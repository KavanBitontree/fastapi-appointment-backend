from sqlalchemy import Column, Integer, String, ForeignKey, Date
from sqlalchemy.orm import relationship
from core.database import Base

class Patient(Base):
    __tablename__ = "patients"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE", onupdate="CASCADE"), unique=True, nullable=False)
    name = Column(String, nullable=False)
    dob = Column(Date, nullable=False)  # Date of Birth instead of age

    # Relationship
    user = relationship("User", back_populates="patient")