import enum

class UserRole(str, enum.Enum):
    DOCTOR = "DOCTOR"
    PATIENT = "PATIENT"
