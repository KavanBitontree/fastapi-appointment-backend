"""
routes/bot_profile.py
=====================
FastAPI routes that expose the LangGraph profile tools as REST endpoints
for n8n HTTP Request tool nodes.

Tools replicated (exact logic from langGraph_service/tools/profile_tools.py):
  1. GET   /bot/profile/me        ← get_patient_profile
  2. PATCH /bot/profile/name      ← update_patient_name
  3. PATCH /bot/profile/dob       ← update_patient_dob

All routes: PATIENT role only.
Patient identity is ALWAYS resolved from the JWT — never from request body.
"""

from fastapi import APIRouter, Depends, HTTPException, Security
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field, field_validator
from typing import Optional
from datetime import date as dt_date

from core.security_schemes import bearer_scheme
from deps import get_db
from middlewares.auth import roles_required
from core.enums import UserRole
from models.patient import Patient

# ── Tool implementations ──────────────────────────────────────────────────────
from langGraph_service.tools.profile_tools import (
    get_patient_profile,
    update_patient_name,
    update_patient_dob,
)


router = APIRouter(
    prefix="/bot/profile",
    tags=["n8n Bot — Profile"],
    dependencies=[Security(bearer_scheme)],
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_patient(db: Session, user_id: int) -> Patient:
    """Resolve Patient from authenticated user_id. Raises 404 if missing."""
    patient = db.query(Patient).filter(Patient.user_id == user_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient profile not found for this user.")
    return patient


# ── Request / Response schemas ────────────────────────────────────────────────

class ProfileResponse(BaseModel):
    """
    Exact keys returned by get_patient_profile():
      id, user_id, name, dob, age, email
    """
    id: int
    user_id: int
    name: str
    dob: str = Field(..., description="Date of birth in YYYY-MM-DD format.")
    age: int
    email: str


class UpdateNameRequest(BaseModel):
    new_name: str = Field(
        ...,
        min_length=2,
        description="New display name for the patient. Minimum 2 characters.",
        examples=["Rahul Sharma"],
    )


class UpdateNameResponse(BaseModel):
    success: bool
    updated_name: Optional[str] = None
    error: Optional[str] = None


class UpdateDobRequest(BaseModel):
    new_dob: str = Field(
        ...,
        description="New date of birth in YYYY-MM-DD format. Must be in the past.",
        examples=["1990-05-15"],
    )

    @field_validator("new_dob")
    @classmethod
    def validate_dob_format(cls, v: str) -> str:
        try:
            dt_date.fromisoformat(v)
        except ValueError:
            raise ValueError(f"Invalid date format '{v}'. Use YYYY-MM-DD.")
        return v


class UpdateDobResponse(BaseModel):
    success: bool
    updated_dob: Optional[str] = None
    age: Optional[int] = None
    error: Optional[str] = None


# ── 1. get_patient_profile ────────────────────────────────────────────────────

@router.get(
    "/me",
    response_model=ProfileResponse,
    summary="Get authenticated patient's profile",
    description=(
        "Replicates `get_patient_profile` tool. "
        "Returns the patient's id, user_id, name, dob (YYYY-MM-DD), age (computed), "
        "and email. Patient identity is resolved from the Bearer token — no parameters needed."
    ),
)
async def get_profile(
    current_user: dict = Depends(roles_required(UserRole.PATIENT)),
    db: Session = Depends(get_db),
) -> ProfileResponse:
    patient = _get_patient(db, current_user["user_id"])

    result = get_patient_profile(db, patient.id, patient.user_id)
    if not result:
        raise HTTPException(status_code=404, detail="Could not load patient profile.")

    return ProfileResponse(**result)


# ── 2. update_patient_name ────────────────────────────────────────────────────

@router.patch(
    "/name",
    response_model=UpdateNameResponse,
    summary="Update authenticated patient's display name",
    description=(
        "Replicates `update_patient_name` tool. "
        "Trims whitespace and validates minimum 2 characters. "
        "Returns {success: true, updated_name} on success or "
        "{success: false, error} on failure. "
        "Patient identity is resolved from Bearer token."
    ),
)
async def update_name(
    body: UpdateNameRequest,
    current_user: dict = Depends(roles_required(UserRole.PATIENT)),
    db: Session = Depends(get_db),
) -> UpdateNameResponse:
    patient = _get_patient(db, current_user["user_id"])

    result = update_patient_name(db, patient.id, body.new_name)
    return UpdateNameResponse(**result)


# ── 3. update_patient_dob ─────────────────────────────────────────────────────

@router.patch(
    "/dob",
    response_model=UpdateDobResponse,
    summary="Update authenticated patient's date of birth",
    description=(
        "Replicates `update_patient_dob` tool. "
        "Accepts new_dob in YYYY-MM-DD format. "
        "Validates that the date is in the past. "
        "Returns {success: true, updated_dob, age} on success or "
        "{success: false, error} on failure. "
        "Patient identity is resolved from Bearer token."
    ),
)
async def update_dob(
    body: UpdateDobRequest,
    current_user: dict = Depends(roles_required(UserRole.PATIENT)),
    db: Session = Depends(get_db),
) -> UpdateDobResponse:
    patient = _get_patient(db, current_user["user_id"])

    try:
        new_dob = dt_date.fromisoformat(body.new_dob)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid date format '{body.new_dob}'. Use YYYY-MM-DD."
        )

    result = update_patient_dob(db, patient.id, new_dob)
    return UpdateDobResponse(**result)