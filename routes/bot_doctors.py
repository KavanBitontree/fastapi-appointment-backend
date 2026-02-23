"""
routes/bot_doctors.py
=====================
FastAPI routes that expose the LangGraph doctor search tools as REST endpoints
for n8n HTTP Request tool nodes.

Tools replicated (exact logic from langGraph_service/tools/doctor_tools.py):
  1. GET /bot/doctors/search                 ← search_doctors_by_name
  2. GET /bot/doctors/by-speciality          ← search_doctors_by_speciality
  3. GET /bot/doctors/specialities           ← get_all_specialities
  4. GET /bot/doctors/                       ← get_all_doctors  (paginated)
  5. GET /bot/doctors/{doctor_id}            ← get_doctor_by_id

All routes: PATIENT role only.
"""

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Security
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List

from core.security_schemes import bearer_scheme
from deps import get_db
from middlewares.auth import roles_required
from core.enums import UserRole
from models.patient import Patient

# ── Tool implementations ──────────────────────────────────────────────────────
from langGraph_service.tools.doctor_tools import (
    search_doctors_by_name,
    search_doctors_by_speciality,
    get_all_specialities,
    get_all_doctors,
    get_doctor_by_id,
)


router = APIRouter(
    prefix="/bot/doctors",
    tags=["n8n Bot — Doctors"],
    dependencies=[Security(bearer_scheme)],
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _verify_patient(db: Session, user_id: int) -> Patient:
    """Verify caller is a patient. Raises 404 if patient profile is missing."""
    patient = db.query(Patient).filter(Patient.user_id == user_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient profile not found for this user.")
    return patient


# ── Response schemas ──────────────────────────────────────────────────────────

class DoctorItem(BaseModel):
    id: int
    name: str
    speciality: str
    opd_fees: float
    address: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class DoctorListResponse(BaseModel):
    total: int
    doctors: List[DoctorItem]


class SpecialitiesResponse(BaseModel):
    specialities: List[str]


# ── 1. search_doctors_by_name ─────────────────────────────────────────────────

@router.get(
    "/search",
    response_model=List[DoctorItem],
    summary="Search doctors by name",
    description=(
        "Replicates `search_doctor_by_name` tool. "
        "Case-insensitive partial match on doctor name. "
        "Pass name WITHOUT 'Dr.' prefix. "
        "Returns up to `limit` results (default 5, max 20)."
    ),
)
async def search_by_name(
    name: str = Query(..., description="Partial or full doctor name without 'Dr.' prefix."),
    limit: int = Query(default=5, ge=1, le=20, description="Max results to return."),
    current_user: dict = Depends(roles_required(UserRole.PATIENT)),
    db: Session = Depends(get_db),
) -> List[DoctorItem]:
    _verify_patient(db, current_user["user_id"])
    results = search_doctors_by_name(db, name, limit=limit)
    return [DoctorItem(**d) for d in results]


# ── 2. search_doctors_by_speciality ──────────────────────────────────────────

@router.get(
    "/by-speciality",
    response_model=List[DoctorItem],
    summary="Search doctors by medical speciality",
    description=(
        "Replicates `search_doctor_by_speciality` tool. "
        "Case-insensitive partial match on speciality field. "
        "Common mappings the n8n agent applies before calling this: "
        "'heart' → Cardiologist, 'skin' → Dermatologist, "
        "'child' → Paediatrician, 'bone' → Orthopaedic, "
        "'eye' → Ophthalmologist, 'teeth' → Dentist, "
        "'mental health' → Psychiatrist. "
        "Returns up to `limit` results (default 10, max 20)."
    ),
)
async def search_by_speciality(
    speciality: str = Query(..., description="Speciality keyword, e.g. 'Cardiologist', 'Dermatologist'."),
    limit: int = Query(default=10, ge=1, le=20, description="Max results to return."),
    current_user: dict = Depends(roles_required(UserRole.PATIENT)),
    db: Session = Depends(get_db),
) -> List[DoctorItem]:
    _verify_patient(db, current_user["user_id"])
    results = search_doctors_by_speciality(db, speciality, limit=limit)
    return [DoctorItem(**d) for d in results]


# ── 3. get_all_specialities ───────────────────────────────────────────────────

@router.get(
    "/specialities",
    response_model=SpecialitiesResponse,
    summary="List all available medical specialities",
    description=(
        "Replicates `list_all_specialities` tool. "
        "Returns all distinct speciality strings from the doctors table, "
        "ordered alphabetically. Used by the agent when the patient is unsure "
        "what type of doctor they need."
    ),
)
async def list_specialities(
    current_user: dict = Depends(roles_required(UserRole.PATIENT)),
    db: Session = Depends(get_db),
) -> SpecialitiesResponse:
    _verify_patient(db, current_user["user_id"])
    specialities = get_all_specialities(db)
    return SpecialitiesResponse(specialities=specialities)


# ── 4. get_all_doctors ────────────────────────────────────────────────────────

@router.get(
    "/",
    response_model=DoctorListResponse,
    summary="List all doctors (paginated)",
    description=(
        "Replicates `list_all_doctors` tool. "
        "Returns a paginated list of all doctors ordered by name. "
        "Used for general browsing when no specific filter is given. "
        "limit is capped at 20 to match the tool's cap."
    ),
)
async def list_all(
    limit: int = Query(default=10, ge=1, le=20, description="Page size (max 20)."),
    skip: int = Query(default=0, ge=0, description="Number of records to skip."),
    current_user: dict = Depends(roles_required(UserRole.PATIENT)),
    db: Session = Depends(get_db),
) -> DoctorListResponse:
    _verify_patient(db, current_user["user_id"])
    result = get_all_doctors(db, limit=limit, skip=skip)
    return DoctorListResponse(
        total=result["total"],
        doctors=[DoctorItem(**d) for d in result["doctors"]],
    )


# ── 5. get_doctor_by_id ───────────────────────────────────────────────────────

@router.get(
    "/{doctor_id}",
    response_model=DoctorItem,
    summary="Get full doctor details by ID",
    description=(
        "Replicates `get_doctor_by_id` tool. "
        "Returns full doctor record including latitude and longitude. "
        "Returns 404 if doctor does not exist."
    ),
)
async def get_by_id(
    doctor_id: int = Path(..., description="Doctor's primary key ID."),
    current_user: dict = Depends(roles_required(UserRole.PATIENT)),
    db: Session = Depends(get_db),
) -> DoctorItem:
    _verify_patient(db, current_user["user_id"])
    result = get_doctor_by_id(db, doctor_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"No doctor found with ID {doctor_id}.")
    return DoctorItem(**result)