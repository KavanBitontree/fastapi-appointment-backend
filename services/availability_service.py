from sqlalchemy.orm import Session
from fastapi import HTTPException
from models.doctor_availability import DoctorAvailability
from models.doctor_slot import DoctorSlot
from core.enums import SlotStatus
from services.slot_generation_service import generate_slots_for_availability


def create_availability(
    db: Session,
    *,
    doctor,
    payload
) -> DoctorAvailability:
    """
    Create availability and auto-generate slots if available.
    """

    availability = DoctorAvailability(
        doctor_id=doctor.id,
        date=payload.date,
        start_time=payload.start_time,
        end_time=payload.end_time,
        is_available=payload.is_available,
    )

    db.add(availability)
    db.flush()  # get availability.id

    if availability.is_available:
        generate_slots_for_availability(
            db=db,
            doctor=doctor,
            availability=availability,
        )

    return availability


def update_availability(
    db: Session,
    *,
    availability: DoctorAvailability,
    doctor,
    payload
) -> DoctorAvailability:
    """
    Update availability safely:
    - Delete only FREE slots
    - Never touch BOOKED/HELD slots
    - Regenerate if available
    """

    # 1️⃣ Delete FREE slots linked to this availability
    db.query(DoctorSlot).filter(
        DoctorSlot.avail_id == availability.id,
        DoctorSlot.status == SlotStatus.FREE
    ).delete(synchronize_session=False)

    # 2️⃣ Update availability fields
    for field, value in payload.dict(exclude_unset=True).items():
        setattr(availability, field, value)

    db.flush()

    # 3️⃣ Regenerate slots if available
    if availability.is_available:
        generate_slots_for_availability(
            db=db,
            doctor=doctor,
            availability=availability,
        )

    return availability


def block_slot(
    db: Session,
    *,
    slot_id: int,
    doctor_id: int
) -> DoctorSlot:
    """
    Block a specific slot for doctor's break/personal time.
    Only FREE slots can be blocked.
    """
    slot = db.query(DoctorSlot).filter(
        DoctorSlot.id == slot_id,
        DoctorSlot.doctor_id == doctor_id
    ).first()

    if not slot:
        raise HTTPException(status_code=404, detail="Slot not found")

    if slot.status != SlotStatus.FREE:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot block slot with status: {slot.status.value}"
        )

    slot.status = SlotStatus.BLOCKED
    db.flush()
    return slot


def unblock_slot(
    db: Session,
    *,
    slot_id: int,
    doctor_id: int
) -> DoctorSlot:
    """
    Unblock a previously blocked slot, making it FREE again.
    """
    slot = db.query(DoctorSlot).filter(
        DoctorSlot.id == slot_id,
        DoctorSlot.doctor_id == doctor_id
    ).first()

    if not slot:
        raise HTTPException(status_code=404, detail="Slot not found")

    if slot.status != SlotStatus.BLOCKED:
        raise HTTPException(
            status_code=400,
            detail=f"Slot is not blocked, current status: {slot.status.value}"
        )

    slot.status = SlotStatus.FREE
    db.flush()
    return slot


def bulk_block_slots(
    db: Session,
    *,
    slot_ids: list[int],
    doctor_id: int
) -> dict:
    """
    Block multiple slots at once (useful for lunch breaks, meetings).
    Returns summary of blocked slots.
    """
    slots = db.query(DoctorSlot).filter(
        DoctorSlot.id.in_(slot_ids),
        DoctorSlot.doctor_id == doctor_id,
        DoctorSlot.status == SlotStatus.FREE
    ).all()

    if not slots:
        raise HTTPException(
            status_code=404,
            detail="No valid FREE slots found to block"
        )

    blocked_count = 0
    for slot in slots:
        slot.status = SlotStatus.BLOCKED
        blocked_count += 1

    db.flush()

    return {
        "blocked_count": blocked_count,
        "requested_count": len(slot_ids),
        "message": f"Successfully blocked {blocked_count} slots"
    }