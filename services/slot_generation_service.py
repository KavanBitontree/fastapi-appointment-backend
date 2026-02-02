from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from models.doctor_slot import DoctorSlot
from models.doctor import Doctor
from models.doctor_availability import DoctorAvailability
from core.enums import SlotStatus

# IST timezone offset
IST_OFFSET = timedelta(hours=5, minutes=30)


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
    
    IMPORTANT: availability.start_time and availability.end_time are in IST,
    but we need to compare with current UTC time converted to IST.
    """

    # Convert minimum_slot_duration (stored as hours) to minutes
    slot_minutes = int(float(doctor.minimum_slot_duration) * 60)

    start_dt = datetime.combine(availability.date, availability.start_time)
    end_dt = datetime.combine(availability.date, availability.end_time)

    # Get current time in UTC and convert to IST
    now_utc = datetime.now(timezone.utc)
    now_ist = now_utc + IST_OFFSET
    today_ist = now_ist.date()

    # Skip past slots if this availability is for today (in IST)
    if skip_past and availability.date == today_ist:
        # Current time in IST (time component only)
        current_time_ist = now_ist.time()
        
        # If current time has passed the start time, adjust start_dt
        if current_time_ist > availability.start_time:
            # If current time is past end time, no slots to create
            if current_time_ist >= availability.end_time:
                return 0
            
            # Start from current time, rounded up to next slot boundary
            current_dt = datetime.combine(availability.date, current_time_ist)
            
            # Calculate how many slot intervals have passed since start
            minutes_elapsed = (current_dt - start_dt).total_seconds() / 60
            slots_passed = int(minutes_elapsed / slot_minutes)
            
            # Move start_dt to the next available slot after current time
            start_dt = start_dt + timedelta(minutes=(slots_passed + 1) * slot_minutes)

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