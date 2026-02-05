from datetime import datetime, timedelta, time, timezone
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
from services.doctor_onboarding_service import setup_default_doctor_availability
from schemas.signup import PatientSignupRequest, DoctorSignupRequest

router = APIRouter(prefix="/signup", tags=["Authentication"])


def create_refresh_token(user_id: int, device_id: int, db: Session) -> str:
    """Create and store a refresh token"""
    token_string = secrets.token_urlsafe(32)
    hashed_token = hashlib.sha256(token_string.encode()).hexdigest()
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
    - Sets access token as HttpOnly cookie for server-side Next.js
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
            dob=request.dob
        )
        db.add(patient)

        # 3. Create Device
        device = Device(
            user_id=user.id,
            fingerprint=device_fingerprint or hashlib.sha256(secrets.token_bytes(32)).hexdigest(),
            device_model=device_model or "Unknown Device",
            last_login_at=datetime.now(timezone.utc),
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
            secure=True,
            samesite="lax",
            max_age=30 * 24 * 60 * 60,  # 30 days
            path="/"
        )

        # Set access token as HttpOnly cookie (for server-side Next.js)
        response.set_cookie(
            key="access_token",
            value=access_token,
            httponly=True,
            secure=True,
            samesite="lax",
            max_age=15 * 60,  # 15 minutes
            path="/"
        )

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
    - Creates User, Doctor (with location), Device, RefreshToken
    - Returns access token in JSON, refresh token in HttpOnly cookie
    - Sets access token as HttpOnly cookie for server-side Next.js
    - AUTOMATICALLY sets up default availability and slots for next 30 days
    """

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

        # 2. Create Doctor profile WITH LOCATION
        doctor = Doctor(
            user_id=user.id,
            name=request.name,
            speciality=request.speciality,
            opd_fees=request.opd_fees,
            minimum_slot_duration=request.minimum_slot_duration,
            address=request.address,
            latitude=request.latitude,
            longitude=request.longitude
        )
        db.add(doctor)
        db.flush()  # Get doctor.id

        # 🆕 3. Setup default availability for next 30 days
        # Use clinic hours from request or default 9 AM - 5 PM
        clinic_start = getattr(request, 'clinic_start_time', time(9, 0))
        clinic_end = getattr(request, 'clinic_end_time', time(17, 0))

        setup_default_doctor_availability(
            db=db,
            doctor=doctor,
            clinic_start=clinic_start,
            clinic_end=clinic_end
        )

        # 4. Create Device
        device = Device(
            user_id=user.id,
            fingerprint=device_fingerprint or hashlib.sha256(secrets.token_bytes(32)).hexdigest(),
            device_model=device_model or "Unknown Device",
            last_login_at=datetime.now(timezone.utc),
            is_active=True
        )
        db.add(device)
        db.flush()

        # 5. Create refresh token
        refresh_token_string = create_refresh_token(user.id, device.id, db)

        # 6. Create access token
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
            secure=True,
            samesite="lax",
            max_age=30 * 24 * 60 * 60,  # 30 days
            path="/"
        )

        # Set access token as HttpOnly cookie (for server-side Next.js)
        response.set_cookie(
            key="access_token",
            value=access_token,
            httponly=True,
            secure=True,
            samesite="lax",
            max_age=15 * 60,  # 15 minutes
            path="/"
        )

        return {
            "access_token": access_token,
            "token_type": "bearer",
            "user_id": user.id,
            "role": user.role.value,
            "message": "Doctor profile created successfully with 30-day availability"
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Signup failed: {str(e)}"
        )