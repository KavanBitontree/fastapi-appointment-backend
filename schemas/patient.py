from pydantic import BaseModel

class PatientCreate(BaseModel):
    user_id: int
    name: str
    age: int


class PatientRead(BaseModel):
    id: int
    user_id: int
    name: str
    age: int

    class Config:
        from_attributes = True
