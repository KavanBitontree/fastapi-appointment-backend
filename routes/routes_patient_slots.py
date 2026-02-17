from fastapi import APIRouter, Depends, HTTPException, Query, Security
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from core.security_schemes import bearer_scheme
from deps import get_db
from middlewares.auth import roles_required
from core.enums import UserRole, SlotStatus
from models.doctor_slot import DoctorSlot
from models.doctor import Doctor

# Import the enhanced cleanup service
from services.slot_cleanup_service import (
    release_expired_holds,
    delete_unbookable_free_slots,
    get_booking_window_info,
    fix_slot_appointment_inconsistencies
)

# Define IST timezone
IST = ZoneInfo("Asia/Kolkata")

router = APIRouter(
    prefix="/patient",
    tags=["Patient - Appointments"],
    dependencies=[Security(bearer_scheme)]
)


# ─────────────────────────────────────────────────────────────
# 🔥 VIEW BOOKING WINDOW INFO (NEW ENDPOINT)
# ─────────────────────────────────────────────────────────────
@router.get("/booking-window")
async def get_booking_window(
    current_user: dict = Depends(roles_required(UserRole.PATIENT))
):
    """
    Get information about the current booking window.
    
    Returns:
        - Current time
        - Earliest bookable datetime (25 hours from now)
        - Explanation of the 25-hour buffer rule
    """
    return get_booking_window_info()


# ─────────────────────────────────────────────────────────────
# 🔥 VIEW SLOTS (WITH 25-HOUR BUFFER CLEANUP)
# ─────────────────────────────────────────────────────────────
@router.get("/view/slots")
async def get_doctor_slots_for_booking(
    doctor_id: int = Query(..., description="Doctor ID"),
    start_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    status: Optional[str] = Query(None, description="FREE, BOOKED, BLOCKED, HELD"),
    current_user: dict = Depends(roles_required(UserRole.PATIENT)),
    db: Session = Depends(get_db)
):
    """
    Get doctor's slots for booking.
    
    CRITICAL CHANGES:
    - Auto-releases expired holds (10 min)
    - Auto-deletes unbookable FREE slots (within 25-hour buffer)
    - Only shows slots that can actually be booked
    
    25-Hour Buffer Rule:
    - Patients can only book slots ≥ 25 hours away from current time
    - This ensures doctor has 24 hours to approve before appointment time
    """

    fix_slot_appointment_inconsistencies(db)
    
    # 🔥 AUTO-CLEANUP: Release expired holds
    release_expired_holds(db)
    
    # 🔥 AUTO-CLEANUP: Delete unbookable FREE slots (< 25 hours away)
    delete_unbookable_free_slots(db)

    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")

    query = db.query(DoctorSlot).filter(DoctorSlot.doctor_id == doctor_id)

    if start_date:
        query = query.filter(
            DoctorSlot.date >= datetime.strptime(start_date, "%Y-%m-%d").date()
        )
    if end_date:
        query = query.filter(
            DoctorSlot.date <= datetime.strptime(end_date, "%Y-%m-%d").date()
        )

    if status:
        query = query.filter(DoctorSlot.status == status.upper())
    else:
        # Show FREE, BOOKED, BLOCKED, and HELD (if held by current user)
        query = query.filter(
            (DoctorSlot.status.in_(
                [SlotStatus.FREE, SlotStatus.BOOKED, SlotStatus.BLOCKED]
            )) |
            (
                (DoctorSlot.status == SlotStatus.HELD) &
                (DoctorSlot.held_by_patient_id == current_user["user_id"])
            )
        )

    slots = query.order_by(
        DoctorSlot.date,
        DoctorSlot.start_time
    ).all()

    slots_data = []
    for slot in slots:
        data = {
            "id": slot.id,
            "doctor_id": slot.doctor_id,
            "date": slot.date.isoformat(),
            "start_time": str(slot.start_time),
            "end_time": str(slot.end_time),
            "status": slot.status.value,
            "held_by_current_user": (
                slot.status == SlotStatus.HELD and
                slot.held_by_patient_id == current_user["user_id"]
            )
        }

        if data["held_by_current_user"]:
            data["held_until"] = slot.held_expires_at.isoformat()

        slots_data.append(data)

    # Add booking window info to response
    booking_window = get_booking_window_info()

    return {
        "total": len(slots_data),
        "slots": slots_data,
        "doctor_id": doctor_id,
        "doctor_name": doctor.name,
        "booking_window": booking_window
    }


# ─────────────────────────────────────────────────────────────
# HOLD SLOT (UNCHANGED LOGIC)
# ─────────────────────────────────────────────────────────────
@router.post("/slots/{slot_id}/hold")
async def hold_slot(
    slot_id: int,
    current_user: dict = Depends(roles_required(UserRole.PATIENT)),
    db: Session = Depends(get_db)
):
    """
    Hold a slot for 10 minutes while patient fills appointment form.
    
    Note: Slot must be ≥ 25 hours away (enforced by cleanup).
    If slot is within 25-hour buffer, it won't exist in DB.
    """
    
    # 🔒 ROW LOCK
    slot = (
        db.query(DoctorSlot)
        .filter(DoctorSlot.id == slot_id)
        .with_for_update()
        .first()
    )

    if not slot:
        raise HTTPException(status_code=404, detail="Slot not found")

    if slot.status != SlotStatus.FREE:
        if (
            slot.status == SlotStatus.HELD and
            slot.held_by_patient_id == current_user["user_id"]
        ):
            # Refresh the hold
            now = datetime.now(timezone.utc)
            expiry = now + timedelta(minutes=10)
            slot.held_at = now
            slot.held_expires_at = expiry
            db.commit()
            return {
                "slot_id": slot.id,
                "status": "HELD",
                "held_until": expiry.isoformat(),
                "time_remaining_seconds": 600,
                "message": "Hold refreshed"
            }

        raise HTTPException(status_code=409, detail="Slot already taken")

    # Release other holds by this user on same date
    db.query(DoctorSlot).filter(
        DoctorSlot.doctor_id == slot.doctor_id,
        DoctorSlot.date == slot.date,
        DoctorSlot.status == SlotStatus.HELD,
        DoctorSlot.held_by_patient_id == current_user["user_id"]
    ).update(
        {
            DoctorSlot.status: SlotStatus.FREE,
            DoctorSlot.held_at: None,
            DoctorSlot.held_by_patient_id: None,
            DoctorSlot.held_expires_at: None,
        },
        synchronize_session=False
    )

    now = datetime.now(timezone.utc)
    expiry = now + timedelta(minutes=10)

    slot.status = SlotStatus.HELD
    slot.held_at = now
    slot.held_by_patient_id = current_user["user_id"]
    slot.held_expires_at = expiry

    db.commit()
    db.refresh(slot)

    return {
        "slot_id": slot.id,
        "status": "HELD",
        "held_until": expiry.isoformat(),
        "time_remaining_seconds": 600,
        "message": "Slot held successfully"
    }


# ─────────────────────────────────────────────────────────────
# RELEASE SLOT (UNCHANGED)
# ─────────────────────────────────────────────────────────────
@router.post("/slots/{slot_id}/release")
async def release_slot(
    slot_id: int,
    current_user: dict = Depends(roles_required(UserRole.PATIENT)),
    db: Session = Depends(get_db)
):
    """Release a held slot"""
    slot = db.query(DoctorSlot).filter(DoctorSlot.id == slot_id).first()
    if not slot:
        raise HTTPException(status_code=404, detail="Slot not found")

    if slot.status != SlotStatus.HELD:
        raise HTTPException(status_code=400, detail="Slot is not held")

    if slot.held_by_patient_id != current_user["user_id"]:
        raise HTTPException(status_code=403, detail="Forbidden")

    slot.status = SlotStatus.FREE
    slot.held_at = None
    slot.held_by_patient_id = None
    slot.held_expires_at = None

    db.commit()

    return {
        "slot_id": slot.id,
        "status": "FREE",
        "message": "Slot released successfully"
    }


# ─────────────────────────────────────────────────────────────
# GET SLOTS BY DATE (WITH 25-HOUR BUFFER CLEANUP)
# ─────────────────────────────────────────────────────────────
@router.get("/slots/by-date")
async def get_slots_by_date(
    doctor_id: int = Query(...),
    date: str = Query(...),
    current_user: dict = Depends(roles_required(UserRole.PATIENT)),
    db: Session = Depends(get_db)
):
    """
    Get slots for a specific date.
    
    CRITICAL: Auto-cleanup runs first to remove unbookable slots.
    """
    
    # 🔥 AUTO-CLEANUP
    release_expired_holds(db)
    delete_unbookable_free_slots(db)

    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")

    try:
        date_obj = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format")

    slots = db.query(DoctorSlot).filter(
        DoctorSlot.doctor_id == doctor_id,
        DoctorSlot.date == date_obj
    ).order_by(DoctorSlot.start_time).all()

    slots_data = []
    has_free_slots = False

    for slot in slots:
        if slot.status == SlotStatus.FREE:
            has_free_slots = True

        data = {
            "id": slot.id,
            "doctor_id": slot.doctor_id,
            "date": slot.date.isoformat(),
            "start_time": str(slot.start_time),
            "end_time": str(slot.end_time),
            "status": slot.status.value,
            "held_by_current_user": (
                slot.status == SlotStatus.HELD and
                slot.held_by_patient_id == current_user["user_id"]
            )
        }

        if data["held_by_current_user"]:
            data["held_until"] = slot.held_expires_at.isoformat()

        slots_data.append(data)

    # Add info about why some dates might have no slots
    booking_window = get_booking_window_info()

    return {
        "date": date,
        "slots": slots_data,
        "has_free_slots": has_free_slots,
        "doctor_id": doctor_id,
        "doctor_name": doctor.name,
        "booking_window": booking_window
    }


# ─────────────────────────────────────────────────────────────
# 🤖 CHATBOT: Check if patient can book on a specific date
# ─────────────────────────────────────────────────────────────
@router.get("/bot/check-availability")
async def bot_check_date_availability(
    date: str = Query(..., description="Date to check (YYYY-MM-DD)"),
    current_user: dict = Depends(roles_required(UserRole.PATIENT)),
    db: Session = Depends(get_db)
):
    """
    🤖 CHATBOT ENDPOINT: Check if patient can book an appointment on a specific date.
    
    This endpoint checks the "one appointment per day" constraint BEFORE showing slots.
    
    Returns:
    - can_book: Boolean indicating if patient can book on this date
    - reason: Explanation if booking is not allowed
    - existing_appointment: Details of existing appointment (if any)
    
    Use this BEFORE calling /bot/available-slots to avoid showing slots
    that the patient cannot book anyway.
    """
    from models.patient import Patient
    from models.appointment import Appointment
    from core.enums import AppointmentStatus
    
    # Get patient
    patient = db.query(Patient).filter(
        Patient.user_id == current_user["user_id"]
    ).first()
    
    if not patient:
        raise HTTPException(status_code=404, detail="Patient profile not found")
    
    # Parse date
    try:
        date_obj = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    
    # Check if date is in the past
    today = datetime.now(IST).date()
    if date_obj < today:
        return {
            "can_book": False,
            "date": date,
            "reason": "Cannot book appointments in the past",
            "existing_appointment": None
        }
    
    # Check if patient already has an appointment on this date
    existing = db.query(Appointment).join(DoctorSlot).filter(
        Appointment.patient_id == patient.id,
        DoctorSlot.date == date_obj,
        Appointment.status.in_([
            AppointmentStatus.REQUESTED,
            AppointmentStatus.APPROVED,
            AppointmentStatus.PAID
        ])
    ).first()
    
    if existing:
        slot = existing.slot
        doctor = existing.doctor
        
        return {
            "can_book": False,
            "date": date,
            "reason": "You already have an appointment on this date",
            "existing_appointment": {
                "id": existing.id,
                "status": existing.status.value,
                "doctor_name": doctor.name,
                "doctor_specialization": doctor.speciality,
                "slot_time": f"{slot.start_time} - {slot.end_time}",
                "created_at": existing.created_at.isoformat()
            }
        }
    
    # Patient can book on this date
    return {
        "can_book": True,
        "date": date,
        "reason": None,
        "existing_appointment": None,
        "message": "You can book an appointment on this date"
    }


# ─────────────────────────────────────────────────────────────
# 🤖 CHATBOT: Get available slots for a date (with validation)
# ─────────────────────────────────────────────────────────────
@router.get("/bot/available-slots")
async def bot_get_available_slots(
    doctor_id: int = Query(..., description="Doctor ID"),
    date: str = Query(..., description="Date (YYYY-MM-DD)"),
    current_user: dict = Depends(roles_required(UserRole.PATIENT)),
    db: Session = Depends(get_db)
):
    """
    🤖 CHATBOT ENDPOINT: Get available slots for a specific doctor and date.
    
    This endpoint:
    1. Checks if patient already has an appointment on this date
    2. Returns FREE slots only if patient can book
    3. Auto-cleans up expired holds and unbookable slots
    
    Recommended flow:
    1. Call /bot/check-availability first
    2. If can_book=true, call this endpoint
    3. Show slots to user
    4. Call /appointments/bot/request to book
    """
    from models.patient import Patient
    from models.appointment import Appointment
    from core.enums import AppointmentStatus
    
    # 🔥 AUTO-CLEANUP
    release_expired_holds(db)
    delete_unbookable_free_slots(db)
    
    # Get patient
    patient = db.query(Patient).filter(
        Patient.user_id == current_user["user_id"]
    ).first()
    
    if not patient:
        raise HTTPException(status_code=404, detail="Patient profile not found")
    
    # Verify doctor exists
    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")
    
    # Parse date
    try:
        date_obj = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    
    # ✅ CHECK: Patient doesn't have appointment on this date
    existing = db.query(Appointment).join(DoctorSlot).filter(
        Appointment.patient_id == patient.id,
        DoctorSlot.date == date_obj,
        Appointment.status.in_([
            AppointmentStatus.REQUESTED,
            AppointmentStatus.APPROVED,
            AppointmentStatus.PAID
        ])
    ).first()
    
    if existing:
        slot = existing.slot
        existing_doctor = existing.doctor
        
        raise HTTPException(
            status_code=400,
            detail={
                "error": "ONE_APPOINTMENT_PER_DAY",
                "message": f"You already have an appointment on {date}",
                "existing_appointment": {
                    "id": existing.id,
                    "status": existing.status.value,
                    "doctor_name": existing_doctor.name,
                    "slot_time": f"{slot.start_time} - {slot.end_time}"
                }
            }
        )
    
    # Get FREE slots for this date
    slots = db.query(DoctorSlot).filter(
        DoctorSlot.doctor_id == doctor_id,
        DoctorSlot.date == date_obj,
        DoctorSlot.status == SlotStatus.FREE
    ).order_by(DoctorSlot.start_time).all()
    
    slots_data = []
    for slot in slots:
        slots_data.append({
            "id": slot.id,
            "date": slot.date.isoformat(),
            "start_time": str(slot.start_time),
            "end_time": str(slot.end_time),
            "status": slot.status.value
        })
    
    # Add booking window info
    booking_window = get_booking_window_info()
    
    return {
        "date": date,
        "doctor_id": doctor_id,
        "doctor_name": doctor.name,
        "doctor_specialization": doctor.speciality,
        "opd_fees": doctor.opd_fees,
        "total_free_slots": len(slots_data),
        "slots": slots_data,
        "booking_window": booking_window,
        "message": f"Found {len(slots_data)} available slots" if slots_data else "No available slots for this date"
    }