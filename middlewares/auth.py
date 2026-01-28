from functools import wraps
from fastapi import Request, HTTPException, status
from jose import jwt, JWTError
from sqlalchemy.orm import Session

from core.config import settings
from core.enums import UserRole
from deps import get_db
from models.device import Device
from models.user import User


def auth_required(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        request: Request = kwargs.get("request")

        if not request:
            raise RuntimeError("Request object not found in route")

        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authorization header missing",
            )

        token = auth_header.split(" ")[1]

        try:
            payload = jwt.decode(
                token,
                settings.JWT_SECRET_KEY,
                algorithms=[settings.JWT_ALGORITHM],
            )
        except JWTError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
            )

        user_id = payload.get("user_id")
        device_id = payload.get("device_id")
        role = payload.get("role")

        if not user_id or not device_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload",
            )

        # 🔐 DB VALIDATION (THIS IS THE FIX)
        db: Session = next(get_db())

        # 1. Check user still exists & active
        user = db.query(User).filter(
            User.id == user_id,
            User.is_active == True
        ).first()

        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User account is inactive or deleted",
            )

        # 2. Check device session is still active
        device = db.query(Device).filter(
            Device.id == device_id,
            Device.user_id == user_id,
            Device.is_active == True
        ).first()

        if not device:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session expired due to login from another device",
            )

        # Attach verified user info to request state
        request.state.user = {
            "user_id": user_id,
            "role": role,
            "device_id": device_id,
        }

        return await func(*args, **kwargs)

    return wrapper


def roles_required(*roles: UserRole):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            request: Request = kwargs.get("request")

            if not request or not hasattr(request.state, "user"):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication required",
                )

            user_role = request.state.user.get("role")
            allowed_roles = [role.value for role in roles]

            if user_role not in allowed_roles:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Not authorized for this resource",
                )

            return await func(*args, **kwargs)

        return wrapper

    return decorator
