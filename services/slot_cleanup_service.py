"""
Enhanced Cleanup Service with Booking Buffer Enforcement

CRITICAL: Removes FREE slots that are within the 25-hour minimum booking buffer.
This ensures patients can only see/book slots that are at least 25 hours away.
"""

from datetime import datetime, date, timedelta, timezone
from sqlalchemy.orm import Session
from models.doctor_slot import DoctorSlot
from models.appointment import Appointment
from core.enums import SlotStatus, AppointmentStatus
from zoneinfo import ZoneInfo

# IST timezone
IST = ZoneInfo("Asia/Kolkata")

# Configuration
APPOINTMENT_APPROVAL_TIMEOUT_HOURS = 24
MINIMUM_BOOKING_BUFFER_HOURS = 25  # 24h approval + 1h buffer


# ═══════════════════════════════════════════════════════════
# DATA INTEGRITY FUNCTIONS
# ═══════════════════════════════════════════════════════════

def fix_slot_appointment_inconsistencies(db: Session) -> dict:
    """
    Fix data inconsistencies between slots and appointments.
    
    Cases handled:
    1. Slots marked FREE but have active appointments → Mark as BOOKED
    2. Slots marked BOOKED but have no appointments → Mark as FREE
    
    Returns:
        Dictionary with counts of fixes applied
    """
    # Case 1: FREE slots with active appointments
    free_slots_with_appointments = db.query(DoctorSlot).join(Appointment).filter(
        DoctorSlot.status == SlotStatus.FREE,
        Appointment.status.in_([
            AppointmentStatus.REQUESTED,
            AppointmentStatus.APPROVED,
            AppointmentStatus.PAID  # Active appointment statuses
        ])
    ).all()
    
    fixed_free_to_booked = 0
    for slot in free_slots_with_appointments:
        slot.status = SlotStatus.BOOKED
        fixed_free_to_booked += 1
    
    # Case 2: BOOKED slots with no appointments
    booked_slots_without_appointments = db.query(DoctorSlot).outerjoin(Appointment).filter(
        DoctorSlot.status == SlotStatus.BOOKED,
        Appointment.id.is_(None)
    ).all()
    
    fixed_booked_to_free = 0
    for slot in booked_slots_without_appointments:
        slot.status = SlotStatus.FREE
        slot.held_at = None
        slot.held_by_patient_id = None
        slot.held_expires_at = None
        fixed_booked_to_free += 1
    
    if fixed_free_to_booked > 0 or fixed_booked_to_free > 0:
        db.commit()
    
    return {
        "free_to_booked": fixed_free_to_booked,
        "booked_to_free": fixed_booked_to_free,
        "total_fixed": fixed_free_to_booked + fixed_booked_to_free
    }


# ═══════════════════════════════════════════════════════════
# ENHANCED SLOT CLEANUP FUNCTIONS
# ═══════════════════════════════════════════════════════════

def release_expired_holds(db: Session) -> int:
    """
    Release slot holds that have expired (>10 minutes).
    
    Returns:
        Number of slots released
    """
    now_utc = datetime.now(timezone.utc)
    
    released = db.query(DoctorSlot).filter(
        DoctorSlot.status == SlotStatus.HELD,
        DoctorSlot.held_expires_at < now_utc
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


def delete_unbookable_free_slots(db: Session) -> int:
    """
    🔥 CRITICAL: Delete FREE slots that are within the 25-hour minimum booking buffer.
    
    IMPORTANT: Only deletes slots that have NO appointments associated with them.
    Uses subquery to avoid SQLAlchemy join+delete limitation.
    
    Returns:
        Number of slots deleted
    """
    now_ist = datetime.now(IST)
    
    # Calculate minimum bookable datetime (25 hours from now)
    min_bookable_datetime = now_ist + timedelta(hours=MINIMUM_BOOKING_BUFFER_HOURS)
    min_bookable_date = min_bookable_datetime.date()
    min_bookable_time = min_bookable_datetime.time()
    
    # ─────────────────────────────────────────────────────────
    # Find slot IDs that have appointments (to exclude them)
    # ─────────────────────────────────────────────────────────
    slots_with_appointments = db.query(Appointment.slot_id).filter(
        Appointment.slot_id.isnot(None)
    ).distinct().subquery()
    
    deleted_count = 0
    
    # ─────────────────────────────────────────────────────────
    # DELETE 1: All FREE slots on dates before min_bookable_date
    # (but only those WITHOUT appointments)
    # ─────────────────────────────────────────────────────────
    deleted_count += db.query(DoctorSlot).filter(
        DoctorSlot.status == SlotStatus.FREE,
        DoctorSlot.date < min_bookable_date,
        ~DoctorSlot.id.in_(slots_with_appointments)  # NOT IN subquery
    ).delete(synchronize_session=False)
    
    # ─────────────────────────────────────────────────────────
    # DELETE 2: FREE slots on min_bookable_date before min_bookable_time
    # (but only those WITHOUT appointments)
    # ─────────────────────────────────────────────────────────
    deleted_count += db.query(DoctorSlot).filter(
        DoctorSlot.status == SlotStatus.FREE,
        DoctorSlot.date == min_bookable_date,
        DoctorSlot.start_time < min_bookable_time,
        ~DoctorSlot.id.in_(slots_with_appointments)  # NOT IN subquery
    ).delete(synchronize_session=False)
    
    if deleted_count > 0:
        db.commit()
    
    return deleted_count


def delete_past_free_slots_legacy(db: Session) -> int:
    """
    Legacy function - kept for backward compatibility.
    Use delete_unbookable_free_slots() instead.
    """
    return delete_unbookable_free_slots(db)


# ═══════════════════════════════════════════════════════════
# APPOINTMENT CLEANUP FUNCTIONS
# ═══════════════════════════════════════════════════════════

def expire_pending_appointments(db: Session) -> int:
    """
    Auto-expire appointments that are REQUESTED for more than 24 hours.
    
    Actions:
    1. Change appointment status to CANCELLED
    2. Release the associated slot (status = FREE)
    
    Returns:
        Number of appointments expired
    """
    now_utc = datetime.now(timezone.utc)
    cutoff_time = now_utc - timedelta(hours=APPOINTMENT_APPROVAL_TIMEOUT_HOURS)
    
    # Find expired appointments
    expired_appointments = db.query(Appointment).filter(
        Appointment.status == AppointmentStatus.REQUESTED,
        Appointment.created_at < cutoff_time
    ).all()
    
    expired_count = 0
    for appointment in expired_appointments:
        # Cancel the appointment
        appointment.status = AppointmentStatus.CANCELLED
        
        # Release the slot
        slot = appointment.slot
        if slot and slot.status == SlotStatus.BOOKED:
            slot.status = SlotStatus.FREE
            slot.held_at = None
            slot.held_by_patient_id = None
            slot.held_expires_at = None
        
        expired_count += 1
    
    if expired_count:
        db.commit()
    
    return expired_count


# ═══════════════════════════════════════════════════════════
# COMPREHENSIVE CLEANUP FUNCTION
# ═══════════════════════════════════════════════════════════

def run_all_cleanup_tasks(db: Session) -> dict:
    """
    🔥 ENHANCED: Run all cleanup tasks with booking buffer enforcement.
    
    This should be called:
    1. Before displaying slots to patients
    2. Before creating new appointments
    3. Periodically (if using scheduled jobs)
    
    Returns:
        Dictionary with counts of cleaned items
    """
    results = {
        "inconsistencies_fixed": fix_slot_appointment_inconsistencies(db),
        "expired_holds_released": release_expired_holds(db),
        "unbookable_slots_deleted": delete_unbookable_free_slots(db),
        "pending_appointments_expired": expire_pending_appointments(db),
    }
    
    return results


# ═══════════════════════════════════════════════════════════
# UTILITY FUNCTIONS
# ═══════════════════════════════════════════════════════════

def get_cleanup_statistics(db: Session) -> dict:
    """
    Get statistics about items that need cleanup.
    Useful for monitoring and debugging.
    
    Returns:
        Dictionary with counts of items needing cleanup
    """
    now_utc = datetime.now(timezone.utc)
    now_ist = datetime.now(IST)
    
    # Calculate minimum bookable datetime
    min_bookable_datetime = now_ist + timedelta(hours=MINIMUM_BOOKING_BUFFER_HOURS)
    min_bookable_date = min_bookable_datetime.date()
    min_bookable_time = min_bookable_datetime.time()
    
    # Subquery for slots with appointments
    slots_with_appointments = db.query(Appointment.slot_id).filter(
        Appointment.slot_id.isnot(None)
    ).distinct().subquery()
    
    # Count expired holds
    expired_holds = db.query(DoctorSlot).filter(
        DoctorSlot.status == SlotStatus.HELD,
        DoctorSlot.held_expires_at < now_utc
    ).count()
    
    # Count unbookable FREE slots (within 25-hour buffer) WITHOUT appointments
    unbookable_before_date = db.query(DoctorSlot).filter(
        DoctorSlot.status == SlotStatus.FREE,
        DoctorSlot.date < min_bookable_date,
        ~DoctorSlot.id.in_(slots_with_appointments)
    ).count()
    
    unbookable_same_date = db.query(DoctorSlot).filter(
        DoctorSlot.status == SlotStatus.FREE,
        DoctorSlot.date == min_bookable_date,
        DoctorSlot.start_time < min_bookable_time,
        ~DoctorSlot.id.in_(slots_with_appointments)
    ).count()
    
    total_unbookable = unbookable_before_date + unbookable_same_date
    
    # Count pending appointments that should expire
    cutoff_time = now_utc - timedelta(hours=APPOINTMENT_APPROVAL_TIMEOUT_HOURS)
    expired_appointments = db.query(Appointment).filter(
        Appointment.status == AppointmentStatus.REQUESTED,
        Appointment.created_at < cutoff_time
    ).count()
    
    return {
        "expired_holds_count": expired_holds,
        "unbookable_slots_count": total_unbookable,
        "unbookable_slots_before_date": unbookable_before_date,
        "unbookable_slots_within_buffer": unbookable_same_date,
        "pending_appointments_to_expire": expired_appointments,
        "minimum_booking_buffer_hours": MINIMUM_BOOKING_BUFFER_HOURS,
        "earliest_bookable_date": min_bookable_date.isoformat(),
        "earliest_bookable_time": str(min_bookable_time),
        "checked_at_utc": now_utc.isoformat(),
        "checked_at_ist": now_ist.isoformat()
    }


def get_booking_window_info() -> dict:
    """
    Get information about the current booking window.
    Useful for displaying to patients and doctors.
    
    Returns:
        Dictionary with booking window information
    """
    now_ist = datetime.now(IST)
    min_bookable = now_ist + timedelta(hours=MINIMUM_BOOKING_BUFFER_HOURS)
    
    return {
        "current_time_ist": now_ist.strftime("%d %B %Y, %I:%M %p IST"),
        "minimum_booking_buffer_hours": MINIMUM_BOOKING_BUFFER_HOURS,
        "approval_timeout_hours": APPOINTMENT_APPROVAL_TIMEOUT_HOURS,
        "earliest_bookable_datetime": min_bookable.strftime("%d %B %Y, %I:%M %p IST"),
        "earliest_bookable_date": min_bookable.date().isoformat(),
        "message": f"Patients can book slots starting from {min_bookable.strftime('%I:%M %p on %d %B')}"
    }


def validate_slot_consistency(db: Session) -> dict:
    """
    Check for inconsistencies in slot-appointment relationships.
    Useful for debugging and data validation.
    
    Returns:
        Dictionary with counts of inconsistencies
    """
    # Slots marked BOOKED but no active appointment
    orphaned_booked_slots = db.query(DoctorSlot).outerjoin(Appointment).filter(
        DoctorSlot.status == SlotStatus.BOOKED,
        Appointment.id.is_(None)
    ).count()
    
    # Appointments with status REQUESTED/APPROVED/PAID but slot is FREE
    mismatched_appointments = db.query(Appointment).join(DoctorSlot).filter(
        Appointment.status.in_([
            AppointmentStatus.REQUESTED,
            AppointmentStatus.APPROVED,
            AppointmentStatus.PAID  # Active appointment statuses
        ]),
        DoctorSlot.status == SlotStatus.FREE
    ).count()
    
    return {
        "orphaned_booked_slots": orphaned_booked_slots,
        "mismatched_appointments": mismatched_appointments,
        "has_issues": orphaned_booked_slots > 0 or mismatched_appointments > 0
    }


# ═══════════════════════════════════════════════════════════
# EXPORTS
# ═══════════════════════════════════════════════════════════

__all__ = [
    # Main cleanup functions (use these in your routes)
    "release_expired_holds",
    "delete_unbookable_free_slots",
    "expire_pending_appointments",
    "run_all_cleanup_tasks",
    "fix_slot_appointment_inconsistencies",
    
    # Utility functions
    "get_cleanup_statistics",
    "get_booking_window_info",
    "validate_slot_consistency",
    
    # Legacy (for backward compatibility)
    "delete_past_free_slots_legacy",
]