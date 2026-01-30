from sqlalchemy import Column, Integer, String, ForeignKey, Numeric, Float
from sqlalchemy.orm import relationship
from core.database import Base

class Doctor(Base):
    __tablename__ = "doctors"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE", onupdate="CASCADE"), unique=True, nullable=False)

    name = Column(String, nullable=False)
    speciality = Column(String, nullable=False)

    opd_fees = Column(Numeric(10, 2), nullable=False)
    minimum_slot_duration = Column(Numeric(4, 2), nullable=False)

    # 📍 LOCATION (NEW)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    address = Column(String, nullable=True)

    # Relationship
    user = relationship("User", back_populates="doctor")
