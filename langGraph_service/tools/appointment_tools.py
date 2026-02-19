"""
Appointment tools for LangGraph chatbot.
Direct DB operations — same server, no HTTP calls needed.
"""

from sqlalchemy.orm import Session
from typing import List, Optional, Dict
from datetime import datetime, timedelta, date as dt_date, timezone
from zoneinfo import ZoneInfo

from langGraph_service.tools.datetime_tools import get_current_ist_date

IST = ZoneInfo("Asia/Kolkata")
APPOINTMENT_APPROVAL_TIMEOUT_HOURS = 24


def get_patient_appointments(
    db: Session,
    patient_id: int,
    status_filter: Optional[str] = None,
    limit: int = 5
) -> List[Dict]:
    """Get patient's recent appointments."""
    from models.appointment import Appointment
    from models.doctor_slot import DoctorSlot
    from models.doctor import Doctor
    from core.enums import AppointmentStatus

    query = db.query(Appointment).filter(Appointment.patient_id == patient_id)

    if status_filter:
        try:
            status_enum = AppointmentStatus(status_filter.upper())
            query = query.filter(Appointment.status == status_enum)
        except ValueError:
            pass

    appointments = query.order_by(Appointment.created_at.desc()).limit(limit).all()

    result = []
    for apt in appointments:
        slot = apt.slot
        doctor = apt.doctor
        result.append({
            "id": apt.id,
            "status": apt.status.value,
            "doctor_name": doctor.name,
            "speciality": doctor.speciality,
            "slot_date": slot.date.isoformat(),
            "slot_time": f"{slot.start_time} - {slot.end_time}",
            "opd_fees": float(doctor.opd_fees),
            "created_at": apt.created_at.isoformat() if apt.created_at else None,
        })

    return result


def check_patient_can_book_on_date(db: Session, patient_id: int, date: dt_date) -> Dict:
    """
    Check if patient can book on a specific date.
    Rules:
    1. Date must not be in the past
    2. Date must be >= 25 hours from now (25hr buffer for doctor approval)
    3. Patient must not already have an appointment on that date
    """
    from models.appointment import Appointment
    from models.doctor_slot import DoctorSlot
    from core.enums import AppointmentStatus

    today = get_current_ist_date()

    if date < today:
        return {"can_book": False, "reason": "Cannot book appointments in the past.", "existing": None}

    # Check 25-hour buffer
    from datetime import datetime as dt
    import datetime as dtt
    start_of_day = dt.combine(date, dtt.time.min).replace(tzinfo=IST)
    now_ist = dt.now(IST)
    hours_until = (start_of_day - now_ist).total_seconds() / 3600

    if hours_until < 25:
        from langGraph_service.tools.datetime_tools import format_date_friendly
        earliest = today + __import__('datetime').timedelta(days=1)
        # More precisely: earliest bookable date
        return {
            "can_book": False,
            "reason": (
                f"Appointments must be booked at least 25 hours in advance to allow the doctor "
                f"24 hours to approve. Please book for {format_date_friendly(today + __import__('datetime').timedelta(days=1))} or later."
            ),
            "existing": None
        }

    existing = db.query(Appointment).join(DoctorSlot).filter(
        Appointment.patient_id == patient_id,
        DoctorSlot.date == date,
        Appointment.status.in_([
            AppointmentStatus.REQUESTED,
            AppointmentStatus.APPROVED,
            AppointmentStatus.PAID,
        ])
    ).first()

    if existing:
        slot = existing.slot
        doctor = existing.doctor
        return {
            "can_book": False,
            "reason": "You already have an appointment on this date.",
            "existing": {
                "id": existing.id,
                "status": existing.status.value,
                "doctor_name": doctor.name,
                "speciality": doctor.speciality,
                "slot_time": f"{slot.start_time} - {slot.end_time}",
            }
        }

    return {"can_book": True, "reason": None, "existing": None}


def get_free_slots_for_doctor_on_date(
    db: Session,
    doctor_id: int,
    date: dt_date
) -> Dict:
    """Get FREE slots for a doctor on a specific date."""
    from models.doctor_slot import DoctorSlot
    from models.doctor import Doctor
    from core.enums import SlotStatus
    from services.slot_cleanup_service import release_expired_holds, delete_unbookable_free_slots

    # Auto-cleanup
    release_expired_holds(db)
    delete_unbookable_free_slots(db)

    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doctor:
        return {"doctor_found": False, "slots": [], "total": 0}

    slots = db.query(DoctorSlot).filter(
        DoctorSlot.doctor_id == doctor_id,
        DoctorSlot.date == date,
        DoctorSlot.status == SlotStatus.FREE
    ).order_by(DoctorSlot.start_time).all()

    slots_data = []
    for s in slots:
        slots_data.append({
            "id": s.id,
            "date": s.date.isoformat(),
            "start_time": str(s.start_time),
            "end_time": str(s.end_time),
            "status": s.status.value,
        })

    return {
        "doctor_found": True,
        "doctor_id": doctor.id,
        "doctor_name": doctor.name,
        "speciality": doctor.speciality,
        "opd_fees": float(doctor.opd_fees),
        "address": doctor.address,
        "slots": slots_data,
        "total": len(slots_data),
    }


def get_slots_near_preferred_time(
    slots: List[Dict],
    preferred_hour: int,
    preferred_minute: int = 0,
    tolerance_hours: int = 2
) -> List[Dict]:
    """Filter slots near a preferred time window."""
    preferred_minutes = preferred_hour * 60 + preferred_minute
    result = []
    for slot in slots:
        parts = str(slot["start_time"]).split(":")
        slot_hour = int(parts[0])
        slot_minute = int(parts[1]) if len(parts) > 1 else 0
        slot_minutes = slot_hour * 60 + slot_minute
        diff = abs(slot_minutes - preferred_minutes)
        if diff <= tolerance_hours * 60:
            slot["time_diff_minutes"] = diff
            result.append(slot)
    result.sort(key=lambda x: x["time_diff_minutes"])
    return result


async def request_appointment_via_bot(
    db: Session,
    patient_id: int,
    slot_id: int
) -> Dict:
    """
    Request appointment directly (bot flow — no hold required).
    Mirrors the /appointments/bot/request route logic.
    """
    from models.appointment import Appointment
    from models.doctor_slot import DoctorSlot
    from models.patient import Patient
    from models.user import User
    from models.device import Device
    from core.enums import SlotStatus, AppointmentStatus
    from services.smtp_mail_service import EmailService

    try:
        patient = db.query(Patient).filter(Patient.id == patient_id).first()
        if not patient:
            return {"success": False, "error": "Patient not found"}

        slot = db.query(DoctorSlot).filter(DoctorSlot.id == slot_id).with_for_update().first()
        if not slot:
            return {"success": False, "error": "Slot not found"}

        if slot.status != SlotStatus.FREE:
            return {"success": False, "error": f"Slot is not available (status: {slot.status.value})"}

        # Check one-appointment-per-day
        availability = check_patient_can_book_on_date(db, patient_id, slot.date)
        if not availability["can_book"]:
            return {"success": False, "error": availability["reason"], "existing": availability.get("existing")}
    except Exception as e:
        db.rollback()
        print(f"[request_appointment_via_bot] Pre-booking validation error: {type(e).__name__}: {str(e)}")
        return {"success": False, "error": f"Validation failed: {str(e)}"}

    try:
        now_utc = datetime.now(timezone.utc)
        approval_expiry = now_utc + timedelta(hours=APPOINTMENT_APPROVAL_TIMEOUT_HOURS)

        appointment = Appointment(
            doctor_id=slot.doctor_id,
            patient_id=patient.id,
            slot_id=slot.id,
            status=AppointmentStatus.REQUESTED,
            report=None,
            approval_expires_at=approval_expiry,
        )

        slot.status = SlotStatus.BOOKED
        slot.held_at = None
        slot.held_expires_at = None
        slot.held_by_patient_id = patient.user_id

        db.add(appointment)
        db.commit()
        db.refresh(appointment)
    except Exception as e:
        db.rollback()
        print(f"[request_appointment_via_bot] Database commit error: {type(e).__name__}: {str(e)}")
        return {"success": False, "error": f"Failed to save appointment: {str(e)}"}

    doctor = slot.doctor
    doctor_user = db.query(User).filter(User.id == doctor.user_id).first()
    patient_user = db.query(User).filter(User.id == patient.user_id).first()

    if doctor_user and patient_user:
        try:
            doctor_device = db.query(Device).filter(
                Device.user_id == doctor_user.id,
                Device.is_active == True
            ).first()
            doctor_device_id = doctor_device.id if doctor_device else 0

            age = 0
            if hasattr(patient, 'dob') and patient.dob:
                from datetime import date as dt_date_inner
                today = dt_date_inner.today()
                age = today.year - patient.dob.year - (
                    (today.month, today.day) < (patient.dob.month, patient.dob.day)
                )

            await EmailService.send_appointment_request_to_doctor(
                doctor_email=doctor_user.email,
                doctor_name=doctor.name,
                patient_name=patient.name,
                patient_age=age,
                patient_contact=patient_user.email,
                appointment_id=appointment.id,
                slot_date=slot.date.strftime("%d %B %Y"),
                slot_time=f"{slot.start_time.strftime('%I:%M %p')} - {slot.end_time.strftime('%I:%M %p')}",
                report_url=None,
                expiry_time=approval_expiry.astimezone(IST).strftime("%d %B %Y, %I:%M %p IST"),
                doctor_user_id=doctor_user.id,
                doctor_role=doctor_user.role.value,
                doctor_device_id=doctor_device_id,
            )
        except Exception as e:
            print(f"[Bot] Email notification failed (non-critical): {e}")

    return {
        "success": True,
        "appointment_id": appointment.id,
        "status": appointment.status.value,
        "doctor_name": doctor.name,
        "slot_date": slot.date.isoformat(),
        "slot_time": f"{slot.start_time} - {slot.end_time}",
        "approval_deadline": approval_expiry.astimezone(IST).strftime("%d %B %Y, %I:%M %p IST"),
    }