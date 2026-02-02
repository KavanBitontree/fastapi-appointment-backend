from pydantic import BaseModel, Field, validator
from datetime import date, time
from typing import List, Optional


class DoctorAvailabilityCreate(BaseModel):
    date: date
    start_time: time
    end_time: time
    is_available: bool = True

    @validator('end_time')
    def end_time_must_be_after_start_time(cls, v, values):
        if 'start_time' in values and v <= values['start_time']:
            raise ValueError('end_time must be after start_time')
        return v

    @validator('date')
    def date_must_be_present_or_future(cls, v):
        if v < date.today():
            raise ValueError('Cannot create availability for past dates')
        return v


class DoctorAvailabilityUpdate(BaseModel):
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    is_available: Optional[bool] = None

    @validator('end_time')
    def end_time_must_be_after_start_time(cls, v, values):
        if v and 'start_time' in values and values['start_time']:
            if v <= values['start_time']:
                raise ValueError('end_time must be after start_time')
        return v


class DoctorAvailabilityResponse(BaseModel):
    id: int
    doctor_id: int
    date: date
    start_time: time
    end_time: time
    is_available: bool

    class Config:
        from_attributes = True


class BlockSlotRequest(BaseModel):
    """Request to block a single slot"""
    slot_id: int = Field(..., description="ID of the slot to block")


class BulkBlockSlotsRequest(BaseModel):
    """Request to block multiple slots at once"""
    slot_ids: List[int] = Field(
        ..., 
        description="List of slot IDs to block",
        min_items=1,
        max_items=50  # Prevent abuse
    )


class SlotResponse(BaseModel):
    """Response model for slot operations"""
    id: int
    doctor_id: int
    date: date
    start_time: time
    end_time: time
    status: str

    class Config:
        from_attributes = True