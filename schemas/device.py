from pydantic import BaseModel
from datetime import datetime

class DeviceCreate(BaseModel):
    fingerprint: str
    device_model: str | None = None


class DeviceRead(BaseModel):
    id: int
    user_id: int
    fingerprint: str
    device_model: str | None
    last_login_at: datetime
    is_active: bool

    class Config:
        from_attributes = True
