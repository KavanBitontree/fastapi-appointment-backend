from sqlalchemy import Column, Integer, ForeignKey, Date, Time, Boolean, DateTime,UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from core.database import Base

class DoctorAvailability(Base):
    __tablename__ = "doctor_availability"

    id = Column(Integer, primary_key=True, index=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id", ondelete="CASCADE", onupdate="CASCADE"), nullable=False, index=True)
    
    date = Column(Date, nullable=False, index=True)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    is_available = Column(Boolean, default=True, nullable=False)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    doctor = relationship("Doctor", back_populates="availabilities")
    slots = relationship("DoctorSlot", back_populates="availability", cascade="all, delete-orphan")

    __table_args__ = (
    UniqueConstraint("doctor_id", "date", name="uq_doctor_date_availability"),
    )


    def __repr__(self):
        return f"<DoctorAvailability(id={self.id}, doctor_id={self.doctor_id}, date={self.date}, {self.start_time}-{self.end_time})>"