from datetime import datetime, date, time
from typing import List, Optional
from sqlalchemy import String, Integer, Boolean, Time, Date, DateTime, Text, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.database.declarative import Base

class Hospital(Base):
    __tablename__ = "hospitals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    phone: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    timezone: Mapped[str] = mapped_column(String(50), default="UTC")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    settings: Mapped[List["HospitalSetting"]] = relationship("HospitalSetting", back_populates="hospital", cascade="all, delete-orphan")
    working_hours: Mapped[List["WorkingHour"]] = relationship("WorkingHour", back_populates="hospital", cascade="all, delete-orphan")
    departments: Mapped[List["Department"]] = relationship("Department", back_populates="hospital", cascade="all, delete-orphan")
    doctors: Mapped[List["Doctor"]] = relationship("Doctor", back_populates="hospital", cascade="all, delete-orphan")
    holidays: Mapped[List["HospitalHoliday"]] = relationship("HospitalHoliday", back_populates="hospital", cascade="all, delete-orphan")
    patients: Mapped[List["Patient"]] = relationship("Patient", back_populates="hospital", cascade="all, delete-orphan")
    appointments: Mapped[List["Appointment"]] = relationship("Appointment", back_populates="hospital", cascade="all, delete-orphan")
    call_logs: Mapped[List["CallLog"]] = relationship("CallLog", back_populates="hospital", cascade="all, delete-orphan")

class HospitalSetting(Base):
    __tablename__ = "hospital_settings"
    __table_args__ = (UniqueConstraint("hospital_id", "setting_key", name="uq_hospital_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    hospital_id: Mapped[str] = mapped_column(ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False)
    setting_key: Mapped[str] = mapped_column(String(100), nullable=False)
    setting_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    hospital: Mapped["Hospital"] = relationship("Hospital", back_populates="settings")

class WorkingHour(Base):
    __tablename__ = "working_hours"
    __table_args__ = (UniqueConstraint("hospital_id", "day_of_week", name="uq_hospital_day"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    hospital_id: Mapped[str] = mapped_column(ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False)
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)  # 1=Monday, 7=Sunday
    open_time: Mapped[time] = mapped_column(Time, nullable=False)
    close_time: Mapped[time] = mapped_column(Time, nullable=False)
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    hospital: Mapped["Hospital"] = relationship("Hospital", back_populates="working_hours")

class Department(Base):
    __tablename__ = "departments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    hospital_id: Mapped[str] = mapped_column(ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    phone_extension: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    hospital: Mapped["Hospital"] = relationship("Hospital", back_populates="departments")
    doctors: Mapped[List["Doctor"]] = relationship("Doctor", back_populates="department")

class Doctor(Base):
    __tablename__ = "doctors"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    hospital_id: Mapped[str] = mapped_column(ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False)
    department_id: Mapped[str] = mapped_column(ForeignKey("departments.id", ondelete="RESTRICT"), nullable=False)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    license_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    hospital: Mapped["Hospital"] = relationship("Hospital", back_populates="doctors")
    department: Mapped["Department"] = relationship("Department", back_populates="doctors")
    specializations: Mapped[List["DoctorSpecialization"]] = relationship("DoctorSpecialization", back_populates="doctor", cascade="all, delete-orphan")
    schedules: Mapped[List["DoctorSchedule"]] = relationship("DoctorSchedule", back_populates="doctor", cascade="all, delete-orphan")
    leaves: Mapped[List["DoctorLeave"]] = relationship("DoctorLeave", back_populates="doctor", cascade="all, delete-orphan")
    appointments: Mapped[List["Appointment"]] = relationship("Appointment", back_populates="doctor")

class DoctorSpecialization(Base):
    __tablename__ = "doctor_specializations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    doctor_id: Mapped[str] = mapped_column(ForeignKey("doctors.id", ondelete="CASCADE"), nullable=False)
    specialization: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    doctor: Mapped["Doctor"] = relationship("Doctor", back_populates="specializations")

class DoctorSchedule(Base):
    __tablename__ = "doctor_schedules"
    __table_args__ = (UniqueConstraint("doctor_id", "day_of_week", "start_time", name="uq_doctor_day_time"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    doctor_id: Mapped[str] = mapped_column(ForeignKey("doctors.id", ondelete="CASCADE"), nullable=False)
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)  # 1=Monday, 7=Sunday
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    slot_duration_minutes: Mapped[int] = mapped_column(Integer, default=30)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    doctor: Mapped["Doctor"] = relationship("Doctor", back_populates="schedules")

class DoctorLeave(Base):
    __tablename__ = "doctor_leaves"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    doctor_id: Mapped[str] = mapped_column(ForeignKey("doctors.id", ondelete="CASCADE"), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    doctor: Mapped["Doctor"] = relationship("Doctor", back_populates="leaves")

class HospitalHoliday(Base):
    __tablename__ = "hospital_holidays"
    __table_args__ = (UniqueConstraint("hospital_id", "holiday_date", name="uq_hospital_holiday"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    hospital_id: Mapped[str] = mapped_column(ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False)
    holiday_date: Mapped[date] = mapped_column(Date, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    hospital: Mapped["Hospital"] = relationship("Hospital", back_populates="holidays")

class InsuranceProvider(Base):
    __tablename__ = "insurance_providers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    hospital_id: Mapped[str] = mapped_column(ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False)
    provider_name: Mapped[str] = mapped_column(String(150), nullable=False)
    plan_name: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    network_status: Mapped[str] = mapped_column(String(50), default="IN_NETWORK")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    hospital: Mapped["Hospital"] = relationship("Hospital")

class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    hospital_id: Mapped[str] = mapped_column(ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    date_of_birth: Mapped[date] = mapped_column(Date, nullable=False)
    gender: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    insurance_provider_id: Mapped[Optional[str]] = mapped_column(ForeignKey("insurance_providers.id", ondelete="SET NULL"), nullable=True)
    insurance_policy_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    hospital: Mapped["Hospital"] = relationship("Hospital", back_populates="patients")
    insurance_provider: Mapped[Optional["InsuranceProvider"]] = relationship("InsuranceProvider")
    appointments: Mapped[List["Appointment"]] = relationship("Appointment", back_populates="patient", cascade="all, delete-orphan")

class Appointment(Base):
    __tablename__ = "appointments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    hospital_id: Mapped[str] = mapped_column(ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), nullable=False)
    doctor_id: Mapped[str] = mapped_column(ForeignKey("doctors.id", ondelete="RESTRICT"), nullable=False)
    appointment_datetime: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=30)
    status: Mapped[str] = mapped_column(String(50), default="SCHEDULED")
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(50), default="VOICE")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    hospital: Mapped["Hospital"] = relationship("Hospital", back_populates="appointments")
    patient: Mapped["Patient"] = relationship("Patient", back_populates="appointments")
    doctor: Mapped["Doctor"] = relationship("Doctor", back_populates="appointments")
    status_history: Mapped[List["AppointmentStatusHistory"]] = relationship("AppointmentStatusHistory", back_populates="appointment", cascade="all, delete-orphan")
    payment_links: Mapped[List["PaymentLink"]] = relationship("PaymentLink", back_populates="appointment", cascade="all, delete-orphan")
    intake: Mapped[Optional["PatientIntake"]] = relationship("PatientIntake", back_populates="appointment", uselist=False, cascade="all, delete-orphan")

class PatientIntake(Base):
    """Stores post-payment AI medical intake information collected via outbound call."""
    __tablename__ = "patient_intakes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    appointment_id: Mapped[str] = mapped_column(ForeignKey("appointments.id", ondelete="CASCADE"), nullable=False, unique=True)
    has_visited_before: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)  # pehle kahi dikhaya?
    previous_doctor: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)    # kahan dikhaya?
    has_reports: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)           # report hai?
    report_details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)            # kya report?
    current_medicines: Mapped[Optional[str]] = mapped_column(Text, nullable=True)         # abhi koi dawai chal rahi?
    additional_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)          # kuch aur
    raw_transcript: Mapped[Optional[str]] = mapped_column(Text, nullable=True)            # AI ka pura transcript
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    appointment: Mapped["Appointment"] = relationship("Appointment", back_populates="intake")

class AppointmentStatusHistory(Base):
    __tablename__ = "appointment_status_history"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    appointment_id: Mapped[str] = mapped_column(ForeignKey("appointments.id", ondelete="CASCADE"), nullable=False)
    previous_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    new_status: Mapped[str] = mapped_column(String(50), nullable=False)
    changed_by_user_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    change_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    appointment: Mapped["Appointment"] = relationship("Appointment", back_populates="status_history")
