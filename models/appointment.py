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
    slot_id = Column(Integer, ForeignKey("doctor_slots.id", ondelete="RESTRICT", onupdate="CASCADE"), nullable=False , index=True)
    
    status = Column(Enum(AppointmentStatus, name="appointment_status"), nullable=False, default=AppointmentStatus.REQUESTED)
    report = Column(String, nullable=True)  # Cloudinary URL of medical report
    
    # ⏰ TIMELINE 1: Doctor has 24 hours to approve/reject after patient requests
    # Set when appointment is created with REQUESTED status
    # If doctor doesn't respond within 24 hours, appointment auto-cancels
    approval_expires_at = Column(DateTime(timezone=True), nullable=True, 
                                comment='When doctor approval window expires (24 hours from request)')
    
    # ⏰ TIMELINE 2: Patient has 15 minutes to pay after doctor approves
    # Set when doctor APPROVES the appointment
    # If patient doesn't pay within 15 minutes, appointment auto-cancels
    payment_expires_at = Column(DateTime(timezone=True), nullable=True,
                               comment='When patient payment window expires (15 minutes from approval)')
    
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
        # Index for doctor approval expiry (REQUESTED status)
        Index('idx_approval_expires', 'approval_expires_at', 'status'),
        # Index for patient payment expiry (APPROVED status)
        Index('idx_payment_expires', 'payment_expires_at', 'status'),
    )

    def __repr__(self):
        return f"<Appointment(id={self.id}, doctor_id={self.doctor_id}, patient_id={self.patient_id}, status={self.status})>"