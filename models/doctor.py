from sqlalchemy import Column, Integer, String, ForeignKey, Numeric, Float, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from core.database import Base

class Doctor(Base):
    __tablename__ = "doctors"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE", onupdate="CASCADE"), unique=True, nullable=False)

    name = Column(String, nullable=False)
    speciality = Column(String, nullable=False, index=True)

    opd_fees = Column(Numeric(10, 2), nullable=False)
    minimum_slot_duration = Column(Numeric(4, 2), nullable=False)  # in hours (e.g., 0.5 = 30 minutes, 1.0 = 1 hour)

    # 📍 LOCATION
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    address = Column(String, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    user = relationship("User", back_populates="doctor")
    availabilities = relationship("DoctorAvailability", back_populates="doctor", cascade="all, delete-orphan")
    slots = relationship("DoctorSlot", back_populates="doctor", cascade="all, delete-orphan")
    appointments = relationship("Appointment", back_populates="doctor")  # Will be created later

    def __repr__(self):
        return f"<Doctor(id={self.id}, name={self.name}, speciality={self.speciality})>"