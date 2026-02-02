from fastapi import APIRouter, Depends, HTTPException, Query, Security
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime, timedelta, timezone, date as date_type
from core.security_schemes import bearer_scheme
from deps import get_db
from middlewares.auth import roles_required
from core.enums import UserRole
from models.doctor_slot import DoctorSlot
from models.doctor import Doctor

router = APIRouter(
    prefix="/patient",
    tags=["Patient - Appointments"],
    dependencies=[Security(bearer_scheme)]
)


@router.get("/view/slots")
async def get_doctor_slots_for_booking(
    doctor_id: int = Query(..., description="Doctor ID to get slots for"),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    status: Optional[str] = Query(None, description="Slot status filter (FREE, BOOKED, BLOCKED, HELD)"),
    current_user: dict = Depends(roles_required(UserRole.PATIENT)),
    db: Session = Depends(get_db)
):
    """
    Get available slots for a specific doctor.
    Used by patients to view and book appointments.
    """
    # Verify doctor exists
    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")

    # Build query
    query = db.query(DoctorSlot).filter(DoctorSlot.doctor_id == doctor_id)

    # Apply date filters - convert string to date object
    if start_date:
        start_date_obj = datetime.strptime(start_date, "%Y-%m-%d").date()
        query = query.filter(DoctorSlot.date >= start_date_obj)
    if end_date:
        end_date_obj = datetime.strptime(end_date, "%Y-%m-%d").date()
        query = query.filter(DoctorSlot.date <= end_date_obj)

    # Apply status filter - if not specified, exclude HELD slots held by others
    if status:
        query = query.filter(DoctorSlot.status == status.upper())
    else:
        # Show FREE, BOOKED, BLOCKED, and HELD slots held by current user
        query = query.filter(
            (DoctorSlot.status.in_(["FREE", "BOOKED", "BLOCKED"])) |
            ((DoctorSlot.status == "HELD") &
             (DoctorSlot.held_by_patient_id == current_user["user_id"]))
        )

    # Get slots ordered by date and time
    slots = query.order_by(DoctorSlot.date, DoctorSlot.start_time).all()

    # Add held_by_current_user flag to slots
    slots_data = []
    for slot in slots:
        slot_dict = {
            "id": slot.id,
            "doctor_id": slot.doctor_id,
            "date": slot.date.isoformat(),  # Convert to string for JSON
            "start_time": str(slot.start_time),
            "end_time": str(slot.end_time),
            "status": slot.status.value if hasattr(slot.status, 'value') else slot.status,
            "held_by_current_user": (
                slot.status == "HELD" and
                slot.held_by_patient_id == current_user["user_id"]
            )
        }

        if slot.status == "HELD" and slot.held_by_patient_id == current_user["user_id"]:
            slot_dict["held_until"] = slot.held_expires_at.isoformat()

        slots_data.append(slot_dict)

    return {
        "total": len(slots_data),
        "slots": slots_data,
        "doctor_id": doctor_id,
        "doctor_name": doctor.name
    }


@router.post("/slots/{slot_id}/hold")
async def hold_slot(
    slot_id: int,
    current_user: dict = Depends(roles_required(UserRole.PATIENT)),
    db: Session = Depends(get_db)
):
    """
    Temporarily hold a slot for booking.
    Slot will be reserved for 10 minutes.
    
    FIXED: Use timezone-aware datetime to match database column definition
    """
    # Get the slot
    slot = db.query(DoctorSlot).filter(DoctorSlot.id == slot_id).first()

    if not slot:
        raise HTTPException(status_code=404, detail="Slot not found")

    # Check if slot is FREE
    if slot.status != "FREE":
        # If already held by this user, just refresh the timer
        if slot.status == "HELD" and slot.held_by_patient_id == current_user["user_id"]:
            # Refresh the hold - FIXED: Use timezone-aware datetime
            now = datetime.now(timezone.utc)
            expiry = now + timedelta(minutes=10)
            slot.held_expires_at = expiry
            slot.held_at = now  # Also update held_at
            db.commit()

            return {
                "slot_id": slot.id,
                "status": "HELD",
                "held_until": expiry.isoformat(),
                "time_remaining_seconds": 600,
                "message": "Hold refreshed"
            }
        else:
            raise HTTPException(
                status_code=409,
                detail=f"Slot is {slot.status.lower() if hasattr(slot.status, 'lower') else slot.status} and cannot be held"
            )

    # Check if patient already has a held slot for this doctor on this date
    # Release any existing holds for this patient on the same date
    # FIXED: Proper date comparison
    existing_holds = db.query(DoctorSlot).filter(
        DoctorSlot.doctor_id == slot.doctor_id,
        DoctorSlot.date == slot.date,  # This compares Date objects directly
        DoctorSlot.status == "HELD",
        DoctorSlot.held_by_patient_id == current_user["user_id"]
    ).all()

    for existing_hold in existing_holds:
        existing_hold.status = "FREE"
        existing_hold.held_at = None
        existing_hold.held_by_patient_id = None
        existing_hold.held_expires_at = None

    # Hold the slot - FIXED: Use timezone-aware datetime
    now = datetime.now(timezone.utc)
    expiry = now + timedelta(minutes=10)

    slot.status = "HELD"
    slot.held_at = now
    slot.held_by_patient_id = current_user["user_id"]
    slot.held_expires_at = expiry

    db.commit()
    db.refresh(slot)  # Refresh to ensure we have the latest data

    return {
        "slot_id": slot.id,
        "status": "HELD",
        "held_until": expiry.isoformat(),
        "time_remaining_seconds": 600,
        "date": slot.date.isoformat(),  # Return date for verification
        "message": "Slot held successfully"
    }


@router.post("/slots/{slot_id}/release")
async def release_slot(
    slot_id: int,
    current_user: dict = Depends(roles_required(UserRole.PATIENT)),
    db: Session = Depends(get_db)
):
    """
    Release a held slot, making it available again.
    Only the patient who held the slot can release it.
    """
    slot = db.query(DoctorSlot).filter(DoctorSlot.id == slot_id).first()

    if not slot:
        raise HTTPException(status_code=404, detail="Slot not found")

    # Check if slot is held by this patient
    if slot.status != "HELD":
        raise HTTPException(status_code=400, detail="Slot is not held")

    if slot.held_by_patient_id != current_user["user_id"]:
        raise HTTPException(
            status_code=403,
            detail="You can only release slots held by you"
        )

    # Release the slot
    slot.status = "FREE"
    slot.held_at = None
    slot.held_by_patient_id = None
    slot.held_expires_at = None

    db.commit()

    return {
        "slot_id": slot.id,
        "status": "FREE",
        "message": "Slot released successfully"
    }


@router.get("/slots/by-date")
async def get_slots_by_date(
    doctor_id: int = Query(..., description="Doctor ID"),
    date: str = Query(..., description="Date (YYYY-MM-DD)"),
    current_user: dict = Depends(roles_required(UserRole.PATIENT)),
    db: Session = Depends(get_db)
):
    """
    Get fresh slot data for a specific date.
    Used to refresh slots when user selects a date.
    
    FIXED: Proper date string to date object conversion
    """
    # Verify doctor exists
    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")

    # FIXED: Convert string to date object for comparison
    try:
        date_obj = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

    # Get slots for the specified date
    slots = db.query(DoctorSlot).filter(
        DoctorSlot.doctor_id == doctor_id,
        DoctorSlot.date == date_obj  # Use date object
    ).order_by(DoctorSlot.start_time).all()

    # Format slots with held_by_current_user flag
    slots_data = []
    has_free_slots = False

    for slot in slots:
        slot_dict = {
            "id": slot.id,
            "doctor_id": slot.doctor_id,
            "date": slot.date.isoformat(),  # Convert to string for JSON
            "start_time": str(slot.start_time),
            "end_time": str(slot.end_time),
            "status": slot.status.value if hasattr(slot.status, 'value') else slot.status,
            "held_by_current_user": (
                slot.status == "HELD" and
                slot.held_by_patient_id == current_user["user_id"]
            )
        }

        if slot.status == "FREE":
            has_free_slots = True

        if slot.status == "HELD" and slot.held_by_patient_id == current_user["user_id"]:
            slot_dict["held_until"] = slot.held_expires_at.isoformat()

        slots_data.append(slot_dict)

    return {
        "date": date,
        "slots": slots_data,
        "has_free_slots": has_free_slots,
        "doctor_id": doctor_id,
        "doctor_name": doctor.name
    }