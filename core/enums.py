from enum import Enum

class UserRole(str, Enum):
    DOCTOR = "DOCTOR"
    PATIENT = "PATIENT"

class SlotStatus(str, Enum):
    FREE = "FREE"
    HELD = "HELD"
    BOOKED = "BOOKED"
    BLOCKED = "BLOCKED"


class AppointmentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PAID = "PAID"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"

class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"

class NotificationType(str, Enum):
    APPO_REQ = "APPO_REQ"
    APPO_APPROVED = "APPO_APPROVED"
    APPO_REJECTED = "APPO_REJECTED"
    PAYMENT_SUCCESS = "PAYMENT_SUCCESS"
    PAYMENT_FAILED = "PAYMENT_FAILED"
    REMINDER = "REMINDER"