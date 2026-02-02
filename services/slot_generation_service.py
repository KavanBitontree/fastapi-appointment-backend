from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from models.doctor_slot import DoctorSlot
from models.doctor import Doctor
from models.doctor_availability import DoctorAvailability
from core.enums import SlotStatus


def generate_slots_for_availability(
    db: Session,
    *,
    doctor: Doctor,
    availability: DoctorAvailability,
    skip_past: bool = True
) -> int:
    """
    Generate slots for ONE availability row.
    Returns number of slots created.
    """

    slot_minutes = int(float(doctor.minimum_slot_duration) * 60)

    start_dt = datetime.combine(availability.date, availability.start_time)
    end_dt = datetime.combine(availability.date, availability.end_time)

    now = datetime.utcnow()

    # Skip past slots for today
    if skip_past and start_dt.date() == now.date():
        start_dt = max(start_dt, now)

    slots_created = 0
    slots = []

    while start_dt + timedelta(minutes=slot_minutes) <= end_dt:
        slots.append(
            DoctorSlot(
                doctor_id=doctor.id,
                avail_id=availability.id,
                date=availability.date,
                start_time=start_dt.time(),
                end_time=(start_dt + timedelta(minutes=slot_minutes)).time(),
                status=SlotStatus.FREE,
            )
        )
        start_dt += timedelta(minutes=slot_minutes)
        slots_created += 1

    if slots:
        db.bulk_save_objects(slots)

    return slots_created
