from sqlalchemy import Column, Integer, String, ForeignKey, Numeric, Enum, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from core.database import Base
from core.enums import PaymentStatus

class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    appointment_id = Column(Integer, ForeignKey("appointments.id", ondelete="CASCADE", onupdate="CASCADE"), unique=True, nullable=False)
    
    stripe_id = Column(String, nullable=True, index=True)  # Stripe payment intent ID
    amount = Column(Numeric(10, 2), nullable=False)
    currency = Column(String(3), nullable=False, default="INR")  # ISO 4217 currency code
    status = Column(Enum(PaymentStatus, name="payment_status"), nullable=False, default=PaymentStatus.PENDING)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    appointment = relationship("Appointment", back_populates="payment")

    def __repr__(self):
        return f"<Payment(id={self.id}, appointment_id={self.appointment_id}, amount={self.amount}, status={self.status})>"