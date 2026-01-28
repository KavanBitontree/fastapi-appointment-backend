from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy.orm import Session
from schemas.signup import PatientSignupRequest, DoctorSignupRequest, AuthResponse
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

router = APIRouter(prefix="/signup", tags=["Authentication"])


def generate_device_fingerprint() -> str:
    """Generate a dummy device fingerprint for testing"""
    return hashlib.sha256(secrets.token_bytes(32)).hexdigest()


def create_refresh_token(user_id: int, device_id: int, db: Session) -> str:
    """Create and store a refresh token"""
    # Generate a secure random token
    token_string = secrets.token_urlsafe(32)
    
    # Hash the token before storing
    hashed_token = hashlib.sha256(token_string.encode()).hexdigest()
    
    # Set expiry (e.g., 30 days)
    expires_at = datetime.utcnow() + timedelta(days=30)
    
    # Store in database
    refresh_token = RefreshToken(
        user_id=user_id,
        device_id=device_id,
        token=hashed_token,
        expires_at=expires_at,
        revoked=False
    )
    db.add(refresh_token)
    db.commit()
    
    return token_string  # Return the unhashed token to the user


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



@router.post("/patient", response_model=AuthResponse)
async def signup_patient(
    request: PatientSignupRequest,
    db: Session = Depends(get_db)
):
    """
    Patient signup endpoint
    - Creates User, Patient, Device, and RefreshToken entries
    - Returns access token and refresh token for immediate session start
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
        db.flush()  # Get user.id without committing
        
        # 2. Create Patient profile
        patient = Patient(
            user_id=user.id,
            name=request.name,
            age=request.age
        )
        db.add(patient)
        
        # 3. Create Device (dummy for testing)
        device = Device(
            user_id=user.id,
            fingerprint=generate_device_fingerprint(),
            device_model="TestDevice-Browser",
            last_login_at=datetime.utcnow(),
            is_active=True
        )
        db.add(device)
        db.flush()  # Get device.id
        
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
            expires_minutes=15  # Access token expires in 15 minutes
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
            detail=f"Signup failed: {str(e)}"
        )



@router.post("/doctor", response_model=AuthResponse)
async def signup_doctor(
    request: DoctorSignupRequest,
    db: Session = Depends(get_db)
):
    """
    Doctor signup endpoint
    - Creates User, Doctor, Device, and RefreshToken entries
    - Returns access token and refresh token for immediate session start
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
        
        # 3. Create Device (dummy for testing)
        device = Device(
            user_id=user.id,
            fingerprint=generate_device_fingerprint(),
            device_model="TestDevice-Browser",
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
            detail=f"Signup failed: {str(e)}"
        )