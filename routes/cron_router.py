from fastapi import APIRouter, Header, HTTPException, Depends
from sqlalchemy.orm import Session
from datetime import date, timedelta, time
import os
from typing import Dict, Any

from deps import get_db
from models.doctor import Doctor
from models.doctor_slot import DoctorSlot
from models.doctor_availability import DoctorAvailability
from core.enums import SlotStatus
from services.slot_generation_service import generate_slots_for_availability

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
    
    expected_secret = os.getenv("CRON_SECRET")
    if not expected_secret:
        raise HTTPException(status_code=500, detail="CRON_SECRET not configured")
    
    expected_auth = f"Bearer {expected_secret}"
    if authorization != expected_auth:
        raise HTTPException(status_code=401, detail="Invalid authorization token")
    
    return True


@cron_router.get("/daily-maintenance")
async def daily_slot_maintenance(
    db: Session = Depends(get_db),
    authorized: bool = Depends(verify_cron_secret)
) -> Dict[str, Any]:
    """
    Daily maintenance job for slot management.
    
    Tasks:
    1. Delete past FREE slots (cleanup)
    2. Create availability + slots for day 30 (rolling window)
    
    Scheduled: Daily at 00:00 UTC via Vercel Cron or GitHub Actions
    
    Security: Requires CRON_SECRET in Authorization header
    """
    
    try:
        today = date.today()
        day_30 = today + timedelta(days=30)
        
        # ═══════════════════════════════════════
        # STEP 1: Cleanup Past FREE Slots
        # ═══════════════════════════════════════
        deleted_count = db.query(DoctorSlot).filter(
            DoctorSlot.date < today,
            DoctorSlot.status == SlotStatus.FREE
        ).delete(synchronize_session=False)
        
        # ═══════════════════════════════════════
        # STEP 2: Create Day 30 Availability
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
        # STEP 3: Return Statistics
        # ═══════════════════════════════════════
        return {
            "success": True,
            "timestamp": str(today),
            "maintenance": {
                "deleted_past_slots": deleted_count,
                "doctors_processed": doctors_processed,
                "doctors_skipped": skipped_existing,
                "new_slots_created": total_slots_created,
                "target_date": str(day_30)
            },
            "errors": errors if errors else None,
            "message": f"Successfully processed {doctors_processed} doctors"
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