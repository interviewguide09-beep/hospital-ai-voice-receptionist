from datetime import datetime, date, time
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field

class HospitalDomain(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    slug: str
    address: Optional[str] = None
    phone: str
    email: Optional[str] = None
    timezone: str = "UTC"
    is_active: bool = True

class DoctorDomain(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    hospital_id: str
    department_id: str
    first_name: str
    last_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    license_number: Optional[str] = None
    is_active: bool = True

    @property
    def full_name(self) -> str:
        return f"Dr. {self.first_name} {self.last_name}"

class PatientDomain(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    hospital_id: str
    first_name: str
    last_name: str
    date_of_birth: date
    gender: Optional[str] = None
    phone: str
    email: Optional[str] = None
    insurance_provider_id: Optional[str] = None
    insurance_policy_number: Optional[str] = None

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

class AppointmentDomain(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    hospital_id: str
    patient_id: str
    doctor_id: str
    appointment_datetime: datetime
    duration_minutes: int = 30
    status: str = "SCHEDULED"
    reason: Optional[str] = None
    source: str = "VOICE"

class SlotDomain(BaseModel):
    """Business entity representing a time slot for scheduling."""
    model_config = ConfigDict(from_attributes=True)

    doctor_id: str
    available_date: date
    start_time: time
    end_time: time
    is_booked: bool = False
