from fastapi import Request, HTTPException, status, Depends
from jose import jwt, JWTError
from sqlalchemy.orm import Session

from core.config import settings
from core.enums import UserRole
from deps import get_db
from models.device import Device
from models.user import User


async def get_current_user(request: Request, db: Session = Depends(get_db)):
    """
    Dependency to get the current authenticated user.
    Validates JWT token and checks user/device status in database.
    """
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

    # 🔐 DB VALIDATION
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

    # Return user info
    return {
        "user_id": user_id,
        "role": role,
        "device_id": device_id,
    }


def auth_required():
    """
    Dependency to require authentication (any logged-in user).
    
    Usage:
        @router.get("/protected")
        def protected_route(current_user: dict = Depends(auth_required())):
            return {"user": current_user}
    
    Note: For role-based auth, use roles_required() instead.
    """
    return get_current_user


def roles_required(*roles: UserRole):
    """
    Dependency factory to require specific roles.
    
    Usage:
        @router.get("/doctor-only")
        def doctor_endpoint(current_user: dict = Depends(roles_required(UserRole.DOCTOR))):
            return {"user": current_user}
        
        @router.get("/admin-or-doctor")
        def multi_role(current_user: dict = Depends(roles_required(UserRole.ADMIN, UserRole.DOCTOR))):
            return {"user": current_user}
    """
    async def role_checker(current_user: dict = Depends(get_current_user)) -> dict:
        user_role = current_user.get("role")
        allowed_roles = [role.value for role in roles]

        if user_role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized for this resource",
            )

        return current_user
    
    return role_checker