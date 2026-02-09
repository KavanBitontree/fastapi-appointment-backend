"""
Profile management routes for doctors and patients
"""

from fastapi import APIRouter, Depends, HTTPException, Security, status
from sqlalchemy.orm import Session
from datetime import date as dt_date

from core.security_schemes import bearer_scheme
from deps import get_db
from middlewares.auth import roles_required
from core.enums import UserRole
from models.doctor import Doctor
from models.patient import Patient
from models.user import User
from schemas.profile_schemas import (
    DoctorProfileUpdateRequest,
    PatientProfileUpdateRequest,
    DoctorProfileResponse,
    PatientProfileResponse,
)

router = APIRouter(
    prefix="/profile",
    tags=["Profile"]
)


# ─────────────────────────────────────────────────────────────
# 📋 GET DOCTOR PROFILE
# ─────────────────────────────────────────────────────────────
@router.get("/doctor", dependencies=[Security(bearer_scheme)], response_model=DoctorProfileResponse)
async def get_doctor_profile(
    current_user: dict = Depends(roles_required(UserRole.DOCTOR)),
    db: Session = Depends(get_db)
):
    """
    Get current doctor's profile information.
    """
    doctor = db.query(Doctor).filter(
        Doctor.user_id == current_user["user_id"]
    ).first()
    
    if not doctor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Doctor profile not found"
        )
    
    # Get user email
    user = db.query(User).filter(User.id == current_user["user_id"]).first()
    
    return DoctorProfileResponse(
        id=doctor.id,
        user_id=doctor.user_id,
        name=doctor.name,
        speciality=doctor.speciality,
        opd_fees=doctor.opd_fees,
        minimum_slot_duration=doctor.minimum_slot_duration,
        address=doctor.address,
        latitude=doctor.latitude,
        longitude=doctor.longitude,
        email=user.email if user else ""
    )


# ─────────────────────────────────────────────────────────────
# ✏️ UPDATE DOCTOR PROFILE
# ─────────────────────────────────────────────────────────────
@router.patch("/doctor", dependencies=[Security(bearer_scheme)], response_model=DoctorProfileResponse)
async def update_doctor_profile(
    updates: DoctorProfileUpdateRequest,
    current_user: dict = Depends(roles_required(UserRole.DOCTOR)),
    db: Session = Depends(get_db)
):
    """
    Update doctor's profile information.
    Only provided fields will be updated (partial update).
    
    Fields that can be updated:
    - name
    - speciality
    - opd_fees
    - minimum_slot_duration
    - address
    - latitude
    - longitude
    """
    doctor = db.query(Doctor).filter(
        Doctor.user_id == current_user["user_id"]
    ).first()
    
    if not doctor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Doctor profile not found"
        )
    
    # Update only provided fields
    update_data = updates.model_dump(exclude_unset=True)
    
    # Validate location fields - if updating location, all 3 must be provided
    location_fields = {'address', 'latitude', 'longitude'}
    provided_location_fields = location_fields & set(update_data.keys())
    
    if provided_location_fields and len(provided_location_fields) != len(location_fields):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="When updating location, address, latitude, and longitude must all be provided"
        )
    
    # Apply updates
    for field, value in update_data.items():
        setattr(doctor, field, value)
    
    db.commit()
    db.refresh(doctor)
    
    # Get user email
    user = db.query(User).filter(User.id == current_user["user_id"]).first()
    
    return DoctorProfileResponse(
        id=doctor.id,
        user_id=doctor.user_id,
        name=doctor.name,
        speciality=doctor.speciality,
        opd_fees=doctor.opd_fees,
        minimum_slot_duration=doctor.minimum_slot_duration,
        address=doctor.address,
        latitude=doctor.latitude,
        longitude=doctor.longitude,
        email=user.email if user else ""
    )


# ─────────────────────────────────────────────────────────────
# 📋 GET PATIENT PROFILE
# ─────────────────────────────────────────────────────────────
@router.get("/patient", dependencies=[Security(bearer_scheme)], response_model=PatientProfileResponse)
async def get_patient_profile(
    current_user: dict = Depends(roles_required(UserRole.PATIENT)),
    db: Session = Depends(get_db)
):
    """
    Get current patient's profile information.
    """
    patient = db.query(Patient).filter(
        Patient.user_id == current_user["user_id"]
    ).first()
    
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient profile not found"
        )
    
    # Calculate age
    today = dt_date.today()
    age = today.year - patient.dob.year - ((today.month, today.day) < (patient.dob.month, patient.dob.day))
    
    # Get user email
    user = db.query(User).filter(User.id == current_user["user_id"]).first()
    
    return PatientProfileResponse(
        id=patient.id,
        user_id=patient.user_id,
        name=patient.name,
        dob=patient.dob,
        age=age,
        email=user.email if user else ""
    )


# ─────────────────────────────────────────────────────────────
# ✏️ UPDATE PATIENT PROFILE
# ─────────────────────────────────────────────────────────────
@router.patch("/patient", dependencies=[Security(bearer_scheme)], response_model=PatientProfileResponse)
async def update_patient_profile(
    updates: PatientProfileUpdateRequest,
    current_user: dict = Depends(roles_required(UserRole.PATIENT)),
    db: Session = Depends(get_db)
):
    """
    Update patient's profile information.
    Only provided fields will be updated (partial update).
    
    Fields that can be updated:
    - name
    - dob (date of birth)
    """
    patient = db.query(Patient).filter(
        Patient.user_id == current_user["user_id"]
    ).first()
    
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient profile not found"
        )
    
    # Update only provided fields
    update_data = updates.model_dump(exclude_unset=True)
    
    for field, value in update_data.items():
        setattr(patient, field, value)
    
    db.commit()
    db.refresh(patient)
    
    # Calculate age
    today = dt_date.today()
    age = today.year - patient.dob.year - ((today.month, today.day) < (patient.dob.month, patient.dob.day))
    
    # Get user email
    user = db.query(User).filter(User.id == current_user["user_id"]).first()
    
    return PatientProfileResponse(
        id=patient.id,
        user_id=patient.user_id,
        name=patient.name,
        dob=patient.dob,
        age=age,
        email=user.email if user else ""
    )