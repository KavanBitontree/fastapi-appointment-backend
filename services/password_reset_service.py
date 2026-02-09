import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_
from zoneinfo import ZoneInfo

from models.user import User
from models.password_reset_token import PasswordResetToken
from schemas.password_reset_token import (
    PasswordResetTokenCreate,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    PasswordResetResponse
)
from services.smtp_mail_service import EmailService
from services.security import hash_password

# IST timezone
IST = ZoneInfo("Asia/Kolkata")


class PasswordResetService:
    """Service for handling password reset operations"""
    
    # Token expiry time in minutes
    TOKEN_EXPIRY_MINUTES = 15
    
    # Token length (bytes)
    TOKEN_LENGTH = 32
    
    @staticmethod
    def generate_secure_token() -> str:
        """
        Generate a cryptographically secure random token
        
        Returns:
            Secure random token string (URL-safe)
        """
        return secrets.token_urlsafe(PasswordResetService.TOKEN_LENGTH)
    
    @staticmethod
    async def request_password_reset(
        db: Session,
        email: str
    ) -> PasswordResetResponse:
        """
        Process forgot password request and send reset email
        
        Args:
            db: Database session
            email: User's email address
            
        Returns:
            PasswordResetResponse with success status
        """
        # Find user by email
        user = db.query(User).filter(User.email == email).first()
        
        # Always return success message for security (don't reveal if email exists)
        success_message = (
            "If an account exists with this email, "
            "you will receive password reset instructions shortly."
        )
        
        if not user:
            # Don't reveal that user doesn't exist
            return PasswordResetResponse(
                message=success_message,
                success=True
            )
        
        # Check if user account is active
        if not user.is_active:
            # Don't reveal that account is inactive
            return PasswordResetResponse(
                message=success_message,
                success=True
            )
        
        # Invalidate any existing unused tokens for this user
        db.query(PasswordResetToken).filter(
            and_(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.used == False
            )
        ).update({"used": True})
        db.commit()
        
        # Generate new secure token
        reset_token = PasswordResetService.generate_secure_token()
        
        # Calculate expiry time (timezone-aware UTC)
        now_utc = datetime.now(timezone.utc)
        expires_at = now_utc + timedelta(
            minutes=PasswordResetService.TOKEN_EXPIRY_MINUTES
        )
        
        # Store token in database
        db_token = PasswordResetToken(
            user_id=user.id,
            token=reset_token,
            expires_at=expires_at,
            used=False
        )
        db.add(db_token)
        db.commit()
        
        # Send reset email
        email_sent = await EmailService.send_password_reset_email(
            user_email=user.email,
            reset_token=reset_token,
            user_name=user.email.split('@')[0],  # Use email username as name
            expiry_minutes=PasswordResetService.TOKEN_EXPIRY_MINUTES
        )
        
        if not email_sent:
            # Log error but don't expose it to user
            print(f"Failed to send password reset email to {email}")
        
        return PasswordResetResponse(
            message=success_message,
            success=True
        )
    
    @staticmethod
    def validate_reset_token(
        db: Session,
        token: str
    ) -> Optional[PasswordResetToken]:
        """
        Validate password reset token
        
        Args:
            db: Database session
            token: Reset token to validate
            
        Returns:
            PasswordResetToken if valid, None otherwise
        """
        # Find token in database
        db_token = db.query(PasswordResetToken).filter(
            PasswordResetToken.token == token
        ).first()
        
        if not db_token:
            return None
        
        # Check if token has been used
        if db_token.used:
            return None
        
        # Check if token has expired (timezone-aware comparison)
        now_utc = datetime.now(timezone.utc)
        if now_utc > db_token.expires_at:
            return None
        
        return db_token
    
    @staticmethod
    def reset_password(
        db: Session,
        token: str,
        new_password: str
    ) -> PasswordResetResponse:
        """
        Reset user password using valid token
        
        Args:
            db: Database session
            token: Valid reset token
            new_password: New password to set
            
        Returns:
            PasswordResetResponse with success status
        """
        # Validate token
        db_token = PasswordResetService.validate_reset_token(db, token)
        
        if not db_token:
            return PasswordResetResponse(
                message="Invalid or expired reset token. Please request a new password reset.",
                success=False
            )
        
        # Get user
        user = db.query(User).filter(User.id == db_token.user_id).first()
        
        if not user:
            return PasswordResetResponse(
                message="User not found.",
                success=False
            )
        
        # Validate password strength (add your validation logic)
        if len(new_password) < 8:
            return PasswordResetResponse(
                message="Password must be at least 8 characters long.",
                success=False
            )
        
        # Update user password
        user.hashed_password = hash_password(new_password)
        
        # Mark token as used
        db_token.used = True
        
        # Commit changes
        db.commit()
        
        return PasswordResetResponse(
            message="Password has been reset successfully. You can now login with your new password.",
            success=True
        )
    
    @staticmethod
    def cleanup_expired_tokens(db: Session) -> int:
        """
        Clean up expired password reset tokens (should be run periodically)
        
        Args:
            db: Database session
            
        Returns:
            Number of tokens deleted
        """
        now_utc = datetime.now(timezone.utc)
        
        deleted_count = db.query(PasswordResetToken).filter(
            PasswordResetToken.expires_at < now_utc
        ).delete()
        
        db.commit()
        
        return deleted_count
    
    @staticmethod
    def get_time_remaining(expires_at: datetime) -> dict:
        """
        Calculate time remaining until expiry (similar to appointment system)
        
        Args:
            expires_at: Expiry datetime (timezone-aware)
            
        Returns:
            Dict with minutes, seconds, and IST formatted expiry
        """
        now_utc = datetime.now(timezone.utc)
        
        if now_utc >= expires_at:
            return {
                "expired": True,
                "minutes": 0,
                "seconds": 0,
                "expires_at_ist": expires_at.astimezone(IST).isoformat()
            }
        
        remaining = expires_at - now_utc
        
        return {
            "expired": False,
            "minutes": int(remaining.total_seconds() // 60),
            "seconds": int(remaining.total_seconds() % 60),
            "expires_at_ist": expires_at.astimezone(IST).isoformat(),
            "expires_at_ist_formatted": expires_at.astimezone(IST).strftime("%d %B %Y, %I:%M %p IST")
        }