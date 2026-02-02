from sqlalchemy import Column, Integer, ForeignKey, Date, Time, Enum, DateTime, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from core.database import Base
from core.enums import SlotStatus

class DoctorSlot(Base):
    __tablename__ = "doctor_slots"

    id = Column(Integer, primary_key=True, index=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id", ondelete="CASCADE", onupdate="CASCADE"), nullable=False, index=True)
    avail_id = Column(Integer, ForeignKey("doctor_availability.id", ondelete="CASCADE", onupdate="CASCADE"), nullable=False, index=True)
    
    date = Column(Date, nullable=False, index=True)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    status = Column(Enum(SlotStatus, name="slot_status"), nullable=False, default=SlotStatus.FREE)
    
    # NEW: HELD status support columns
    held_at = Column(DateTime(timezone=True), nullable=True)
    held_by_patient_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    held_expires_at = Column(DateTime(timezone=True), nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    doctor = relationship("Doctor", back_populates="slots")
    availability = relationship("DoctorAvailability", back_populates="slots")
    appointment = relationship("Appointment", back_populates="slot", uselist=False)  # One slot = One appointment
    held_by_patient = relationship("User", foreign_keys=[held_by_patient_id])

    # Composite indexes for efficient slot queries
    __table_args__ = (
        Index('idx_doctor_date_status', 'doctor_id', 'date', 'status'),
        Index('idx_doctor_date_time', 'doctor_id', 'date', 'start_time'),
        # NEW: Index for expired holds cleanup (partial index in PostgreSQL)
        Index('idx_held_expires', 'held_expires_at', postgresql_where=(status == SlotStatus.HELD)),
        # NEW: Index for patient holds
        Index('idx_held_by_patient', 'held_by_patient_id', 'status'),
    )

    def __repr__(self):
        return f"<DoctorSlot(id={self.id}, doctor_id={self.doctor_id}, date={self.date}, {self.start_time}-{self.end_time}, status={self.status})>"