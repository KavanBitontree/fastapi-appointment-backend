from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime, timezone

from core.database import Base


class PasswordResetToken(Base):
    """Model for password reset tokens"""
    
    __tablename__ = "password_reset_tokens"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token = Column(String(100), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    used = Column(Boolean, default=False, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    # Relationship
    user = relationship("User", back_populates="password_reset_tokens")
    
    # Composite indexes for efficient queries
    __table_args__ = (
        # Index for finding valid tokens
        Index('idx_user_valid_tokens', 'user_id', 'used', 'expires_at'),
        # Index for cleanup of expired tokens (partial index in PostgreSQL)
        Index('idx_expired_tokens', 'expires_at', postgresql_where=(used == False)),
    )
    
    def __repr__(self):
        return f"<PasswordResetToken(id={self.id}, user_id={self.user_id}, used={self.used})>"
    
    @property
    def is_expired(self) -> bool:
        """Check if token has expired (timezone-aware)"""
        now_utc = datetime.now(timezone.utc)
        return now_utc > self.expires_at
    
    @property
    def is_valid(self) -> bool:
        """Check if token is valid (not used and not expired)"""
        return not self.used and not self.is_expired