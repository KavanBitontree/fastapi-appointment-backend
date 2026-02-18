"""
Profile management tools for LangGraph chatbot.
Direct DB operations for patient profile.
"""

from sqlalchemy.orm import Session
from typing import Dict, Optional
from datetime import date as dt_date


def get_patient_profile(db: Session, patient_id: int, user_id: int) -> Optional[Dict]:
    """Get patient profile information."""
    from models.patient import Patient
    from models.user import User

    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        return None

    today = dt_date.today()
    age = today.year - patient.dob.year - (
        (today.month, today.day) < (patient.dob.month, patient.dob.day)
    )
    user = db.query(User).filter(User.id == user_id).first()

    return {
        "id": patient.id,
        "user_id": patient.user_id,
        "name": patient.name,
        "dob": patient.dob.isoformat(),
        "age": age,
        "email": user.email if user else "N/A",
    }


def update_patient_name(db: Session, patient_id: int, new_name: str) -> Dict:
    """Update patient name."""
    from models.patient import Patient

    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        return {"success": False, "error": "Patient not found"}

    if not new_name or len(new_name.strip()) < 2:
        return {"success": False, "error": "Name must be at least 2 characters long"}

    patient.name = new_name.strip()
    db.commit()
    db.refresh(patient)
    return {"success": True, "updated_name": patient.name}


def update_patient_dob(db: Session, patient_id: int, new_dob: dt_date) -> Dict:
    """Update patient date of birth."""
    from models.patient import Patient

    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        return {"success": False, "error": "Patient not found"}

    if new_dob >= dt_date.today():
        return {"success": False, "error": "Date of birth must be in the past"}

    patient.dob = new_dob
    db.commit()
    db.refresh(patient)

    today = dt_date.today()
    age = today.year - new_dob.year - ((today.month, today.day) < (new_dob.month, new_dob.day))

    return {"success": True, "updated_dob": new_dob.isoformat(), "age": age}