from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional

from deps import get_db
from models.patient import Patient
from models.user import User
from middlewares.auth import auth_required, roles_required
from core.enums import UserRole
from schemas.patient import PatientRead

router = APIRouter(prefix="/patients", tags=["Patients"])


@router.get("/{patient_id}", response_model=PatientRead)
def get_patient_by_id(
    patient_id: int,
    current_user: dict = Depends(auth_required()),
    db: Session = Depends(get_db)
):
    """
    Get a single patient by ID
    Accessible by doctors and patients
    """
    # Check if user has required role
    user_role = current_user.get("role")
    allowed_roles = [UserRole.DOCTOR.value, UserRole.PATIENT.value]

    if user_role not in allowed_roles:
        raise HTTPException(
            status_code=403,
            detail="Not authorized for this resource"
        )

    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    return patient


@router.get("/", response_model=PatientRead)
def get_current_patient(
    current_user: dict = Depends(auth_required()),
    db: Session = Depends(get_db)
):
    """
    Get the current patient's profile
    Accessible by patients only
    """
    user_role = current_user.get("role")

    if user_role != UserRole.PATIENT.value:
        raise HTTPException(
            status_code=403,
            detail="Not authorized for this resource"
        )

    # Get the patient associated with the current user
    patient = db.query(Patient).filter(Patient.user_id == current_user.get("user_id")).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient profile not found")

    return patient