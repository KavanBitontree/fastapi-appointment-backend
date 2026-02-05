from pydantic import BaseModel, Field, field_validator
from typing import Optional
from datetime import datetime
from core.enums import AppointmentStatus


# ──────────────────────────────────────────────────────────────
# REQUEST SCHEMAS
# ──────────────────────────────────────────────────────────────

class AppointmentCreateRequest(BaseModel):
    doctor_id: int = Field(..., gt=0)
    slot_id: int = Field(..., gt=0)
    report_url: Optional[str] = None  # Cloudinary URL from frontend

    @field_validator('report_url')
    @classmethod
    def validate_report_url(cls, v):
        if v and not v.startswith('https://res.cloudinary.com/'):
            raise ValueError('Invalid Cloudinary URL')
        return v


class AppointmentUpdateStatus(BaseModel):
    status: AppointmentStatus
    rejection_reason: Optional[str] = None


# ──────────────────────────────────────────────────────────────
# RESPONSE SCHEMAS
# ──────────────────────────────────────────────────────────────

class SlotInAppointment(BaseModel):
    id: int
    date: str
    start_time: str
    end_time: str

    class Config:
        from_attributes = True


class DoctorInAppointment(BaseModel):
    id: int
    name: str
    speciality: str
    opd_fees: str

    class Config:
        from_attributes = True


class PatientInAppointment(BaseModel):
    id: int
    name: str
    dob: str  # Date of birth instead of age
    
    class Config:
        from_attributes = True
        
    @property
    def age(self) -> int:
        """Calculate age from date of birth"""
        from datetime import date
        if isinstance(self.dob, str):
            dob_date = date.fromisoformat(self.dob)
        else:
            dob_date = self.dob
        today = date.today()
        return today.year - dob_date.year - ((today.month, today.day) < (dob_date.month, dob_date.day))


class AppointmentResponse(BaseModel):
    id: int
    doctor_id: int
    patient_id: int
    slot_id: int
    status: str
    report: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    
    # Nested relationships
    doctor: DoctorInAppointment
    patient: PatientInAppointment
    slot: SlotInAppointment

    class Config:
        from_attributes = True


class AppointmentListResponse(BaseModel):
    total: int
    appointments: list[AppointmentResponse]


class AppointmentCreateResponse(BaseModel):
    appointment_id: int
    status: str
    message: str
    slot_id: int
    doctor_name: str