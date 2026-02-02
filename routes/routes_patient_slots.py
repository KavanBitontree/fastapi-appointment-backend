from fastapi import APIRouter, Depends, HTTPException, Query, Security
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime, timedelta, timezone
from core.security_schemes import bearer_scheme
from deps import get_db
from middlewares.auth import roles_required
from core.enums import UserRole, SlotStatus
from models.doctor_slot import DoctorSlot
from models.doctor import Doctor


router = APIRouter(
    prefix="/patient",
    tags=["Patient - Appointments"],
    dependencies=[Security(bearer_scheme)]
)

# ─────────────────────────────────────────────────────────────
# 🔥 INLINE EXPIRED HOLD CLEANUP (Hobby-safe replacement for cron)
# ─────────────────────────────────────────────────────────────
def release_expired_holds_inline(db: Session) -> int:
    now = datetime.now(timezone.utc)

    released = db.query(DoctorSlot).filter(
        DoctorSlot.status == SlotStatus.HELD,
        DoctorSlot.held_expires_at < now
    ).update(
        {
            DoctorSlot.status: SlotStatus.FREE,
            DoctorSlot.held_at: None,
            DoctorSlot.held_by_patient_id: None,
            DoctorSlot.held_expires_at: None,
        },
        synchronize_session=False
    )

    if released:
        db.commit()

    return released


# ─────────────────────────────────────────────────────────────
# VIEW SLOTS (AUTO-CLEAN EXPIRED HOLDS)
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
    # 🔥 Auto release expired holds
    release_expired_holds_inline(db)

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

    return {
        "total": len(slots_data),
        "slots": slots_data,
        "doctor_id": doctor_id,
        "doctor_name": doctor.name
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
    slot = db.query(DoctorSlot).filter(DoctorSlot.id == slot_id).first()
    if not slot:
        raise HTTPException(status_code=404, detail="Slot not found")

    if slot.status != SlotStatus.FREE:
        if slot.status == SlotStatus.HELD and slot.held_by_patient_id == current_user["user_id"]:
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
        raise HTTPException(status_code=409, detail="Slot cannot be held")

    existing_holds = db.query(DoctorSlot).filter(
        DoctorSlot.doctor_id == slot.doctor_id,
        DoctorSlot.date == slot.date,
        DoctorSlot.status == SlotStatus.HELD,
        DoctorSlot.held_by_patient_id == current_user["user_id"]
    ).all()

    for h in existing_holds:
        h.status = SlotStatus.FREE
        h.held_at = None
        h.held_by_patient_id = None
        h.held_expires_at = None

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
# GET SLOTS BY DATE (AUTO-CLEAN INCLUDED)
# ─────────────────────────────────────────────────────────────
@router.get("/slots/by-date")
async def get_slots_by_date(
    doctor_id: int = Query(...),
    date: str = Query(...),
    current_user: dict = Depends(roles_required(UserRole.PATIENT)),
    db: Session = Depends(get_db)
):
    # 🔥 Auto cleanup
    release_expired_holds_inline(db)

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

    return {
        "date": date,
        "slots": slots_data,
        "has_free_slots": has_free_slots,
        "doctor_id": doctor_id,
        "doctor_name": doctor.name
    }
