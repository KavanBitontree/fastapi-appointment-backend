from pydantic import BaseModel, EmailStr, field_validator
import re


class PasswordValidationMixin:
    """Mixin for password validation"""
    
    @field_validator('password')
    @classmethod
    def validate_password(cls, v: str) -> str:
        """
        Validate password strength:
        - Minimum 8 characters
        - At least 1 uppercase letter
        - At least 1 number
        - At least 1 special character
        """
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
    age: int
    
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
    
    @field_validator('confirm_password')
    @classmethod
    def passwords_match(cls, v: str, info) -> str:
        if 'password' in info.data and v != info.data['password']:
            raise ValueError('Passwords do not match')
        return v