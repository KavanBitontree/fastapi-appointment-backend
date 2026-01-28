from pydantic import BaseModel, EmailStr
from core.enums import UserRole

class UserCreate(BaseModel):
    email: EmailStr
    password: str
    role: UserRole


class UserRead(BaseModel):
    id: int
    email: EmailStr
    role: UserRole
    is_active: bool

    class Config:
        from_attributes = True
