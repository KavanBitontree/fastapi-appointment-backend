from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from zoneinfo import ZoneInfo

from deps import get_db
from schemas.password_reset_token import (
    ForgotPasswordRequest,
    ResetPasswordRequest,
    PasswordResetResponse
)
from services.password_reset_service import PasswordResetService

# IST timezone
IST = ZoneInfo("Asia/Kolkata")

router = APIRouter(prefix="/auth", tags=["Authentication - Password Reset"])


@router.post(
    "/forgot-password",
    response_model=PasswordResetResponse,
    status_code=status.HTTP_200_OK,
    summary="Request password reset",
    description="""
    Send password reset email to user.
    
    **Security Features:**
    - Always returns success message (doesn't reveal if email exists)
    - Generates cryptographically secure token
    - Token expires in 15 minutes
    - Invalidates previous unused tokens
    - Single-use tokens only
    - Timezone-aware expiry tracking
    
    **Process:**
    1. User provides their email
    2. System validates email exists and account is active
    3. Previous unused tokens are invalidated
    4. New secure token is generated and stored with UTC timezone
    5. Reset email is sent with expiring link
    6. Generic success message returned
    """
)
async def forgot_password(
    request: ForgotPasswordRequest,
    db: Session = Depends(get_db)
):
    """Request password reset email"""
    return await PasswordResetService.request_password_reset(
        db=db,
        email=request.email
    )


@router.post(
    "/reset-password",
    response_model=PasswordResetResponse,
    status_code=status.HTTP_200_OK,
    summary="Reset password with token",
    description="""
    Reset user password using valid reset token.
    
    **Validation:**
    - Token must exist in database
    - Token must not be expired (15 min window, timezone-aware check)
    - Token must not have been used
    - New password must meet strength requirements (min 8 chars)
    
    **Process:**
    1. User provides reset token and new password
    2. Token is validated (timezone-aware expiry check)
    3. Password is hashed and updated
    4. Token is marked as used
    5. User can login with new password
    """
)
def reset_password(
    request: ResetPasswordRequest,
    db: Session = Depends(get_db)
):
    """Reset password using token"""
    response = PasswordResetService.reset_password(
        db=db,
        token=request.token,
        new_password=request.new_password
    )
    
    if not response.success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=response.message
        )
    
    return response


@router.post(
    "/validate-reset-token",
    status_code=status.HTTP_200_OK,
    summary="Validate password reset token",
    description="""
    Check if a password reset token is valid.
    
    Useful for frontend to validate token before showing reset form.
    Returns 200 if valid, 400 if invalid/expired.
    Includes time remaining in response (similar to appointment system).
    """
)
def validate_reset_token(
    token: str,
    db: Session = Depends(get_db)
):
    """Validate if reset token is valid and not expired"""
    db_token = PasswordResetService.validate_reset_token(db, token)
    
    if not db_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token"
        )
    
    # Get time remaining (similar to appointment payment countdown)
    time_remaining = PasswordResetService.get_time_remaining(db_token.expires_at)
    
    return {
        "message": "Token is valid",
        "expires_at_utc": db_token.expires_at.isoformat(),
        "expires_at_ist": db_token.expires_at.astimezone(IST).isoformat(),
        "expires_at_ist_formatted": db_token.expires_at.astimezone(IST).strftime("%d %B %Y, %I:%M %p IST"),
        "time_remaining": time_remaining
    }