from datetime import date, datetime, timedelta, time as dt_time
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Security
from sqlalchemy.orm import Session

from core.security_schemes import bearer_scheme
from deps import get_db
from middlewares.auth import roles_required
from core.enums import UserRole, SlotStatus
from models.doctor import Doctor
from models.doctor_availability import DoctorAvailability
from models.doctor_slot import DoctorSlot


router = APIRouter(
    prefix="/doctor/calendar",
    tags=["Doctor Calendar"],
    dependencies=[Security(bearer_scheme)]
)


def _get_doctor(db: Session, user_id: int) -> Doctor:
    doctor = db.query(Doctor).filter(Doctor.user_id == user_id).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor profile not found")
    return doctor


def _parse_iso_date(value: Any, *, field_name: str) -> date:
    if value is None:
        raise HTTPException(status_code=400, detail=f"Missing field: {field_name}")
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}: expected YYYY-MM-DD string")
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}: expected YYYY-MM-DD")


def _require_present_or_future(d: date, *, field_name: str) -> None:
    if d < date.today():
        raise HTTPException(status_code=400, detail=f"{field_name} cannot be in the past")


def _require_not_before_min_editable(d: date, *, field_name: str) -> None:
    """
    Enforce that doctors only edit slots/days that are still relevant for booking.
    Rule: date must be >= tomorrow (today + 1 day).
    """
    today = date.today()
    min_editable = today + timedelta(days=1)
    if d < min_editable:
        raise HTTPException(
            status_code=400,
            detail=f"{field_name} cannot be earlier than {min_editable.isoformat()}",
        )


def _upsert_day_off(db: Session, *, doctor_id: int, off_date: date) -> dict:
    """
    Mark a date as OFF by setting/creating DoctorAvailability with is_available=False.
    Also blocks any FREE slots on that date (if they already exist).

    IMPORTANT:
    - We do NOT touch BOOKED/HELD slots.
    - We keep start/end times for existing availability.
    - For new availability row, we store a full-day range to satisfy NOT NULL columns.
    """
    # Lock slots for the date first (patient hold/booking also uses row locks on slot rows)
    slots_for_day = (
        db.query(DoctorSlot)
        .filter(
            DoctorSlot.doctor_id == doctor_id,
            DoctorSlot.date == off_date,
        )
        .order_by(DoctorSlot.id)
        .with_for_update()
        .all()
    )

    # Lock availability row (if present) so concurrent availability edits serialize
    availability = (
        db.query(DoctorAvailability)
        .filter(
            DoctorAvailability.doctor_id == doctor_id,
            DoctorAvailability.date == off_date,
        )
        .with_for_update(of=DoctorAvailability)
        .first()
    )

    created = False
    if availability:
        availability.is_available = False
    else:
        # Full-day placeholder window (only used for storage; is_available=False prevents slot generation)
        availability = DoctorAvailability(
            doctor_id=doctor_id,
            date=off_date,
            start_time=dt_time(0, 0),
            end_time=dt_time(23, 59),
            is_available=False,
        )
        db.add(availability)
        created = True

    # Block FREE slots for this day (first-writer-wins; never touch BOOKED/HELD)
    blocked_count = 0
    for slot in slots_for_day:
        if slot.status == SlotStatus.FREE:
            slot.status = SlotStatus.BLOCKED
            blocked_count += 1

    return {
        "date": off_date.isoformat(),
        "availability_created": created,
        "blocked_free_slots": blocked_count,
        "message": "Day marked off successfully",
    }


@router.post("/date-off")
def mark_date_off(
    payload: dict = Body(...),
    current_user: dict = Depends(roles_required(UserRole.DOCTOR)),
    db: Session = Depends(get_db)
):
    doctor = _get_doctor(db, current_user["user_id"])
    off_date = _parse_iso_date(payload.get("date"), field_name="date")
    _require_present_or_future(off_date, field_name="date")
    _require_not_before_min_editable(off_date, field_name="date")
    result = _upsert_day_off(db, doctor_id=doctor.id, off_date=off_date)
    db.commit()
    return result


@router.post("/leave-range")
def take_leave_range(
    payload: dict = Body(...),
    current_user: dict = Depends(roles_required(UserRole.DOCTOR)),
    db: Session = Depends(get_db)
):
    doctor = _get_doctor(db, current_user["user_id"])

    start_date = _parse_iso_date(payload.get("start_date"), field_name="start_date")
    end_date = _parse_iso_date(payload.get("end_date"), field_name="end_date")
    _require_present_or_future(start_date, field_name="start_date")
    _require_not_before_min_editable(start_date, field_name="start_date")
    if end_date < start_date:
        raise HTTPException(status_code=400, detail="end_date must be >= start_date")

    # Guardrail to avoid accidental huge updates
    total_days = (end_date - start_date).days + 1
    if total_days > 60:
        raise HTTPException(status_code=400, detail="Leave range too large (max 60 days)")

    results = []
    day = start_date
    while day <= end_date:
        results.append(_upsert_day_off(db, doctor_id=doctor.id, off_date=day))
        day += timedelta(days=1)

    db.commit()

    return {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "days_marked_off": total_days,
        "details": results,
    }


@router.post("/recurring-sundays-off")
def recurring_sundays_off(
    payload: dict = Body(...),
    current_user: dict = Depends(roles_required(UserRole.DOCTOR)),
    db: Session = Depends(get_db)
):
    doctor = _get_doctor(db, current_user["user_id"])

    start = _parse_iso_date(payload.get("start_date"), field_name="start_date")
    _require_present_or_future(start, field_name="start_date")
    
    # Auto-adjust to min editable date instead of rejecting
    today = date.today()
    min_editable = today + timedelta(days=1)
    if start < min_editable:
        start = min_editable
    
    weeks = payload.get("weeks")
    if not isinstance(weeks, int):
        raise HTTPException(status_code=400, detail="weeks must be an integer")
    if weeks < 1 or weeks > 52:
        raise HTTPException(status_code=400, detail="weeks must be between 1 and 52")

    # Compute Sundays in the next N weeks (inclusive week window)
    end = start + timedelta(weeks=weeks)

    # Find first Sunday on/after start
    # Python weekday(): Monday=0..Sunday=6
    days_until_sunday = (6 - start.weekday()) % 7
    first_sunday = start + timedelta(days=days_until_sunday)

    sundays = []
    d = first_sunday
    while d <= end:
        sundays.append(d)
        d += timedelta(weeks=1)

    results = []
    for sunday in sundays:
        results.append(_upsert_day_off(db, doctor_id=doctor.id, off_date=sunday))

    db.commit()

    return {
        "start_date": start.isoformat(),
        "weeks": weeks,
        "sundays_marked_off": len(sundays),
        "dates": [d.isoformat() for d in sundays],
        "details": results,
    }


