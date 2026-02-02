from sqlalchemy import Column, Integer, String, ForeignKey, Enum, DateTime, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from core.database import Base
from core.enums import AppointmentStatus

class Appointment(Base):
    __tablename__ = "appointments"

    id = Column(Integer, primary_key=True, index=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id", ondelete="CASCADE", onupdate="CASCADE"), nullable=False, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE", onupdate="CASCADE"), nullable=False, index=True)
    slot_id = Column(Integer, ForeignKey("doctor_slots.id", ondelete="RESTRICT", onupdate="CASCADE"), unique=True, nullable=False)
    
    status = Column(Enum(AppointmentStatus, name="appointment_status"), nullable=False, default=AppointmentStatus.REQUESTED)
    report = Column(String, nullable=True)  # Path to PDF/Image file
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    doctor = relationship("Doctor", back_populates="appointments")
    patient = relationship("Patient", back_populates="appointments")
    slot = relationship("DoctorSlot", back_populates="appointment")
    payment = relationship("Payment", back_populates="appointment", uselist=False, cascade="all, delete-orphan")

    # Composite indexes for common queries
    __table_args__ = (
        Index('idx_doctor_status', 'doctor_id', 'status'),
        Index('idx_patient_status', 'patient_id', 'status'),
        Index('idx_doctor_created', 'doctor_id', 'created_at'),
        Index('idx_patient_created', 'patient_id', 'created_at'),
    )

    def __repr__(self):
        return f"<Appointment(id={self.id}, doctor_id={self.doctor_id}, patient_id={self.patient_id}, status={self.status})>"