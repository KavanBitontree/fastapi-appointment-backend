from pydantic import BaseModel

class DoctorCreate(BaseModel):
    user_id: int
    name: str
    speciality: str


class DoctorRead(BaseModel):
    id: int
    user_id: int
    name: str
    speciality: str

    class Config:
        from_attributes = True
