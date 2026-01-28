from pydantic import BaseModel, EmailStr

class PatientSignupRequest(BaseModel):
    email: EmailStr
    password: str
    name: str
    age: int


class DoctorSignupRequest(BaseModel):
    email: EmailStr
    password: str
    name: str
    speciality: str
    opd_fees: float
    minimum_slot_duration: float


class AuthResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user_id: int
    role: str