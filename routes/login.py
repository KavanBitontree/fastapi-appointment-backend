from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, status, Depends, Request
from sqlalchemy.orm import Session
from schemas.login import LoginRequest, RefreshTokenRequest, AuthResponse, MessageResponse
import secrets
import hashlib

from deps import get_db
from models.user import User
from models.device import Device
from models.refresh_token import RefreshToken
from services.security import verify_password, create_access_token
from middlewares.auth import auth_required
from core.security_schemes import bearer_scheme

router = APIRouter(prefix="/auth", tags=["Authentication"])


def generate_device_fingerprint() -> str:
    """Generate a dummy device fingerprint for testing"""
    return hashlib.sha256(secrets.token_bytes(32)).hexdigest()


def create_refresh_token_for_device(user_id: int, device_id: int, db: Session) -> str:
    """Create and store a refresh token"""
    token_string = secrets.token_urlsafe(32)
    hashed_token = hashlib.sha256(token_string.encode()).hexdigest()
    expires_at = datetime.utcnow() + timedelta(days=30)
    
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
    # Revoke all refresh tokens
    db.query(RefreshToken).filter(
        RefreshToken.user_id == user_id
    ).update({"revoked": True})
    
    # Deactivate all devices
    db.query(Device).filter(
        Device.user_id == user_id
    ).update({"is_active": False})
    
    db.commit()


@router.post("/login", response_model=AuthResponse)
async def login(
    request: LoginRequest,
    db: Session = Depends(get_db)
):
    """
    Login endpoint with single-session enforcement
    - Revokes all existing sessions for the user
    - Creates new device and session
    - Returns access token and refresh token
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
    
    try:
        # 4. ENFORCE SINGLE SESSION: Revoke all existing sessions
        revoke_all_user_sessions(user.id, db)
        
        # 5. Create new device
        device = Device(
            user_id=user.id,
            fingerprint=generate_device_fingerprint(),
            device_model="TestDevice-Browser",
            last_login_at=datetime.utcnow(),
            is_active=True
        )
        db.add(device)
        db.flush()
        
        # 6. Create refresh token
        refresh_token_string = create_refresh_token_for_device(user.id, device.id, db)
        
        # 7. Create access token
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
        
        return AuthResponse(
            access_token=access_token,
            refresh_token=refresh_token_string,
            user_id=user.id,
            role=user.role.value
        )
        
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Login failed: {str(e)}"
        )


@router.post("/refresh", response_model=AuthResponse)
async def refresh_access_token(
    request: RefreshTokenRequest,
    db: Session = Depends(get_db)
):
    """
    Refresh access token using refresh token
    - Validates refresh token
    - Checks if token is revoked or expired
    - Issues new access token (and optionally new refresh token)
    """
    # Hash the provided token to compare with stored hash
    hashed_token = hashlib.sha256(request.refresh_token.encode()).hexdigest()
    
    # Find the refresh token in database
    refresh_token = db.query(RefreshToken).filter(
        RefreshToken.token == hashed_token
    ).first()
    
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token"
        )
    
    # Check if token is revoked
    if refresh_token.revoked:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has been revoked. Please login again."
        )
    
    # Check if token is expired
    if refresh_token.expires_at < datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has expired. Please login again."
        )
    
    # Check if device is still active
    device = db.query(Device).filter(Device.id == refresh_token.device_id).first()
    if not device or not device.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Device is no longer active. Please login again."
        )
    
    # Get user
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
    device.last_login_at = datetime.utcnow()
    db.commit()
    
    # Return the same refresh token (or generate a new one for rotation)
    return AuthResponse(
        access_token=access_token,
        refresh_token=request.refresh_token,  # Keep same refresh token
        user_id=user.id,
        role=user.role.value
    )


@router.post("/logout",dependencies=[Depends(bearer_scheme)], response_model=MessageResponse)
@auth_required
async def logout(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Logout endpoint
    - Revokes current device's refresh tokens
    - Deactivates current device
    - User must login again to access
    """
    user_data = request.state.user
    device_id = user_data.get("device_id")
    
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
        
        return MessageResponse(message="Logged out successfully")
        
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Logout failed: {str(e)}"
        )


@router.post("/logout-all", response_model=MessageResponse)
@auth_required
async def logout_all_devices(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Logout from all devices
    - Revokes all refresh tokens for the user
    - Deactivates all devices for the user
    - User must login again on all devices
    """
    user_data = request.state.user
    user_id = user_data.get("user_id")
    
    try:
        revoke_all_user_sessions(user_id, db)
        
        return MessageResponse(message="Logged out from all devices successfully")
        
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Logout all failed: {str(e)}"
        )


@router.get("/me", dependencies=[Depends(bearer_scheme)])
@auth_required
async def get_current_user(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Get current user information
    - Protected route to test authentication
    """
    user_data = request.state.user
    user_id = user_data.get("user_id")
    
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