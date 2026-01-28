from pydantic import BaseModel
from datetime import datetime

class RefreshTokenCreate(BaseModel):
    user_id: int
    device_id: int
    expires_at: datetime


class RefreshTokenRead(BaseModel):
    id: int
    user_id: int
    device_id: int
    expires_at: datetime
    revoked: bool

    class Config:
        from_attributes = True
