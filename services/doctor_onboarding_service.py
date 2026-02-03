from datetime import date, timedelta, time
from sqlalchemy.orm import Session
from services.availability_service import create_availability
from schemas.doctor_availability import DoctorAvailabilityCreate

ROLLING_DAYS = 30


def setup_default_doctor_availability(
    db: Session,
    *,
    doctor,
    clinic_start: time,
    clinic_end: time,
):
    """
    Create default availability + slots
    for next ROLLING_DAYS.
    """

    today = date.today()

    for i in range(ROLLING_DAYS):
        day = today + timedelta(days=i)

        payload = DoctorAvailabilityCreate(
            date=day,
            start_time=clinic_start,
            end_time=clinic_end,
            is_available=True
        )

        create_availability(
            db=db,
            doctor=doctor,
            payload=payload
        )
