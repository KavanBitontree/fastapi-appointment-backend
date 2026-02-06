from sqlalchemy import Column, Integer, String, Boolean, Enum
from sqlalchemy.orm import relationship
from core.database import Base
from core.enums import UserRole

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    role = Column(Enum(UserRole, name="user_role"), nullable=False)
    is_active = Column(Boolean, default=True)

    # Relationships
    doctor = relationship("Doctor", uselist=False, back_populates="user", cascade="all, delete-orphan")
    patient = relationship("Patient", uselist=False, back_populates="user", cascade="all, delete-orphan")
    devices = relationship("Device", back_populates="user", cascade="all, delete-orphan")
    refresh_tokens = relationship("RefreshToken", back_populates="user", cascade="all, delete-orphan")

    # ✅ Password reset tokens relationship
    password_reset_tokens = relationship(
        "PasswordResetToken", 
        back_populates="user",
        cascade="all, delete-orphan"  # Optional: delete tokens when user deleted
    )