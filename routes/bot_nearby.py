"""
routes/bot_nearby.py
====================
FastAPI routes that expose the LangGraph nearby doctor tools as REST endpoints
for n8n HTTP Request tool nodes.

Tools replicated (exact logic from langGraph_service/tools/doctor_tools.py
accessed via nearby_tools_agentic.py):
  1. GET /bot/nearby/doctors    ← find_nearby_doctors (Haversine distance)
  2. GET /bot/nearby/specialities ← get_all_specialities (shared helper)

All routes: PATIENT role only.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Security
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import Optional, List

from core.security_schemes import bearer_scheme
from deps import get_db
from middlewares.auth import roles_required
from core.enums import UserRole
from models.patient import Patient

# ── Tool implementations ──────────────────────────────────────────────────────
from langGraph_service.tools.doctor_tools import (
    find_nearby_doctors,
    get_all_specialities,
)


router = APIRouter(
    prefix="/bot/nearby",
    tags=["n8n Bot — Nearby Doctors"],
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

class NearbyDoctorItem(BaseModel):
    """
    Extends the base doctor dict with distance_km added by find_nearby_doctors().
    Matches the exact keys returned by _doctor_to_dict() + distance_km.
    """
    id: int
    name: str
    speciality: str
    opd_fees: float
    address: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    distance_km: float = Field(..., description="Straight-line distance from patient in km (Haversine).")


class SpecialitiesResponse(BaseModel):
    specialities: List[str]


# ── 1. find_nearby_doctors ────────────────────────────────────────────────────

@router.get(
    "/doctors",
    response_model=List[NearbyDoctorItem],
    summary="Find doctors near patient's GPS location",
    description=(
        "Replicates `find_nearby_doctors` tool. "
        "Uses the Haversine formula to compute straight-line distance between "
        "the patient's GPS coordinates and each doctor's stored lat/lon. "
        "Doctors with NULL coordinates are excluded. "
        "Results are sorted by distance_km ascending. "
        "If `speciality` is provided, applies case-insensitive partial match before distance filter. "
        "The n8n agent expands search radius (10 → 20 → 50 km) if no results are found."
    ),
)
async def nearby_doctors(
    patient_lat: float = Query(
        ...,
        description="Patient's latitude from browser Geolocation API.",
        examples=[28.6139],
    ),
    patient_lon: float = Query(
        ...,
        description="Patient's longitude from browser Geolocation API.",
        examples=[77.2090],
    ),
    max_distance_km: float = Query(
        default=10.0,
        ge=0.1,
        le=500.0,
        description="Search radius in km. Agent retries with 20 then 50 if no results.",
    ),
    speciality: Optional[str] = Query(
        default=None,
        description="Optional speciality filter, e.g. 'Cardiologist'. Case-insensitive partial match.",
    ),
    limit: int = Query(
        default=10,
        ge=1,
        le=20,
        description="Max results to return.",
    ),
    current_user: dict = Depends(roles_required(UserRole.PATIENT)),
    db: Session = Depends(get_db),
) -> List[NearbyDoctorItem]:
    _verify_patient(db, current_user["user_id"])

    results = find_nearby_doctors(
        db=db,
        patient_lat=patient_lat,
        patient_lon=patient_lon,
        max_distance_km=max_distance_km,
        speciality=speciality,
        limit=limit,
    )
    return [NearbyDoctorItem(**d) for d in results]


# ── 2. get_all_specialities ───────────────────────────────────────────────────

@router.get(
    "/specialities",
    response_model=SpecialitiesResponse,
    summary="List all specialities (nearby agent helper)",
    description=(
        "Replicates `list_all_specialities` tool used inside the nearby agent. "
        "Returns all distinct speciality strings ordered alphabetically. "
        "Used when the patient is unsure of the exact speciality name."
    ),
)
async def list_specialities(
    current_user: dict = Depends(roles_required(UserRole.PATIENT)),
    db: Session = Depends(get_db),
) -> SpecialitiesResponse:
    _verify_patient(db, current_user["user_id"])
    specialities = get_all_specialities(db)
    return SpecialitiesResponse(specialities=specialities)