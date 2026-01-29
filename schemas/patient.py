from pydantic import BaseModel
from datetime import date

class PatientCreate(BaseModel):
    user_id: int
    name: str
    dob: date  # Date of Birth instead of age


class PatientRead(BaseModel):
    id: int
    user_id: int
    name: str
    dob: date  # Date of Birth instead of age

    class Config:
        from_attributes = True
