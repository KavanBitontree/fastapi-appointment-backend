"""
routes/bot_appointments.py — FIXED
All routes use JWT auth. No patient_id query param anywhere.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Security
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import date as dt_date

from core.security_schemes import bearer_scheme
from deps import get_db
from middlewares.auth import roles_required
from core.enums import UserRole
from models.patient import Patient

from langGraph_service.tools.appointment_tools import (
    check_patient_can_book_on_date,
    get_free_slots_for_doctor_on_date,
    request_appointment_via_bot,
    get_patient_appointments,
)
from langGraph_service.tools.doctor_tools import search_doctors_by_name


router = APIRouter(
    prefix="/bot/appointments",
    tags=["n8n Bot — Appointments"],
    dependencies=[Security(bearer_scheme)],
)


def _get_patient(db: Session, user_id: int) -> Patient:
    patient = db.query(Patient).filter(Patient.user_id == user_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient profile not found for this user.")
    return patient


# ── Schemas ───────────────────────────────────────────────────────────────────

class CheckDateRequest(BaseModel):
    date: str = Field(..., description="Target date in YYYY-MM-DD format.", examples=["2026-03-15"])

class ExistingAppointment(BaseModel):
    id: int
    status: str
    doctor_name: str
    speciality: str
    slot_time: str

class CheckDateResponse(BaseModel):
    can_book: bool
    reason: Optional[str] = None
    existing: Optional[ExistingAppointment] = None

class SlotItem(BaseModel):
    id: int
    date: str
    start_time: str
    end_time: str
    status: str

class FreeSlotsResponse(BaseModel):
    doctor_found: bool
    doctor_id: Optional[int] = None
    doctor_name: Optional[str] = None
    speciality: Optional[str] = None
    opd_fees: Optional[float] = None
    address: Optional[str] = None
    slots: List[SlotItem] = []
    total: int = 0

class BookSlotRequest(BaseModel):
    slot_id: int = Field(..., description="Slot ID obtained from /free-slots endpoint.")

class BookSlotResponse(BaseModel):
    success: bool
    appointment_id: Optional[int] = None
    status: Optional[str] = None
    doctor_name: Optional[str] = None
    slot_date: Optional[str] = None
    slot_time: Optional[str] = None
    approval_deadline: Optional[str] = None
    error: Optional[str] = None
    existing: Optional[ExistingAppointment] = None

class AppointmentItem(BaseModel):
    id: int
    status: str
    doctor_name: str
    speciality: str
    slot_date: str
    slot_time: str
    opd_fees: float
    created_at: Optional[str] = None

class DoctorSearchItem(BaseModel):
    id: int
    name: str
    speciality: str
    opd_fees: float
    address: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None


# ── 1. check_can_book_on_date ─────────────────────────────────────────────────

@router.post(
    "/check-date",
    response_model=CheckDateResponse,
    summary="Check if patient can book on a date",
)
async def check_date(
    body: CheckDateRequest,
    current_user: dict = Depends(roles_required(UserRole.PATIENT)),
    db: Session = Depends(get_db),
) -> CheckDateResponse:
    patient = _get_patient(db, current_user["user_id"])

    try:
        target_date = dt_date.fromisoformat(body.date)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid date format '{body.date}'. Use YYYY-MM-DD.")

    result = check_patient_can_book_on_date(db, patient.id, target_date)
    return CheckDateResponse(**result)


# ── 2. get_free_slots_for_doctor_on_date ─────────────────────────────────────

@router.get(
    "/free-slots",
    response_model=FreeSlotsResponse,
    summary="Get free slots for a doctor on a date",
)
async def free_slots(
    doctor_id: int = Query(..., description="Doctor ID from search endpoint."),
    date: str = Query(..., description="Date in YYYY-MM-DD format."),
    current_user: dict = Depends(roles_required(UserRole.PATIENT)),
    db: Session = Depends(get_db),
) -> FreeSlotsResponse:
    _get_patient(db, current_user["user_id"])

    try:
        target_date = dt_date.fromisoformat(date)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid date format '{date}'. Use YYYY-MM-DD.")

    result = get_free_slots_for_doctor_on_date(db, doctor_id, target_date)
    return FreeSlotsResponse(**result)


# ── 3. book_slot ──────────────────────────────────────────────────────────────

@router.post(
    "/book",
    response_model=BookSlotResponse,
    summary="Book a slot for the authenticated patient",
)
async def book_slot(
    body: BookSlotRequest,
    current_user: dict = Depends(roles_required(UserRole.PATIENT)),
    db: Session = Depends(get_db),
) -> BookSlotResponse:
    patient = _get_patient(db, current_user["user_id"])
    result = await request_appointment_via_bot(db, patient.id, body.slot_id)
    return BookSlotResponse(**result)


# ── 4. my_appointments ────────────────────────────────────────────────────────

@router.get(
    "/my-appointments",
    response_model=List[AppointmentItem],
    summary="Get authenticated patient's appointments",
)
async def my_appointments(
    status_filter: Optional[str] = Query(default=None, description="REQUESTED | APPROVED | PAID | CANCELLED"),
    limit: int = Query(default=10, ge=1, le=50),
    current_user: dict = Depends(roles_required(UserRole.PATIENT)),
    db: Session = Depends(get_db),
) -> List[AppointmentItem]:
    patient = _get_patient(db, current_user["user_id"])
    results = get_patient_appointments(db, patient.id, status_filter, limit=limit)
    return [AppointmentItem(**a) for a in results]


# ── 5. search_doctor ──────────────────────────────────────────────────────────

@router.get(
    "/search-doctor",
    response_model=List[DoctorSearchItem],
    summary="Search doctors by name (appointment agent helper)",
)
async def search_doctor(
    name: str = Query(..., description="Partial or full doctor name, no 'Dr.' prefix."),
    current_user: dict = Depends(roles_required(UserRole.PATIENT)),
    db: Session = Depends(get_db),
) -> List[DoctorSearchItem]:
    _get_patient(db, current_user["user_id"])
    results = search_doctors_by_name(db, name, limit=5)
    return [DoctorSearchItem(**d) for d in results]