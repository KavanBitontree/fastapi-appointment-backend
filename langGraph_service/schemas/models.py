"""
Pydantic models for LangGraph service requests and responses
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import date, time


class SlotInfo(BaseModel):
    """Slot information for display"""
    id: int
    date: str
    start_time: str
    end_time: str
    doctor_name: str
    doctor_specialization: str
    opd_fees: float


class DoctorInfo(BaseModel):
    """Doctor information for search results"""
    id: int
    name: str
    speciality: str
    opd_fees: float
    address: Optional[str] = None
    distance_km: Optional[float] = None


class AppointmentInfo(BaseModel):
    """Appointment information"""
    id: int
    status: str
    doctor_name: str
    specialization: str
    slot_date: str
    slot_time: str
    opd_fees: float


class ProfileUpdateRequest(BaseModel):
    """Patient profile update request"""
    name: Optional[str] = None
    dob: Optional[date] = None


class ChatRequest(BaseModel):
    """Incoming chat message"""
    message: str
    conversation_id: Optional[str] = None


class ChatResponse(BaseModel):
    """Outgoing chat response"""
    response: str
    conversation_id: str
    suggestions: Optional[List[str]] = None
    data: Optional[dict] = None  # Additional structured data (slots, doctors, etc.)
