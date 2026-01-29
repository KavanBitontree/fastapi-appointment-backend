from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, status, Depends, Response
from sqlalchemy.orm import Session
import secrets
import hashlib

from deps import get_db
from core.enums import UserRole
from models.user import User
from models.patient import Patient
from models.doctor import Doctor
from models.device import Device
from models.refresh_token import RefreshToken
from services.security import hash_password, create_access_token
from schemas.signup import PatientSignupRequest, DoctorSignupRequest

router = APIRouter(prefix="/signup", tags=["Authentication"])


def create_refresh_token(user_id: int, device_id: int, db: Session) -> str:
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
    db.query(RefreshToken).filter(
        RefreshToken.user_id == user_id
    ).update({"revoked": True})
    
    db.query(Device).filter(
        Device.user_id == user_id
    ).update({"is_active": False})
    
    db.commit()


@router.post("/patient")
async def signup_patient(
    request: PatientSignupRequest,
    response: Response,
    device_fingerprint: str = None,
    device_model: str = None,
    db: Session = Depends(get_db)
):
    """
    Patient signup endpoint
    - Creates User, Patient, Device, and RefreshToken entries
    - Returns access token in JSON, refresh token in HttpOnly cookie
    - Enforces single-session per user
    """
    # Check if user already exists
    existing_user = db.query(User).filter(User.email == request.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    try:
        # 1. Create User
        user = User(
            email=request.email,
            hashed_password=hash_password(request.password),
            role=UserRole.PATIENT,
            is_active=True
        )
        db.add(user)
        db.flush()
        
        # 2. Create Patient profile with DOB
        patient = Patient(
            user_id=user.id,
            name=request.name,
            dob=request.dob  # Store date of birth
        )
        db.add(patient)
        
        # 3. Create Device
        device = Device(
            user_id=user.id,
            fingerprint=device_fingerprint or hashlib.sha256(secrets.token_bytes(32)).hexdigest(),
            device_model=device_model or "Unknown Device",
            last_login_at=datetime.utcnow(),
            is_active=True
        )
        db.add(device)
        db.flush()
        
        # 4. Create refresh token
        refresh_token_string = create_refresh_token(user.id, device.id, db)
        
        # 5. Create access token
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
            max_age=30 * 24 * 60 * 60,  # 30 days in seconds
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
            detail=f"Signup failed: {str(e)}"
        )


@router.post("/doctor")
async def signup_doctor(
    request: DoctorSignupRequest,
    response: Response,
    device_fingerprint: str = None,
    device_model: str = None,
    db: Session = Depends(get_db)
):
    """
    Doctor signup endpoint
    - Creates User, Doctor, Device, and RefreshToken entries
    - Returns access token in JSON, refresh token in HttpOnly cookie
    - Enforces single-session per user
    """
    # Check if user already exists
    existing_user = db.query(User).filter(User.email == request.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    try:
        # 1. Create User
        user = User(
            email=request.email,
            hashed_password=hash_password(request.password),
            role=UserRole.DOCTOR,
            is_active=True
        )
        db.add(user)
        db.flush()
        
        # 2. Create Doctor profile
        doctor = Doctor(
            user_id=user.id,
            name=request.name,
            speciality=request.speciality,
            opd_fees=request.opd_fees,
            minimum_slot_duration=request.minimum_slot_duration
        )
        db.add(doctor)
        
        # 3. Create Device
        device = Device(
            user_id=user.id,
            fingerprint=device_fingerprint or hashlib.sha256(secrets.token_bytes(32)).hexdigest(),
            device_model=device_model or "Unknown Device",
            last_login_at=datetime.utcnow(),
            is_active=True
        )
        db.add(device)
        db.flush()
        
        # 4. Create refresh token
        refresh_token_string = create_refresh_token(user.id, device.id, db)
        
        # 5. Create access token
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
            max_age=30 * 24 * 60 * 60,  # 30 days in seconds
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
            detail=f"Signup failed: {str(e)}"
        )