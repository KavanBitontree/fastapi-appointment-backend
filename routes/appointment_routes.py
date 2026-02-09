from fastapi import APIRouter, Depends, HTTPException, Security, UploadFile, File, Request, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo
from jose import jwt, JWTError

from core.security_schemes import bearer_scheme
from core.config import settings
from deps import get_db
from middlewares.auth import roles_required, get_current_user
from core.enums import UserRole, AppointmentStatus, SlotStatus
from models.appointment import Appointment
from models.doctor_slot import DoctorSlot
from models.doctor import Doctor
from models.patient import Patient
from models.user import User
from schemas.appointment_schemas import AppointmentCreateRequest
from services.smtp_mail_service import EmailService

# IST timezone
IST = ZoneInfo("Asia/Kolkata")

# ⏰ PRODUCTION STANDARD: 24 hours for doctor approval
APPOINTMENT_APPROVAL_TIMEOUT_HOURS = 24

# ⏰ NEW: 15 minutes for patient payment after approval
PAYMENT_TIMEOUT_MINUTES = 15

router = APIRouter(
    prefix="/appointments",
    tags=["Appointments"]
)


# ─────────────────────────────────────────────────────────────
# 🔐 HELPER: Token-based authentication (for email links)
# ─────────────────────────────────────────────────────────────
async def get_user_from_token_or_bearer(
    request: Request,
    token: Optional[str] = Query(None),
    db: Session = Depends(get_db)
) -> dict:
    """
    Authenticate user either via:
    1. Bearer token in Authorization header (normal flow)
    2. Token in query parameter (from email links)
    """
    # Try query param token first (from email links)
    if token:
        try:
            payload = jwt.decode(
                token,
                settings.JWT_SECRET_KEY,
                algorithms=[settings.JWT_ALGORITHM],
            )
            user_id = payload.get("user_id")
            role = payload.get("role")
            
            if not user_id or not role:
                raise HTTPException(status_code=401, detail="Invalid token payload")
            
            # Verify user exists and is active
            user = db.query(User).filter(
                User.id == user_id,
                User.is_active == True
            ).first()
            
            if not user:
                raise HTTPException(status_code=401, detail="User account is inactive or deleted")
            
            return {
                "user_id": user_id,
                "role": role,
                "device_id": payload.get("device_id", 0)
            }
        except JWTError:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
    
    # Fall back to Bearer token authentication
    return await get_current_user(request, db)


# ─────────────────────────────────────────────────────────────
# 🔥 AUTO-EXPIRE REQUESTED APPOINTMENTS (Doctor didn't respond)
# ─────────────────────────────────────────────────────────────
def expire_pending_approval_appointments_inline(db: Session) -> int:
    """
    Auto-expire appointments that are REQUESTED and approval_expires_at has passed.
    This means doctor didn't respond within 24 hours.
    Release the slot and cancel the appointment.
    """
    now_utc = datetime.now(timezone.utc)
    
    # Find expired appointments where doctor didn't respond
    expired_appointments = db.query(Appointment).filter(
        Appointment.status == AppointmentStatus.REQUESTED,
        Appointment.approval_expires_at.isnot(None),
        Appointment.approval_expires_at < now_utc
    ).all()
    
    expired_count = 0
    for appointment in expired_appointments:
        # Release the slot
        slot = appointment.slot
        if slot and slot.status == SlotStatus.BOOKED:
            slot.status = SlotStatus.FREE
            slot.held_at = None
            slot.held_by_patient_id = None
            slot.held_expires_at = None
        
        # Cancel the appointment
        appointment.status = AppointmentStatus.CANCELLED
        expired_count += 1
    
    if expired_count:
        db.commit()
    
    return expired_count


# ─────────────────────────────────────────────────────────────
# 🔥 AUTO-EXPIRE APPROVED APPOINTMENTS (Patient didn't pay)
# ─────────────────────────────────────────────────────────────
def expire_unpaid_appointments_inline(db: Session) -> int:
    """
    Auto-expire appointments that are APPROVED but payment_expires_at has passed.
    This means patient didn't pay within 15 minutes.
    Release the slot and cancel the appointment.
    """
    now_utc = datetime.now(timezone.utc)
    
    # Find expired approved appointments where patient didn't pay
    expired_appointments = db.query(Appointment).filter(
        Appointment.status == AppointmentStatus.APPROVED,
        Appointment.payment_expires_at.isnot(None),
        Appointment.payment_expires_at < now_utc
    ).all()
    
    expired_count = 0
    for appointment in expired_appointments:
        # Release the slot
        slot = appointment.slot
        if slot and slot.status == SlotStatus.BOOKED:
            slot.status = SlotStatus.FREE
            slot.held_at = None
            slot.held_by_patient_id = None
            slot.held_expires_at = None
        
        # Cancel the appointment
        appointment.status = AppointmentStatus.CANCELLED
        expired_count += 1
    
    if expired_count:
        db.commit()
    
    return expired_count


# ─────────────────────────────────────────────────────────────
# ✅ CHECK: One appointment per day per patient
# ─────────────────────────────────────────────────────────────
def validate_one_appointment_per_day(
    db: Session,
    patient_id: int,
    appointment_date: datetime.date
) -> None:
    """
    Ensure patient doesn't have another appointment on the same day.
    Checks all appointments except CANCELLED and REJECTED.
    """
    existing = db.query(Appointment).join(DoctorSlot).filter(
        Appointment.patient_id == patient_id,
        DoctorSlot.date == appointment_date,
        Appointment.status.in_([
            AppointmentStatus.REQUESTED,
            AppointmentStatus.APPROVED,
            AppointmentStatus.PAID
        ])
    ).first()
    
    if existing:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "ONE_APPOINTMENT_PER_DAY",
                "message": f"You already have an appointment on {appointment_date}",
                "existing_appointment_id": existing.id,
                "existing_status": existing.status.value
            }
        )


# ─────────────────────────────────────────────────────────────
# 📝 CREATE APPOINTMENT (Enhanced with validations)
# ─────────────────────────────────────────────────────────────
@router.post("/request", dependencies=[Security(bearer_scheme)])
async def request_appointment(
    slot_id: int,
    report: Optional[UploadFile] = File(None),
    current_user: dict = Depends(roles_required(UserRole.PATIENT)),
    db: Session = Depends(get_db)
):
    """
    Request an appointment (patient side).
    
    Validations:
    1. Slot must be HELD by current patient
    2. Patient can only book ONE appointment per day
    3. Creates appointment with REQUESTED status
    4. Sets approval_expires_at = now + 24 hours (doctor has 24 hours to respond)
    """
    
    # 🔥 Auto-expire old pending appointments
    expire_pending_approval_appointments_inline(db)
    expire_unpaid_appointments_inline(db)
    
    # Get patient
    patient = db.query(Patient).filter(
        Patient.user_id == current_user["user_id"]
    ).first()
    
    if not patient:
        raise HTTPException(status_code=404, detail="Patient profile not found")
    
    # 🔒 Row lock the slot
    slot = (
        db.query(DoctorSlot)
        .filter(DoctorSlot.id == slot_id)
        .with_for_update()
        .first()
    )
    
    if not slot:
        raise HTTPException(status_code=404, detail="Slot not found")
    
    # Verify slot is held by current patient
    if slot.status != SlotStatus.HELD:
        raise HTTPException(
            status_code=400,
            detail="Slot is not held. Please hold the slot first."
        )
    
    if slot.held_by_patient_id != current_user["user_id"]:
        raise HTTPException(
            status_code=403,
            detail="This slot is held by another patient"
        )
    
    # ✅ VALIDATE: One appointment per day
    validate_one_appointment_per_day(
        db=db,
        patient_id=patient.id,
        appointment_date=slot.date
    )
    
    # Handle report upload (if provided)
    report_url = None
    if report:
        from services.cloudinary_service import CloudinaryService
        
        # Read file content
        file_content = await report.read()
        
        # Upload to Cloudinary
        report_url = CloudinaryService.upload_medical_report(
            file_bytes=file_content,
            filename=report.filename or "report",
            patient_id=patient.id,
            doctor_id=slot.doctor_id
        )
        
        if not report_url:
            raise HTTPException(
                status_code=500,
                detail="Failed to upload medical report. Please try again."
            )
    
    # Calculate approval expiry (24 hours for doctor to respond)
    now_utc = datetime.now(timezone.utc)
    approval_expiry = now_utc + timedelta(hours=APPOINTMENT_APPROVAL_TIMEOUT_HOURS)
    
    # Create appointment with REQUESTED status
    appointment = Appointment(
        doctor_id=slot.doctor_id,
        patient_id=patient.id,
        slot_id=slot.id,
        status=AppointmentStatus.REQUESTED,
        report=report_url,
        approval_expires_at=approval_expiry  # ⏰ Doctor has 24 hours
    )
    
    # Update slot status to BOOKED (locked for this appointment)
    slot.status = SlotStatus.BOOKED
    slot.held_at = None
    slot.held_expires_at = None
    # Keep held_by_patient_id for reference
    
    db.add(appointment)
    db.commit()
    db.refresh(appointment)
    
    # Convert to IST for display
    approval_expiry_ist = approval_expiry.astimezone(IST)
    
    # Get doctor details for email
    doctor = slot.doctor
    doctor_user = db.query(User).filter(User.id == doctor.user_id).first()
    patient_user = db.query(User).filter(User.id == patient.user_id).first()
    
    # Send email to doctor
    if doctor_user and patient_user:
        # Get doctor's device (use first active device or create a dummy device_id)
        from models.device import Device
        doctor_device = db.query(Device).filter(
            Device.user_id == doctor_user.id,
            Device.is_active == True
        ).first()
        doctor_device_id = doctor_device.id if doctor_device else 0
        
        await EmailService.send_appointment_request_to_doctor(
            doctor_email=doctor_user.email,
            doctor_name=doctor.name,
            patient_name=patient.name,
            patient_age=patient.age if hasattr(patient, 'age') else 0,
            patient_contact=patient_user.email,
            appointment_id=appointment.id,
            slot_date=slot.date.strftime("%d %B %Y"),
            slot_time=f"{slot.start_time.strftime('%I:%M %p')} - {slot.end_time.strftime('%I:%M %p')}",
            report_url=report_url,
            expiry_time=approval_expiry_ist.strftime("%d %B %Y, %I:%M %p IST"),
            doctor_user_id=doctor_user.id,
            doctor_role=doctor_user.role.value,
            doctor_device_id=doctor_device_id
        )
    
    return {
        "appointment_id": appointment.id,
        "status": appointment.status.value,
        "message": "Appointment request sent to doctor",
        "approval_deadline": approval_expiry_ist.isoformat(),
        "approval_deadline_formatted": approval_expiry_ist.strftime("%d %B %Y, %I:%M %p IST"),
        "timeout_hours": APPOINTMENT_APPROVAL_TIMEOUT_HOURS,
        "slot_details": {
            "date": slot.date.isoformat(),
            "start_time": str(slot.start_time),
            "end_time": str(slot.end_time)
        }
    }


# ─────────────────────────────────────────────────────────────
# ❌ CANCEL APPOINTMENT (Patient side - with time validation)
# ─────────────────────────────────────────────────────────────
@router.post("/{appointment_id}/cancel", dependencies=[Security(bearer_scheme)])
async def cancel_appointment(
    appointment_id: int,
    current_user: dict = Depends(roles_required(UserRole.PATIENT)),
    db: Session = Depends(get_db)
):
    """
    Patient cancels their appointment.
    Only allowed for REQUESTED, APPROVED appointments.
    Releases the slot if appointment was REQUESTED or APPROVED (not paid yet).
    """
    
    patient = db.query(Patient).filter(
        Patient.user_id == current_user["user_id"]
    ).first()
    
    if not patient:
        raise HTTPException(status_code=404, detail="Patient profile not found")
    
    appointment = db.query(Appointment).filter(
        Appointment.id == appointment_id,
        Appointment.patient_id == patient.id
    ).first()
    
    if not appointment:
        raise HTTPException(status_code=404, detail="Appointment not found")
    
    # Can't cancel completed or already cancelled appointments
    if appointment.status in [AppointmentStatus.CANCELLED, AppointmentStatus.COMPLETED]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel appointment with status: {appointment.status.value}"
        )
    
    # For CONFIRMED appointments (payment done), may need refund logic
    if appointment.status == AppointmentStatus.PAID:
        # TODO: Implement refund logic based on cancellation policy
        raise HTTPException(
            status_code=400,
            detail="Cannot cancel confirmed appointment. Please contact support."
        )
    
    # Update appointment status
    appointment.status = AppointmentStatus.CANCELLED
    
    # Release the slot if not paid
    if appointment.status in [AppointmentStatus.REQUESTED, AppointmentStatus.APPROVED]:
        slot = appointment.slot
        if slot:
            slot.status = SlotStatus.FREE
            slot.held_at = None
            slot.held_by_patient_id = None
            slot.held_expires_at = None
    
    db.commit()
    
    return {
        "appointment_id": appointment.id,
        "status": "CANCELLED",
        "message": "Appointment cancelled successfully"
    }


# ─────────────────────────────────────────────────────────────
# 👨‍⚕️ DOCTOR: Approve Appointment (WITH PAYMENT EMAIL)
# ─────────────────────────────────────────────────────────────
@router.post("/{appointment_id}/approve")
async def approve_appointment(
    appointment_id: int,
    request: Request,
    token: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """
    Doctor approves appointment.
    Changes status from REQUESTED to APPROVED.
    Sets payment_expires_at = now + 15 minutes (patient has 15 minutes to pay).
    Sends payment email to patient.
    
    Supports authentication via:
    - Bearer token (normal flow)
    - Query param token (from email links)
    """
    
    # Authenticate user (from token or bearer)
    current_user = await get_user_from_token_or_bearer(request, token, db)
    
    # Verify doctor role
    if current_user.get("role") != UserRole.DOCTOR.value:
        raise HTTPException(status_code=403, detail="Only doctors can approve appointments")
    
    # 🔥 Auto-expire old requests first
    expire_pending_approval_appointments_inline(db)
    expire_unpaid_appointments_inline(db)
    
    doctor = db.query(Doctor).filter(
        Doctor.user_id == current_user["user_id"]
    ).first()
    
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor profile not found")
    
    appointment = db.query(Appointment).filter(
        Appointment.id == appointment_id,
        Appointment.doctor_id == doctor.id
    ).first()
    
    if not appointment:
        raise HTTPException(status_code=404, detail="Appointment not found")
    
    # Make approval idempotent:
    # - If already APPROVED, simply return a success-style response instead of error
    # - Only block other terminal/invalid states
    if appointment.status == AppointmentStatus.APPROVED:
        patient = appointment.patient
        slot = appointment.slot

        # Use existing payment_expires_at if present
        payment_expiry = appointment.payment_expires_at
        payment_expiry_ist = (
            payment_expiry.astimezone(IST) if payment_expiry else None
        )

        return {
            "appointment_id": appointment.id,
            "status": "APPROVED",
            "message": "Appointment already approved. No further action needed.",
            "patient_name": patient.name if patient else None,
            "payment_deadline": payment_expiry_ist.isoformat() if payment_expiry_ist else None,
            "payment_deadline_formatted": payment_expiry_ist.strftime("%d %B %Y, %I:%M %p IST") if payment_expiry_ist else None,
            "payment_timeout_minutes": PAYMENT_TIMEOUT_MINUTES,
        }

    if appointment.status != AppointmentStatus.REQUESTED:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot approve appointment with status: {appointment.status.value}"
        )
    
    # Check if doctor's approval window has expired
    now_utc = datetime.now(timezone.utc)
    
    if appointment.approval_expires_at and appointment.approval_expires_at < now_utc:
        # Auto-cancel expired appointment
        appointment.status = AppointmentStatus.CANCELLED
        slot = appointment.slot
        if slot:
            slot.status = SlotStatus.FREE
        db.commit()
        
        raise HTTPException(
            status_code=400,
            detail="This appointment request has expired (24 hour window passed)"
        )
    
    # Approve the appointment and set payment expiry
    appointment.status = AppointmentStatus.APPROVED
    payment_expiry = now_utc + timedelta(minutes=PAYMENT_TIMEOUT_MINUTES)
    appointment.payment_expires_at = payment_expiry  # ⏰ Patient has 15 minutes to pay
    
    db.commit()
    db.refresh(appointment)
    
    # Get patient and slot details
    patient = appointment.patient
    patient_user = db.query(User).filter(User.id == patient.user_id).first()
    slot = appointment.slot
    
    # Convert to IST for display
    payment_expiry_ist = payment_expiry.astimezone(IST)
    
    # Send approval email to patient with payment link
    if patient_user:
        # Get patient's device (use first active device or create a dummy device_id)
        from models.device import Device
        patient_device = db.query(Device).filter(
            Device.user_id == patient_user.id,
            Device.is_active == True
        ).first()
        patient_device_id = patient_device.id if patient_device else 0
        
        await EmailService.send_approval_confirmation_to_patient(
            patient_email=patient_user.email,
            patient_name=patient.name,
            doctor_name=doctor.name,
            appointment_id=appointment.id,
            slot_date=slot.date.strftime("%d %B %Y"),
            slot_time=f"{slot.start_time.strftime('%I:%M %p')} - {slot.end_time.strftime('%I:%M %p')}",
            opd_fees=doctor.opd_fees,
            payment_expiry=payment_expiry_ist.strftime("%d %B %Y, %I:%M %p IST"),
            patient_user_id=patient_user.id,
            patient_role=patient_user.role.value,
            patient_device_id=patient_device_id
        )
    
    return {
        "appointment_id": appointment.id,
        "status": "APPROVED",
        "message": "Appointment approved. Patient will be notified to complete payment.",
        "patient_name": patient.name,
        "payment_deadline": payment_expiry_ist.isoformat(),
        "payment_deadline_formatted": payment_expiry_ist.strftime("%d %B %Y, %I:%M %p IST"),
        "payment_timeout_minutes": PAYMENT_TIMEOUT_MINUTES
    }


# ─────────────────────────────────────────────────────────────
# 👨‍⚕️ DOCTOR: Reject Appointment
# ─────────────────────────────────────────────────────────────
@router.post("/{appointment_id}/reject")
async def reject_appointment(
    appointment_id: int,
    request: Request,
    reason: Optional[str] = None,
    token: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """
    Doctor rejects appointment.
    Releases the slot back to FREE status.
    
    Supports authentication via:
    - Bearer token (normal flow)
    - Query param token (from email links)
    """
    
    # Authenticate user (from token or bearer)
    current_user = await get_user_from_token_or_bearer(request, token, db)
    
    # Verify doctor role
    if current_user.get("role") != UserRole.DOCTOR.value:
        raise HTTPException(status_code=403, detail="Only doctors can reject appointments")
    
    doctor = db.query(Doctor).filter(
        Doctor.user_id == current_user["user_id"]
    ).first()
    
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor profile not found")
    
    appointment = db.query(Appointment).filter(
        Appointment.id == appointment_id,
        Appointment.doctor_id == doctor.id
    ).first()
    
    if not appointment:
        raise HTTPException(status_code=404, detail="Appointment not found")
    
    if appointment.status != AppointmentStatus.REQUESTED:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot reject appointment with status: {appointment.status.value}"
        )
    
    # Reject appointment
    appointment.status = AppointmentStatus.REJECTED
    
    # Release the slot
    slot = appointment.slot
    if slot:
        slot.status = SlotStatus.FREE
        slot.held_at = None
        slot.held_by_patient_id = None
        slot.held_expires_at = None
    
    db.commit()
    
    # Get patient details for email
    patient = appointment.patient
    patient_user = db.query(User).filter(User.id == patient.user_id).first()
    
    # Send rejection email to patient
    if patient_user:
        await EmailService.send_rejection_notification_to_patient(
            patient_email=patient_user.email,
            patient_name=patient.name,
            doctor_name=doctor.name,
            slot_date=slot.date.strftime("%d %B %Y"),
            slot_time=f"{slot.start_time.strftime('%I:%M %p')} - {slot.end_time.strftime('%I:%M %p')}",
            rejection_reason=reason
        )
    
    return {
        "appointment_id": appointment.id,
        "status": "REJECTED",
        "message": "Appointment rejected. Patient will be notified.",
        "reason": reason
    }


# ─────────────────────────────────────────────────────────────
# 💳 GET APPOINTMENT PAYMENT DETAILS (For payment page)
# ─────────────────────────────────────────────────────────────
@router.get("/{appointment_id}/payment-details")
async def get_payment_details(
    appointment_id: int,
    request: Request,
    token: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """
    Get appointment details for payment page.
    Checks if payment window is still valid (15 minutes from approval).
    
    Supports authentication via:
    - Bearer token (normal flow)
    - Query param token (from email links)
    """
    
    # Authenticate user (from token or bearer)
    current_user = await get_user_from_token_or_bearer(request, token, db)
    
    # Verify patient role
    if current_user.get("role") != UserRole.PATIENT.value:
        raise HTTPException(status_code=403, detail="Only patients can view payment details")
    
    # Auto-expire unpaid appointments
    expire_unpaid_appointments_inline(db)
    
    patient = db.query(Patient).filter(
        Patient.user_id == current_user["user_id"]
    ).first()
    
    if not patient:
        raise HTTPException(status_code=404, detail="Patient profile not found")
    
    appointment = db.query(Appointment).filter(
        Appointment.id == appointment_id,
        Appointment.patient_id == patient.id
    ).first()
    
    if not appointment:
        raise HTTPException(status_code=404, detail="Appointment not found")
    
    # Check if appointment is in APPROVED status
    if appointment.status != AppointmentStatus.APPROVED:
        raise HTTPException(
            status_code=400,
            detail=f"Appointment is not in approved status. Current status: {appointment.status.value}"
        )
    
    # Check if payment window has expired
    now_utc = datetime.now(timezone.utc)
    if appointment.payment_expires_at and appointment.payment_expires_at < now_utc:
        # Expired - cancel appointment and release slot
        appointment.status = AppointmentStatus.CANCELLED
        slot = appointment.slot
        if slot:
            slot.status = SlotStatus.FREE
            slot.held_at = None
            slot.held_by_patient_id = None
            slot.held_expires_at = None
        db.commit()
        
        raise HTTPException(
            status_code=400,
            detail="Payment window has expired (15 minutes). Appointment cancelled."
        )
    
    # Calculate time remaining
    time_remaining = None
    if appointment.payment_expires_at:
        remaining = appointment.payment_expires_at - now_utc
        time_remaining = {
            "minutes": int(remaining.total_seconds() // 60),
            "seconds": int(remaining.total_seconds() % 60),
            "expires_at": appointment.payment_expires_at.astimezone(IST).isoformat()
        }
    
    slot = appointment.slot
    doctor = appointment.doctor
    
    return {
        "appointment_id": appointment.id,
        "doctor_name": doctor.name,
        "specialization": doctor.speciality,
        "opd_fees": doctor.opd_fees,
        "slot_date": slot.date.strftime("%d %B %Y"),
        "slot_time": f"{slot.start_time.strftime('%I:%M %p')} - {slot.end_time.strftime('%I:%M %p')}",
        "time_remaining": time_remaining,
        "payment_expires_at": appointment.payment_expires_at.astimezone(IST).isoformat() if appointment.payment_expires_at else None
    }



# Add these updated endpoints to your existing appointment_routes.py

# ─────────────────────────────────────────────────────────────
# 📊 GET PATIENT'S APPOINTMENTS (WITH PAGINATION & SEARCH)
# ─────────────────────────────────────────────────────────────
@router.get("/my-appointments", dependencies=[Security(bearer_scheme)])
async def get_my_appointments(
    status: Optional[str] = None,
    search: Optional[str] = None,  # Search by doctor name
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    current_user: dict = Depends(roles_required(UserRole.PATIENT)),
    db: Session = Depends(get_db)
):
    """
    Get all appointments for current patient with pagination and search.
    Auto-expires pending appointments before fetching.
    
    Query params:
    - status: Filter by status (REQUESTED, APPROVED, REJECTED, PAID, CANCELLED)
    - search: Search by doctor name
    - page: Page number (default: 1)
    - page_size: Items per page (default: 10, max: 100)
    """
    
    # 🔥 Auto-expire old requests
    expire_pending_approval_appointments_inline(db)
    expire_unpaid_appointments_inline(db)
    
    patient = db.query(Patient).filter(
        Patient.user_id == current_user["user_id"]
    ).first()
    
    if not patient:
        raise HTTPException(status_code=404, detail="Patient profile not found")
    
    # Base query
    query = db.query(Appointment).filter(
        Appointment.patient_id == patient.id
    )
    
    # Apply status filter
    if status:
        try:
            status_enum = AppointmentStatus(status.upper())
            query = query.filter(Appointment.status == status_enum)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")
    
    # Apply search filter (doctor name)
    if search:
        query = query.join(Doctor).filter(
            Doctor.name.ilike(f"%{search}%")
        )
    
    # Get total count
    total = query.count()
    
    # Calculate pagination
    total_pages = (total + page_size - 1) // page_size
    offset = (page - 1) * page_size
    
    # Apply pagination and ordering
    appointments = query.order_by(Appointment.created_at.desc()).offset(offset).limit(page_size).all()
    
    result = []
    for apt in appointments:
        slot = apt.slot
        doctor = apt.doctor
        
        # Calculate time remaining for doctor approval (if REQUESTED)
        approval_time_remaining = None
        if apt.status == AppointmentStatus.REQUESTED and apt.approval_expires_at:
            now_utc = datetime.now(timezone.utc)
            if apt.approval_expires_at > now_utc:
                remaining = apt.approval_expires_at - now_utc
                approval_time_remaining = {
                    "hours": int(remaining.total_seconds() // 3600),
                    "minutes": int((remaining.total_seconds() % 3600) // 60),
                    "expires_at": apt.approval_expires_at.astimezone(IST).isoformat()
                }
        
        # Calculate time remaining for payment (if APPROVED)
        payment_time_remaining = None
        if apt.status == AppointmentStatus.APPROVED and apt.payment_expires_at:
            now_utc = datetime.now(timezone.utc)
            if apt.payment_expires_at > now_utc:
                remaining = apt.payment_expires_at - now_utc
                payment_time_remaining = {
                    "minutes": int(remaining.total_seconds() // 60),
                    "seconds": int(remaining.total_seconds() % 60),
                    "expires_at": apt.payment_expires_at.astimezone(IST).isoformat()
                }
        
        result.append({
            "id": apt.id,
            "status": apt.status.value,
            "doctor_name": doctor.name,
            "specialization": doctor.speciality,
            "slot_date": slot.date.isoformat(),
            "slot_time": f"{slot.start_time} - {slot.end_time}",
            "created_at": apt.created_at.isoformat(),
            "approval_time_remaining": approval_time_remaining,
            "payment_time_remaining": payment_time_remaining,
            "opd_fees": doctor.opd_fees,
            "report": apt.report
        })
    
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "appointments": result
    }


# ─────────────────────────────────────────────────────────────
# 📊 GET DOCTOR'S APPOINTMENTS (WITH PAGINATION & SEARCH)
# ─────────────────────────────────────────────────────────────
@router.get("/doctor-appointments", dependencies=[Security(bearer_scheme)])
async def get_doctor_appointments(
    status: Optional[str] = None,
    search: Optional[str] = None,  # Search by patient name
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    current_user: dict = Depends(roles_required(UserRole.DOCTOR)),
    db: Session = Depends(get_db)
):
    """
    Get all appointments for current doctor with pagination and search.
    Auto-expires pending appointments before fetching.
    
    Query params:
    - status: Filter by status (REQUESTED, APPROVED, REJECTED, PAID, CANCELLED)
    - search: Search by patient name
    - page: Page number (default: 1)
    - page_size: Items per page (default: 10, max: 100)
    """
    
    # 🔥 Auto-expire old requests
    expire_pending_approval_appointments_inline(db)
    expire_unpaid_appointments_inline(db)
    
    doctor = db.query(Doctor).filter(
        Doctor.user_id == current_user["user_id"]
    ).first()
    
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor profile not found")
    
    # Base query
    query = db.query(Appointment).filter(
        Appointment.doctor_id == doctor.id
    )
    
    # Apply status filter
    if status:
        try:
            status_enum = AppointmentStatus(status.upper())
            query = query.filter(Appointment.status == status_enum)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")
    
    # Apply search filter (patient name)
    if search:
        query = query.join(Patient).filter(
            Patient.name.ilike(f"%{search}%")
        )
    
    # Get total count
    total = query.count()
    
    # Calculate pagination
    total_pages = (total + page_size - 1) // page_size
    offset = (page - 1) * page_size
    
    # Apply pagination and ordering
    appointments = query.order_by(Appointment.created_at.desc()).offset(offset).limit(page_size).all()
    
    result = []
    for apt in appointments:
        slot = apt.slot
        patient = apt.patient
        patient_user = db.query(User).filter(User.id == patient.user_id).first()
        
        # Calculate time remaining for doctor approval (if REQUESTED)
        approval_time_remaining = None
        if apt.status == AppointmentStatus.REQUESTED and apt.approval_expires_at:
            now_utc = datetime.now(timezone.utc)
            if apt.approval_expires_at > now_utc:
                remaining = apt.approval_expires_at - now_utc
                approval_time_remaining = {
                    "hours": int(remaining.total_seconds() // 3600),
                    "minutes": int((remaining.total_seconds() % 3600) // 60),
                    "expires_at": apt.approval_expires_at.astimezone(IST).isoformat()
                }
        
        # Calculate time remaining for payment (if APPROVED)
        payment_time_remaining = None
        if apt.status == AppointmentStatus.APPROVED and apt.payment_expires_at:
            now_utc = datetime.now(timezone.utc)
            if apt.payment_expires_at > now_utc:
                remaining = apt.payment_expires_at - now_utc
                payment_time_remaining = {
                    "minutes": int(remaining.total_seconds() // 60),
                    "seconds": int(remaining.total_seconds() % 60),
                    "expires_at": apt.payment_expires_at.astimezone(IST).isoformat()
                }
        
        result.append({
            "id": apt.id,
            "status": apt.status.value,
            "patient_name": patient.name,
            "patient_contact": patient_user.email if patient_user else None,
            "slot_date": slot.date.isoformat(),
            "slot_time": f"{slot.start_time} - {slot.end_time}",
            "created_at": apt.created_at.isoformat(),
            "approval_time_remaining": approval_time_remaining,
            "payment_time_remaining": payment_time_remaining,
            "opd_fees": doctor.opd_fees,
            "report": apt.report
        })
    
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "appointments": result
    }