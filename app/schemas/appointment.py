from datetime import datetime, date, time
from typing import List, Optional
from pydantic import BaseModel, EmailStr, Field, ConfigDict

class HospitalBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    slug: str = Field(..., min_length=2, max_length=100)
    address: Optional[str] = None
    phone: str = Field(..., max_length=20)
    email: Optional[EmailStr] = None
    timezone: str = "UTC"

class HospitalCreate(HospitalBase):
    pass

class HospitalRead(HospitalBase):
    model_config = ConfigDict(from_attributes=True)
    id: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

class DepartmentBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    description: Optional[str] = None
    phone_extension: Optional[str] = Field(None, max_length=10)

class DepartmentCreate(DepartmentBase):
    hospital_id: str

class DepartmentRead(DepartmentBase):
    model_config = ConfigDict(from_attributes=True)
    id: str
    hospital_id: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

class DoctorBase(BaseModel):
    first_name: str = Field(..., min_length=2, max_length=100)
    last_name: str = Field(..., min_length=2, max_length=100)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(None, max_length=20)
    license_number: Optional[str] = Field(None, max_length=100)

class DoctorCreate(DoctorBase):
    hospital_id: str
    department_id: str
    specializations: List[str] = []

class DoctorRead(DoctorBase):
    model_config = ConfigDict(from_attributes=True)
    id: str
    hospital_id: str
    department_id: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

class PatientBase(BaseModel):
    first_name: str = Field(..., min_length=2, max_length=100)
    last_name: str = Field(..., min_length=2, max_length=100)
    date_of_birth: date
    gender: Optional[str] = Field(None, max_length=20)
    phone: str = Field(..., max_length=20)
    email: Optional[EmailStr] = None
    insurance_provider_id: Optional[str] = None
    insurance_policy_number: Optional[str] = Field(None, max_length=100)

class PatientCreate(PatientBase):
    hospital_id: str

class PatientRead(PatientBase):
    model_config = ConfigDict(from_attributes=True)
    id: str
    hospital_id: str
    created_at: datetime
    updated_at: datetime

class AppointmentBase(BaseModel):
    appointment_datetime: datetime
    duration_minutes: int = 30
    reason: Optional[str] = None
    source: str = "VOICE"

class AppointmentCreate(AppointmentBase):
    hospital_id: str
    patient_id: str
    doctor_id: str

class AppointmentUpdate(BaseModel):
    appointment_datetime: Optional[datetime] = None
    duration_minutes: Optional[int] = None
    status: Optional[str] = None
    reason: Optional[str] = None

class AppointmentRead(AppointmentBase):
    model_config = ConfigDict(from_attributes=True)
    id: str
    hospital_id: str
    patient_id: str
    doctor_id: str
    status: str
    created_at: datetime
    updated_at: datetime

class SlotQuery(BaseModel):
    doctor_id: str
    start_date: date
    end_date: date

class AvailableSlot(BaseModel):
    doctor_id: str
    date: date
    start_time: time
    end_time: time

class AvailableSlotsResponse(BaseModel):
    doctor_id: str
    slots: List[AvailableSlot]
