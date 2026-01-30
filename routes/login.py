from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, status, Depends, Request, Response,Security
from sqlalchemy.orm import Session
import secrets
import hashlib

from deps import get_db
from models.user import User
from models.device import Device
from models.refresh_token import RefreshToken
from services.security import verify_password, create_access_token
from middlewares.auth import auth_required
from schemas.login import LoginRequest, MessageResponse

from core.security_schemes import bearer_scheme

router = APIRouter(prefix="/auth", tags=["Authentication"])


def create_refresh_token_for_device(user_id: int, device_id: int, db: Session) -> str:
    """Create and store a refresh token"""
    token_string = secrets.token_urlsafe(32)
    hashed_token = hashlib.sha256(token_string.encode()).hexdigest()
    # Store timezone-aware UTC timestamp (column is timezone=True)
    expires_at = datetime.now(timezone.utc) + timedelta(days=30)

    refresh_token = RefreshToken(
        user_id=user_id,
        device_id=device_id,
        token=hashed_token,
        expires_at=expires_at,
        revoked=False
    )
    db.add(refresh_token)
    db.commit()

    return token_string


def revoke_all_user_sessions(user_id: int, db: Session):
    """Revoke all refresh tokens and deactivate all devices for a user"""
    db.query(RefreshToken).filter(
        RefreshToken.user_id == user_id
    ).update({"revoked": True})

    db.query(Device).filter(
        Device.user_id == user_id
    ).update({"is_active": False})

    db.commit()


@router.get("/check-session")
async def check_session(
    email: str,
    db: Session = Depends(get_db)
):
    """
    Check if user has active sessions on other devices
    Returns device info if sessions exist
    """
    user = db.query(User).filter(User.email == email).first()
    if not user:
        return {"has_active_session": False}

    # Get active devices
    active_devices = db.query(Device).filter(
        Device.user_id == user.id,
        Device.is_active == True
    ).all()

    if not active_devices:
        return {"has_active_session": False}

    # Return the most recent active device
    latest_device = max(active_devices, key=lambda d: d.last_login_at)

    return {
        "has_active_session": True,
        "device_model": latest_device.device_model,
        "last_login_at": latest_device.last_login_at.isoformat()
    }


@router.post("/login")
async def login(
    request: LoginRequest,
    response: Response,
    device_fingerprint: str = None,
    device_model: str = None,
    force_login: bool = False,
    db: Session = Depends(get_db)
):
    """
    Login endpoint with single-session enforcement
    - Revokes all existing sessions for the user (if force_login=True)
    - Creates new device and session
    - Returns access token in JSON, refresh token in HttpOnly cookie
    """
    # 1. Find user
    user = db.query(User).filter(User.email == request.email).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )

    # 2. Verify password
    if not verify_password(request.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )

    # 3. Check if user is active
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated"
        )

    # 4. Check for existing active sessions (if not force_login)
    if not force_login:
        active_devices = db.query(Device).filter(
            Device.user_id == user.id,
            Device.is_active == True
        ).all()

        if active_devices:
            latest_device = max(active_devices, key=lambda d: d.last_login_at)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "message": "Already logged in from another device",
                    "device_model": latest_device.device_model,
                    "last_login_at": latest_device.last_login_at.isoformat()
                }
            )

    try:
        # 5. ENFORCE SINGLE SESSION: Revoke all existing sessions
        revoke_all_user_sessions(user.id, db)

        # 6. Create new device
        device = Device(
            user_id=user.id,
            fingerprint=device_fingerprint or hashlib.sha256(secrets.token_bytes(32)).hexdigest(),
            device_model=device_model or "Unknown Device",
            last_login_at=datetime.now(timezone.utc),
            is_active=True
        )
        db.add(device)
        db.flush()

        # 7. Create refresh token
        refresh_token_string = create_refresh_token_for_device(user.id, device.id, db)

        # 8. Create access token
        access_token = create_access_token(
            data={
                "user_id": user.id,
                "email": user.email,
                "role": user.role.value,
                "device_id": device.id
            },
            expires_minutes=15
        )

        db.commit()

        # Set refresh token as HttpOnly cookie
        response.set_cookie(
            key="refresh_token",
            value=refresh_token_string,
            httponly=True,
            secure=True,  # Set to True in production with HTTPS
            samesite="lax",
            max_age=30 * 24 * 60 * 60,  # 30 days
            path="/"
        )

        # Return only access token in response body
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "user_id": user.id,
            "role": user.role.value,
            "device_model": device.device_model
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Login failed: {str(e)}"
        )


@router.post("/refresh")
async def refresh_access_token(
    request: Request,
    response: Response,
    db: Session = Depends(get_db)
):
    """
    Refresh access token using refresh token from HttpOnly cookie
    - Validates refresh token from cookie
    - Checks if token is revoked or expired
    - Issues new access token
    """
    # Get refresh token from cookie
    refresh_token_string = request.cookies.get("refresh_token")

    if not refresh_token_string:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token not found"
        )

    # Hash the token to compare with stored hash
    hashed_token = hashlib.sha256(refresh_token_string.encode()).hexdigest()

    refresh_token = db.query(RefreshToken).filter(
        RefreshToken.token == hashed_token
    ).first()

    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token"
        )

    if refresh_token.revoked:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has been revoked. Please login again."
        )

    # Compare using timezone-aware UTC datetimes to avoid naive/aware TypeError
    now_utc = datetime.now(timezone.utc)
    expires_at = refresh_token.expires_at
    if expires_at is not None and expires_at.tzinfo is None:
        # If stored value is naive (legacy rows), assume it's UTC
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if expires_at and expires_at < now_utc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has expired. Please login again."
        )

    device = db.query(Device).filter(Device.id == refresh_token.device_id).first()
    if not device or not device.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Device is no longer active. Please login again."
        )

    user = db.query(User).filter(User.id == refresh_token.user_id).first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is not active"
        )

    # Create new access token
    access_token = create_access_token(
        data={
            "user_id": user.id,
            "email": user.email,
            "role": user.role.value,
            "device_id": device.id
        },
        expires_minutes=15
    )

    # Update device last login
    device.last_login_at = datetime.now(timezone.utc)
    db.commit()

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user_id": user.id,
        "role": user.role.value,
        "device_model": device.device_model
    }


@router.post("/logout", dependencies=[Security(bearer_scheme)],response_model=MessageResponse)
async def logout(
    request: Request,
    response: Response,
    current_user: dict = Depends(auth_required()),
    db: Session = Depends(get_db)
):
    """
    Logout endpoint
    - Revokes current device's refresh tokens
    - Deactivates current device
    - Clears refresh token cookie
    """
    device_id = current_user.get("device_id")

    if not device_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid session"
        )

    try:
        # Revoke all refresh tokens for this device
        db.query(RefreshToken).filter(
            RefreshToken.device_id == device_id
        ).update({"revoked": True})

        # Deactivate device
        db.query(Device).filter(
            Device.id == device_id
        ).update({"is_active": False})

        db.commit()

        # Clear the refresh token cookie
        response.delete_cookie(key="refresh_token", path="/")

        return MessageResponse(message="Logged out successfully")

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Logout failed: {str(e)}"
        )


@router.post("/logout-all", dependencies=[Security(bearer_scheme)],response_model=MessageResponse)
async def logout_all_devices(
    request: Request,
    response: Response,
    current_user: dict = Depends(auth_required()),
    db: Session = Depends(get_db)
):
    """
    Logout from all devices
    - Revokes all refresh tokens for the user
    - Deactivates all devices for the user
    - Clears refresh token cookie
    """
    user_id = current_user.get("user_id")

    try:
        revoke_all_user_sessions(user_id, db)

        # Clear the refresh token cookie
        response.delete_cookie(key="refresh_token", path="/")

        return MessageResponse(message="Logged out from all devices successfully")

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Logout all failed: {str(e)}"
        )


@router.get("/me",dependencies=[Security(bearer_scheme)])
async def get_current_user(
    request: Request,
    current_user: dict = Depends(auth_required()),
    db: Session = Depends(get_db)
):
    """
    Get current user information
    - Protected route to test authentication
    """
    user_id = current_user.get("user_id")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    return {
        "user_id": user.id,
        "email": user.email,
        "role": user.role.value,
        "is_active": user.is_active
    }