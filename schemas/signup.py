from pydantic import BaseModel, EmailStr, field_validator
from datetime import date
import re


class PasswordValidationMixin:
    """Mixin for password validation"""

    @field_validator('password')
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters long')

        if not re.search(r'[A-Z]', v):
            raise ValueError('Password must contain at least one uppercase letter')

        if not re.search(r'[0-9]', v):
            raise ValueError('Password must contain at least one number')

        if not re.search(r'[!@#$%^&*(),.?":{}|<>]', v):
            raise ValueError('Password must contain at least one special character')

        return v


class PatientSignupRequest(BaseModel, PasswordValidationMixin):
    email: EmailStr
    password: str
    confirm_password: str
    name: str
    dob: date

    @field_validator('dob')
    @classmethod
    def validate_dob(cls, v: date) -> date:
        today = date.today()
        if v > today:
            raise ValueError('Date of birth cannot be in the future')

        age = today.year - v.year - ((today.month, today.day) < (v.month, v.day))
        if age < 0 or age > 150:
            raise ValueError('Invalid date of birth')

        return v

    @field_validator('confirm_password')
    @classmethod
    def passwords_match(cls, v: str, info) -> str:
        if 'password' in info.data and v != info.data['password']:
            raise ValueError('Passwords do not match')
        return v


class DoctorSignupRequest(BaseModel, PasswordValidationMixin):
    email: EmailStr
    password: str
    confirm_password: str

    name: str
    speciality: str
    opd_fees: float
    minimum_slot_duration: float

    # 📍 Location fields (NEW)
    address: str
    latitude: float
    longitude: float

    @field_validator('confirm_password')
    @classmethod
    def passwords_match(cls, v: str, info) -> str:
        if 'password' in info.data and v != info.data['password']:
            raise ValueError('Passwords do not match')
        return v
