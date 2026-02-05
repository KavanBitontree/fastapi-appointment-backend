from fastapi import APIRouter, Depends, HTTPException, Security
from sqlalchemy.orm import Session
from typing import List
from core.security_schemes import bearer_scheme
from deps import get_db
from middlewares.auth import roles_required
from core.enums import UserRole
from models.doctor import Doctor
from models.doctor_availability import DoctorAvailability
from models.doctor_slot import DoctorSlot
from schemas.doctor_availability import (
    DoctorAvailabilityCreate,
    DoctorAvailabilityUpdate,
    BlockSlotRequest,
    BulkBlockSlotsRequest
)
from services.availability_service import (
    create_availability,
    update_availability,
    block_slot,
    unblock_slot,
    bulk_block_slots
)

router = APIRouter(
    prefix="/doctor/availability",
    tags=["Doctor Availability"],
    dependencies=[Security(bearer_scheme)]
)


@router.post("/")
def create_doctor_availability(
    payload: DoctorAvailabilityCreate,
    current_user: dict = Depends(roles_required(UserRole.DOCTOR)),
    db: Session = Depends(get_db)
):
    """
    Create new availability for a specific date.
    Automatically generates slots if is_available=True.
    """
    doctor = db.query(Doctor).filter(
        Doctor.user_id == current_user["user_id"]
    ).first()

    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor profile not found")

    result = create_availability(db=db, doctor=doctor, payload=payload)
    db.commit()
    db.refresh(result)  # Refresh to get updated data
    return result


@router.patch("/{availability_id}")
def update_doctor_availability(
    availability_id: int,
    payload: DoctorAvailabilityUpdate,
    current_user: dict = Depends(roles_required(UserRole.DOCTOR)),
    db: Session = Depends(get_db)
):
    """
    Update existing availability.
    Safely deletes only FREE slots and regenerates based on new times.
    """
    availability = db.query(DoctorAvailability).join(Doctor).filter(
        DoctorAvailability.id == availability_id,
        Doctor.user_id == current_user["user_id"]
    ).first()

    if not availability:
        raise HTTPException(status_code=404, detail="Availability not found")

    result = update_availability(
        db=db,
        availability=availability,
        doctor=availability.doctor,
        payload=payload
    )
    db.commit()
    db.refresh(result)
    return result


@router.post("/slots/{slot_id}/block")
def block_doctor_slot(
    slot_id: int,
    current_user: dict = Depends(roles_required(UserRole.DOCTOR)),
    db: Session = Depends(get_db)
):
    """
    Block a specific slot (for breaks, personal time, etc.).
    Only FREE slots can be blocked.
    """
    doctor = db.query(Doctor).filter(
        Doctor.user_id == current_user["user_id"]
    ).first()

    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor profile not found")

    result = block_slot(db=db, slot_id=slot_id, doctor_id=doctor.id)
    db.commit()
    db.refresh(result)  # Refresh to get the updated slot
    return result


@router.post("/slots/{slot_id}/unblock")
def unblock_doctor_slot(
    slot_id: int,
    current_user: dict = Depends(roles_required(UserRole.DOCTOR)),
    db: Session = Depends(get_db)
):
    """
    Unblock a previously blocked slot, making it available again.
    """
    doctor = db.query(Doctor).filter(
        Doctor.user_id == current_user["user_id"]
    ).first()

    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor profile not found")

    result = unblock_slot(db=db, slot_id=slot_id, doctor_id=doctor.id)
    db.commit()
    db.refresh(result)
    return result


@router.post("/slots/bulk-block")
def bulk_block_doctor_slots(
    payload: BulkBlockSlotsRequest,
    current_user: dict = Depends(roles_required(UserRole.DOCTOR)),
    db: Session = Depends(get_db)
):
    """
    Block multiple slots at once.
    Useful for lunch breaks, meetings, or extended unavailability.
    """
    doctor = db.query(Doctor).filter(
        Doctor.user_id == current_user["user_id"]
    ).first()

    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor profile not found")

    result = bulk_block_slots(
        db=db,
        slot_ids=payload.slot_ids,
        doctor_id=doctor.id
    )
    db.commit()
    # Refresh all affected slots if result is a list
    if isinstance(result, list):
        for slot in result:
            db.refresh(slot)
    return result


@router.get("/slots")
def get_doctor_slots(
    start_date: str = None,
    end_date: str = None,
    status: str = None,
    current_user: dict = Depends(roles_required(UserRole.DOCTOR)),
    db: Session = Depends(get_db)
):
    """
    Get doctor's slots with optional filters.
    Useful for viewing blocked slots, free slots, etc.
    """
    doctor = db.query(Doctor).filter(
        Doctor.user_id == current_user["user_id"]
    ).first()

    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor profile not found")

    query = db.query(DoctorSlot).filter(DoctorSlot.doctor_id == doctor.id)

    if start_date:
        query = query.filter(DoctorSlot.date >= start_date)
    if end_date:
        query = query.filter(DoctorSlot.date <= end_date)
    if status:
        query = query.filter(DoctorSlot.status == status)

    slots = query.order_by(DoctorSlot.date, DoctorSlot.start_time).all()

    return {
        "total": len(slots),
        "slots": slots
    }