from datetime import date
from sqlalchemy.orm import Session
from models.doctor_slot import DoctorSlot
from core.enums import SlotStatus


def delete_past_free_slots(db: Session):
    """
    Cleanup job:
    deletes past FREE slots only
    """
    today = date.today()

    db.query(DoctorSlot).filter(
        DoctorSlot.date < today,
        DoctorSlot.status == SlotStatus.FREE
    ).delete(synchronize_session=False)
