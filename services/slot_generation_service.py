"""
Enhanced Slot Generation Service with Minimum Booking Buffer

CRITICAL BUSINESS LOGIC:
- Doctor has 24 hours to approve appointment requests
- Slots must be at least 25+ hours away from current time
- This ensures doctor has time to approve before appointment time

Example:
- Current: Monday 10:00 AM
- Minimum bookable: Tuesday 11:01 AM onwards (25+ hours away)
- Patient CANNOT book: Tuesday 09:00 AM (only 23 hours away)
"""

from datetime import datetime, timedelta, timezone, time as dt_time
from sqlalchemy.orm import Session
from models.doctor_slot import DoctorSlot
from models.doctor import Doctor
from models.doctor_availability import DoctorAvailability
from core.enums import SlotStatus
from zoneinfo import ZoneInfo

# IST timezone
IST = ZoneInfo("Asia/Kolkata")

# CRITICAL: Minimum hours required before appointment time
# 24h for doctor approval + 1h buffer
MINIMUM_BOOKING_BUFFER_HOURS = 25


def generate_slots_for_availability(
    db: Session,
    *,
    doctor: Doctor,
    availability: DoctorAvailability,
    skip_past: bool = True,
    enforce_booking_buffer: bool = True
) -> int:
    """
    Generate slots for ONE availability row.
    
    IMPORTANT CHANGES:
    - Skips slots that are less than 25 hours away (24h approval + 1h buffer)
    - Uses IST timezone for date/time calculations
    
    Args:
        db: Database session
        doctor: Doctor model
        availability: DoctorAvailability model
        skip_past: Skip past times (always True)
        enforce_booking_buffer: Enforce 25-hour minimum buffer (default True)
    
    Returns:
        Number of slots created
    """
    
    # Convert minimum_slot_duration (stored as hours) to minutes
    slot_minutes = int(float(doctor.minimum_slot_duration) * 60)

    start_dt = datetime.combine(availability.date, availability.start_time)
    end_dt = datetime.combine(availability.date, availability.end_time)

    # Get current time in IST
    now_utc = datetime.now(timezone.utc)
    now_ist = now_utc.astimezone(IST)
    today_ist = now_ist.date()

    # Calculate minimum bookable datetime (25 hours from now)
    if enforce_booking_buffer:
        min_bookable_datetime_ist = now_ist + timedelta(hours=MINIMUM_BOOKING_BUFFER_HOURS)
        min_bookable_date = min_bookable_datetime_ist.date()
        min_bookable_time = min_bookable_datetime_ist.time()
    else:
        # Fallback to current time
        min_bookable_datetime_ist = now_ist
        min_bookable_date = today_ist
        min_bookable_time = now_ist.time()

    # ──────────────────────────────────────────────────────────
    # CASE 1: Availability date is before minimum bookable date
    # ──────────────────────────────────────────────────────────
    if availability.date < min_bookable_date:
        # Don't create slots - too soon for booking
        return 0

    # ──────────────────────────────────────────────────────────
    # CASE 2: Availability date is exactly the minimum bookable date
    # ──────────────────────────────────────────────────────────
    if availability.date == min_bookable_date:
        # Only create slots that start after min_bookable_time
        if availability.end_time <= min_bookable_time:
            # All slots in this availability are too soon
            return 0
        
        # Adjust start_dt to first valid slot time
        if availability.start_time < min_bookable_time:
            # Calculate slot boundary after min_bookable_time
            current_dt = datetime.combine(availability.date, min_bookable_time)
            
            # Find next slot boundary
            minutes_since_start = (current_dt - start_dt).total_seconds() / 60
            slots_passed = int(minutes_since_start / slot_minutes)
            
            # Move to next slot boundary
            start_dt = start_dt + timedelta(minutes=(slots_passed + 1) * slot_minutes)

    # ──────────────────────────────────────────────────────────
    # CASE 3: Availability date is in the future (safe to create all slots)
    # ──────────────────────────────────────────────────────────
    # No adjustment needed, create all slots

    # Generate slots
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


def calculate_minimum_bookable_date() -> tuple[datetime.date, dt_time]:
    """
    Calculate the minimum date and time that can be booked.
    
    Returns:
        Tuple of (date, time) representing minimum bookable datetime
        
    Example:
        Current: Monday 10:00 AM IST
        Returns: (Tuesday, 11:00:00) - 25 hours later
    """
    now_ist = datetime.now(IST)
    min_bookable_datetime = now_ist + timedelta(hours=MINIMUM_BOOKING_BUFFER_HOURS)
    
    return min_bookable_datetime.date(), min_bookable_datetime.time()


def is_slot_bookable(slot_date: datetime.date, slot_start_time: dt_time) -> bool:
    """
    Check if a slot is bookable based on the 25-hour minimum buffer.
    
    Args:
        slot_date: Date of the slot
        slot_start_time: Start time of the slot
    
    Returns:
        True if slot is bookable, False otherwise
    """
    now_ist = datetime.now(IST)
    slot_datetime = datetime.combine(slot_date, slot_start_time).replace(tzinfo=IST)
    
    hours_until_slot = (slot_datetime - now_ist).total_seconds() / 3600
    
    return hours_until_slot >= MINIMUM_BOOKING_BUFFER_HOURS


def get_bookable_slots_info() -> dict:
    """
    Get information about the current booking window.
    Useful for displaying to patients.
    
    Returns:
        Dictionary with booking window information
    """
    now_ist = datetime.now(IST)
    min_bookable = now_ist + timedelta(hours=MINIMUM_BOOKING_BUFFER_HOURS)
    
    return {
        "current_time_ist": now_ist.strftime("%d %B %Y, %I:%M %p IST"),
        "minimum_booking_buffer_hours": MINIMUM_BOOKING_BUFFER_HOURS,
        "earliest_bookable_datetime": min_bookable.strftime("%d %B %Y, %I:%M %p IST"),
        "earliest_bookable_date": min_bookable.date().isoformat(),
        "earliest_bookable_time": min_bookable.time().isoformat(),
        "reason": f"Slots must be at least {MINIMUM_BOOKING_BUFFER_HOURS} hours away (24h doctor approval + 1h buffer)"
    }