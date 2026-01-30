from pydantic import BaseModel
from decimal import Decimal
from typing import Optional

class DoctorCreate(BaseModel):
    user_id: int
    name: str
    speciality: str
    opd_fees: Decimal
    minimum_slot_duration: Decimal
    latitude: float
    longitude: float
    address: Optional[str] = None


class DoctorRead(BaseModel):
    id: int
    user_id: int
    name: str
    speciality: str
    opd_fees: Decimal
    minimum_slot_duration: Decimal
    latitude: float
    longitude: float
    address: Optional[str] = None

    class Config:
        from_attributes = True
