from pydantic import BaseModel, EmailStr
from datetime import datetime


class PasswordResetTokenCreate(BaseModel):
    """Schema for creating a password reset token"""
    user_id: int
    token: str
    expires_at: datetime


class PasswordResetTokenRead(BaseModel):
    """Schema for reading password reset token data"""
    id: int
    user_id: int
    token: str
    expires_at: datetime
    used: bool
    created_at: datetime

    class Config:
        from_attributes = True


class ForgotPasswordRequest(BaseModel):
    """Schema for forgot password request"""
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    """Schema for password reset with token"""
    token: str
    new_password: str


class PasswordResetResponse(BaseModel):
    """Schema for password reset responses"""
    message: str
    success: bool