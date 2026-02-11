from fastapi import APIRouter, Header, HTTPException, Depends , Security
from sqlalchemy.orm import Session
from datetime import date, timedelta, time, datetime, timezone
from typing import Dict, Any
from core.security_schemes import bearer_scheme
from core.cron_security import verify_cron_auth

from deps import get_db
from models.doctor import Doctor
from models.doctor_slot import DoctorSlot
from models.doctor_availability import DoctorAvailability
from models.appointment import Appointment
from core.enums import SlotStatus, AppointmentStatus
from services.slot_generation_service import generate_slots_for_availability
from core.config import settings
from services.slot_cleanup_service import (
    fix_slot_appointment_inconsistencies,
    delete_unbookable_free_slots
)

# Create router for cron jobs
cron_router = APIRouter(prefix="/api/cron", tags=["Cron Jobs"])


def verify_cron_secret(authorization: str = Header(None)) -> bool:
    """
    Verify that the request is coming from Vercel Cron or authorized service.

    Security:
    - Set CRON_SECRET in Vercel environment variables
    - Include 'Authorization: Bearer YOUR_CRON_SECRET' in cron config
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization header")

    expected_secret = settings.CRON_SECRET
    if not expected_secret:
        raise HTTPException(status_code=500, detail="CRON_SECRET not configured")

    expected_auth = f"Bearer {expected_secret}"
    if authorization != expected_auth:
        raise HTTPException(status_code=401, detail="Invalid authorization token")

    return True


@cron_router.get("/daily-maintenance", dependencies=[Security(verify_cron_auth)])
async def daily_slot_maintenance(
    db: Session = Depends(get_db),
    authorized: bool = Depends(verify_cron_secret)
) -> Dict[str, Any]:
    """
    Daily maintenance job for slot and appointment management.

    Tasks:
    1. Fix slot-appointment inconsistencies (data integrity)
    2. Expire appointments that passed 24-hour approval window (doctor didn't respond)
    3. Expire appointments that passed 15-minute payment window (patient didn't pay)
    4. Delete unbookable FREE slots (< 25 hours buffer, no appointments)
    5. Create availability + slots for day 30 (rolling window)

    Scheduled: Daily at 00:00 UTC via Vercel Cron or GitHub Actions

    Security: Requires CRON_SECRET in Authorization header
    """

    try:
        today = date.today()
        day_30 = today + timedelta(days=30)
        now_utc = datetime.now(timezone.utc)

        # ═══════════════════════════════════════
        # STEP 0: Fix Data Inconsistencies
        # ═══════════════════════════════════════
        inconsistencies_fixed = fix_slot_appointment_inconsistencies(db)

        # ═══════════════════════════════════════
        # STEP 1: Expire Pending Approval Appointments (24-hour window)
        # ═══════════════════════════════════════
        expired_approval_appointments = db.query(Appointment).filter(
            Appointment.status == AppointmentStatus.REQUESTED,
            Appointment.approval_expires_at.isnot(None),
            Appointment.approval_expires_at < now_utc
        ).all()
        
        expired_approval_count = 0
        for appointment in expired_approval_appointments:
            # Release the slot
            slot = appointment.slot
            if slot and slot.status == SlotStatus.BOOKED:
                slot.status = SlotStatus.FREE
                slot.held_at = None
                slot.held_by_patient_id = None
                slot.held_expires_at = None
            
            # Cancel the appointment
            appointment.status = AppointmentStatus.CANCELLED
            expired_approval_count += 1

        # ═══════════════════════════════════════
        # STEP 2: Expire Unpaid Appointments (15-minute payment window)
        # ═══════════════════════════════════════
        expired_payment_appointments = db.query(Appointment).filter(
            Appointment.status == AppointmentStatus.APPROVED,
            Appointment.payment_expires_at.isnot(None),
            Appointment.payment_expires_at < now_utc
        ).all()
        
        expired_payment_count = 0
        for appointment in expired_payment_appointments:
            # Release the slot
            slot = appointment.slot
            if slot and slot.status == SlotStatus.BOOKED:
                slot.status = SlotStatus.FREE
                slot.held_at = None
                slot.held_by_patient_id = None
                slot.held_expires_at = None
            
            # Cancel the appointment
            appointment.status = AppointmentStatus.CANCELLED
            expired_payment_count += 1

        # Commit appointment expirations
        if expired_approval_count > 0 or expired_payment_count > 0:
            db.commit()

        # ═══════════════════════════════════════
        # STEP 3: Delete Unbookable FREE Slots
        # ═══════════════════════════════════════
        deleted_count = delete_unbookable_free_slots(db)

        # ═══════════════════════════════════════
        # STEP 4: Create Day 30 Availability
        # ═══════════════════════════════════════
        doctors = db.query(Doctor).all()
        total_slots_created = 0
        doctors_processed = 0
        skipped_existing = 0
        errors = []

        for doctor in doctors:
            try:
                # Check if availability already exists for day 30
                existing_availability = db.query(DoctorAvailability).filter(
                    DoctorAvailability.doctor_id == doctor.id,
                    DoctorAvailability.date == day_30
                ).first()

                if existing_availability:
                    skipped_existing += 1
                    continue

                # Get the doctor's most recent availability pattern
                recent_availability = db.query(DoctorAvailability).filter(
                    DoctorAvailability.doctor_id == doctor.id,
                    DoctorAvailability.date >= today,
                    DoctorAvailability.is_available == True
                ).order_by(DoctorAvailability.date.desc()).first()

                # Use recent pattern or default clinic hours
                clinic_start = recent_availability.start_time if recent_availability else time(9, 0)
                clinic_end = recent_availability.end_time if recent_availability else time(17, 0)

                # Create availability for day 30
                new_availability = DoctorAvailability(
                    doctor_id=doctor.id,
                    date=day_30,
                    start_time=clinic_start,
                    end_time=clinic_end,
                    is_available=True
                )

                db.add(new_availability)
                db.flush()

                # Generate slots for the new availability
                slots_created = generate_slots_for_availability(
                    db=db,
                    doctor=doctor,
                    availability=new_availability,
                    skip_past=False  # Day 30 is always in future
                )

                total_slots_created += slots_created
                doctors_processed += 1

            except Exception as e:
                errors.append({
                    "doctor_id": doctor.id,
                    "doctor_name": doctor.name,
                    "error": str(e)
                })
                continue

        db.commit()

        # ═══════════════════════════════════════
        # STEP 5: Return Statistics
        # ═══════════════════════════════════════
        return {
            "success": True,
            "timestamp": str(today),
            "maintenance": {
                "data_integrity": inconsistencies_fixed,
                "expired_approval_appointments": expired_approval_count,
                "expired_payment_appointments": expired_payment_count,
                "deleted_unbookable_slots": deleted_count,
                "doctors_processed": doctors_processed,
                "doctors_skipped": skipped_existing,
                "new_slots_created": total_slots_created,
                "target_date": str(day_30)
            },
            "errors": errors if errors else None,
            "message": f"Successfully processed {doctors_processed} doctors. Fixed {inconsistencies_fixed.get('total_fixed', 0)} inconsistencies. Expired {expired_approval_count} approval and {expired_payment_count} payment appointments. Deleted {deleted_count} unbookable slots."
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Daily maintenance failed: {str(e)}"
        )

@cron_router.get("/health")
async def cron_health_check(
    authorized: bool = Depends(verify_cron_secret)
) -> Dict[str, str]:
    """
    Health check endpoint for cron service.
    Useful for monitoring and testing.
    """
    return {
        "status": "healthy",
        "service": "cron",
        "message": "Cron service is operational"
    }


@cron_router.post("/manual-trigger")
async def manual_maintenance_trigger(
    db: Session = Depends(get_db),
    authorized: bool = Depends(verify_cron_secret)
) -> Dict[str, Any]:
    """
    Manually trigger the daily maintenance job.
    Useful for testing or emergency runs.

    Security: Requires CRON_SECRET in Authorization header
    """
    return await daily_slot_maintenance(db=db, authorized=authorized)


@cron_router.get("/statistics")
async def get_cron_statistics(
    db: Session = Depends(get_db),
    authorized: bool = Depends(verify_cron_secret)
) -> Dict[str, Any]:
    """
    Get statistics about slots and holds for monitoring.
    """
    from sqlalchemy import func

    try:
        now = datetime.now()
        today = date.today()

        # Count slots by status
        slot_counts = db.query(
            DoctorSlot.status,
            func.count(DoctorSlot.id).label('count')
        ).group_by(DoctorSlot.status).all()

        status_breakdown = {status.value: count for status, count in slot_counts}

        # Count expired holds (should be 0 if job is working)
        expired_holds = db.query(func.count(DoctorSlot.id)).filter(
            DoctorSlot.status == SlotStatus.HELD,
            DoctorSlot.held_expires_at < now
        ).scalar()

        # Count future slots
        future_slots = db.query(func.count(DoctorSlot.id)).filter(
            DoctorSlot.date >= today
        ).scalar()

        # Count past slots that should be cleaned
        past_free_slots = db.query(func.count(DoctorSlot.id)).filter(
            DoctorSlot.date < today,
            DoctorSlot.status == SlotStatus.FREE
        ).scalar()

        return {
            "success": True,
            "timestamp": now.isoformat(),
            "statistics": {
                "status_breakdown": status_breakdown,
                "expired_holds": expired_holds,
                "future_slots": future_slots,
                "past_free_slots_pending_cleanup": past_free_slots
            },
            "health": {
                "expired_holds_ok": expired_holds == 0,
                "cleanup_needed": past_free_slots > 0
            }
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get statistics: {str(e)}"
        )