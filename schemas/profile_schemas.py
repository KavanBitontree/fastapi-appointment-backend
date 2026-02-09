"""
Profile update schemas for doctors and patients
"""

from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import Optional
from datetime import date
from decimal import Decimal


class DoctorProfileUpdateRequest(BaseModel):
    """Schema for doctor profile updates"""
    
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    speciality: Optional[str] = Field(None, min_length=2, max_length=100)
    opd_fees: Optional[Decimal] = Field(None, ge=0, decimal_places=2)
    minimum_slot_duration: Optional[Decimal] = Field(None, ge=0.25, le=4.0)
    address: Optional[str] = Field(None, min_length=5, max_length=500)
    latitude: Optional[float] = Field(None, ge=-90, le=90)
    longitude: Optional[float] = Field(None, ge=-180, le=180)

    model_config = ConfigDict(from_attributes=True)

    @field_validator('name')
    @classmethod
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("Name cannot be empty")
            if not all(c.isalnum() or c.isspace() or c in ".-'" for c in v):
                raise ValueError("Name contains invalid characters")
        return v

    @field_validator('speciality')
    @classmethod
    def validate_speciality(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("Speciality cannot be empty")
        return v

    @field_validator('minimum_slot_duration')
    @classmethod
    def validate_slot_duration(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        if v is not None:
            allowed_durations = [Decimal('0.25'), Decimal('0.5'), Decimal('1.0'), 
                               Decimal('1.5'), Decimal('2.0'), Decimal('3.0'), 
                               Decimal('4.0')]
            if v not in allowed_durations:
                raise ValueError(
                    f"Slot duration must be one of: {', '.join(str(d) for d in allowed_durations)} hours"
                )
        return v


class PatientProfileUpdateRequest(BaseModel):
    """Schema for patient profile updates"""
    
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    dob: Optional[date] = None

    model_config = ConfigDict(from_attributes=True)

    @field_validator('name')
    @classmethod
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("Name cannot be empty")
            if not all(c.isalnum() or c.isspace() or c in ".-'" for c in v):
                raise ValueError("Name contains invalid characters")
        return v

    @field_validator('dob')
    @classmethod
    def validate_dob(cls, v: Optional[date]) -> Optional[date]:
        if v is not None:
            from datetime import date as dt_date
            today = dt_date.today()
            
            # Must be born before today
            if v >= today:
                raise ValueError("Date of birth must be in the past")
            
            # Must be at least 1 year old
            age = today.year - v.year - ((today.month, today.day) < (v.month, v.day))
            if age < 1:
                raise ValueError("Patient must be at least 1 year old")
            
            # Must be less than 150 years old
            if age > 150:
                raise ValueError("Invalid date of birth (age too high)")
        
        return v


class DoctorProfileResponse(BaseModel):
    """Response schema for doctor profile"""
    
    id: int
    user_id: int
    name: str
    speciality: str
    opd_fees: Decimal
    minimum_slot_duration: Decimal
    address: Optional[str]
    latitude: float
    longitude: float
    email: str  # From user relationship
    
    model_config = ConfigDict(from_attributes=True)


class PatientProfileResponse(BaseModel):
    """Response schema for patient profile"""
    
    id: int
    user_id: int
    name: str
    dob: date
    age: int  # Calculated field
    email: str  # From user relationship
    
    model_config = ConfigDict(from_attributes=True)