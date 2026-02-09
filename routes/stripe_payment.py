from fastapi import APIRouter, Depends, HTTPException, Request, Query, Response
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from typing import Optional
import stripe
from decimal import Decimal
from jose import jwt, JWTError

from core.config import settings
from deps import get_db
from core.enums import AppointmentStatus, SlotStatus, PaymentStatus
from models.appointment import Appointment
from models.doctor_slot import DoctorSlot
from models.payment import Payment
from models.patient import Patient
from models.user import User
from routes.appointment_routes import expire_unpaid_appointments_inline
from middlewares.auth import get_current_user

# Helper function for token-based auth (duplicated from appointment_routes)
async def get_user_from_token_or_bearer(
    request: Request,
    token: Optional[str],
    db: Session
) -> dict:
    """Authenticate user either via Bearer token or query param token"""
    if token:
        try:
            payload = jwt.decode(
                token,
                settings.JWT_SECRET_KEY,
                algorithms=[settings.JWT_ALGORITHM],
            )
            user_id = payload.get("user_id")
            role = payload.get("role")
            
            if not user_id or not role:
                raise HTTPException(status_code=401, detail="Invalid token payload")
            
            user = db.query(User).filter(
                User.id == user_id,
                User.is_active == True
            ).first()
            
            if not user:
                raise HTTPException(status_code=401, detail="User account is inactive or deleted")
            
            return {
                "user_id": user_id,
                "role": role,
                "device_id": payload.get("device_id", 0)
            }
        except JWTError:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
    
    # Fall back to Bearer token authentication
    return await get_current_user(request, db)

# Initialize Stripe
stripe.api_key = settings.STRIPE_SECRET_KEY

router = APIRouter(
    prefix="",
    tags=["Payment"]
)


# ─────────────────────────────────────────────────────────────
# 💳 CREATE PAYMENT INTENT (Redirect to Stripe Checkout)
# ─────────────────────────────────────────────────────────────
@router.get("/pay")
async def create_payment_intent(
    appointment_id: int = Query(..., description="Appointment ID"),
    token: Optional[str] = Query(None, description="Access token from email"),
    request: Request = None,
    db: Session = Depends(get_db)
):
    """
    Create Stripe payment intent and redirect to Stripe Checkout.
    Supports token-based auth from email links.
    """
    
    # Authenticate user (from token or bearer)
    # NOTE: when the patient comes from an email link we get a `token` query param.
    # We will also propagate this token to the Stripe success/cancel URLs so that
    # the verification step can authenticate the same way.
    current_user = await get_user_from_token_or_bearer(request, token, db)
    
    # Verify patient role
    if current_user.get("role") != "PATIENT":
        raise HTTPException(status_code=403, detail="Only patients can make payments")
    
    # Auto-expire unpaid appointments
    expire_unpaid_appointments_inline(db)
    
    # Get patient
    patient = db.query(Patient).filter(
        Patient.user_id == current_user["user_id"]
    ).first()
    
    if not patient:
        raise HTTPException(status_code=404, detail="Patient profile not found")
    
    # Get appointment
    appointment = db.query(Appointment).filter(
        Appointment.id == appointment_id,
        Appointment.patient_id == patient.id
    ).first()
    
    if not appointment:
        raise HTTPException(status_code=404, detail="Appointment not found")
    
    # Verify appointment is in APPROVED status
    if appointment.status != AppointmentStatus.APPROVED:
        raise HTTPException(
            status_code=400,
            detail=f"Appointment is not approved. Current status: {appointment.status.value}"
        )
    
    # Check if payment window has expired
    now_utc = datetime.now(timezone.utc)
    if appointment.payment_expires_at and appointment.payment_expires_at < now_utc:
        # Expired - cancel appointment and release slot
        appointment.status = AppointmentStatus.CANCELLED
        slot = appointment.slot
        if slot:
            slot.status = SlotStatus.FREE
            slot.held_at = None
            slot.held_by_patient_id = None
            slot.held_expires_at = None
        db.commit()
        
        raise HTTPException(
            status_code=400,
            detail="Payment window has expired (15 minutes). Appointment cancelled."
        )
    
    # Get doctor and slot details
    doctor = appointment.doctor
    slot = appointment.slot
    
    # Convert amount to paise (Stripe uses smallest currency unit)
    # For INR, 1 rupee = 100 paise
    amount_paise = int(float(doctor.opd_fees) * 100)
    
    # Check if payment already exists
    existing_payment = db.query(Payment).filter(
        Payment.appointment_id == appointment_id
    ).first()
    
    if existing_payment and existing_payment.status == PaymentStatus.SUCCESS:
        raise HTTPException(
            status_code=400,
            detail="Payment already completed for this appointment"
        )
    
    # Create or update payment record
    if existing_payment:
        payment = existing_payment
    else:
        payment = Payment(
            appointment_id=appointment_id,
            amount=Decimal(str(doctor.opd_fees)),
            currency="INR",
            status=PaymentStatus.PENDING
        )
        db.add(payment)
        db.flush()
    
    try:
        # Calculate expires_at for Stripe Checkout Session
        # Stripe requires at least 30 minutes from session creation
        # We need to use the maximum of:
        # 1. Payment expiry time (15 minutes from approval) - if still valid
        # 2. 30 minutes from now (Stripe's minimum requirement)
        from datetime import timedelta
        
        min_stripe_expiry = now_utc + timedelta(minutes=30)  # Stripe's minimum: 30 minutes
        
        if appointment.payment_expires_at and appointment.payment_expires_at > min_stripe_expiry:
            # Payment window is longer than 30 minutes, use it
            stripe_expires_at = appointment.payment_expires_at
        else:
            # Use Stripe's minimum (30 minutes) or payment expiry, whichever is later
            stripe_expires_at = max(min_stripe_expiry, appointment.payment_expires_at) if appointment.payment_expires_at else min_stripe_expiry
        
        # Build success/cancel URLs
        # If the payment was initiated from an email link we include the same token
        # so that `/payment/verify` and `/appointments/{id}/payment-details`
        # can authenticate using the token (even if the patient is not logged in).
        token_query = f"&token={token}" if token else ""
        success_url = (
            f"{settings.FRONTEND_URL}/patient/payment/success"
            f"?appointment_id={appointment_id}&session_id={{CHECKOUT_SESSION_ID}}{token_query}"
        )
        cancel_url = (
            f"{settings.FRONTEND_URL}/patient/payment"
            f"?appointment_id={appointment_id}{token_query}"
        )

        # Create Stripe Checkout Session
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'inr',
                    'product_data': {
                        'name': f'Appointment with Dr. {doctor.name}',
                        'description': f'Appointment on {slot.date.strftime("%d %B %Y")} at {slot.start_time.strftime("%I:%M %p")}',
                    },
                    'unit_amount': amount_paise,
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={
                'appointment_id': str(appointment_id),
                'patient_id': str(patient.id),
                'doctor_id': str(doctor.id),
            },
            expires_at=int(stripe_expires_at.timestamp()),
        )
        
        # Update payment with Stripe session ID
        payment.stripe_id = checkout_session.id
        db.commit()
        
        # Redirect to Stripe Checkout
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url=checkout_session.url, status_code=303)
        
    except stripe.error.StripeError as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Stripe error: {str(e)}"
        )


# ─────────────────────────────────────────────────────────────
# 🔔 STRIPE WEBHOOK (Handle payment success/failure)
# ─────────────────────────────────────────────────────────────
@router.post("/stripe/webhook")
async def stripe_webhook(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Handle Stripe webhook events.
    Updates payment, appointment, and slot statuses on successful payment.
    """
    
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    
    # Get webhook secret from settings (add STRIPE_WEBHOOK_SECRET to .env)
    webhook_secret = settings.STRIPE_WEBHOOK_SECRET
    
    try:
        if webhook_secret:
            # Verify webhook signature in production
            event = stripe.Webhook.construct_event(
                payload, 
                sig_header, 
                webhook_secret
            )
        else:
            # In development without webhook secret, parse JSON directly
            # WARNING: This skips signature verification - only use in development!
            import json
            event = json.loads(payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid payload: {str(e)}")
    except stripe.error.SignatureVerificationError as e:
        raise HTTPException(status_code=400, detail=f"Invalid signature: {str(e)}")
    # Handle the event
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        
        # Get appointment_id from metadata
        appointment_id = int(session['metadata'].get('appointment_id'))
        
        # Get appointment
        appointment = db.query(Appointment).filter(
            Appointment.id == appointment_id
        ).first()
        
        if not appointment:
            raise HTTPException(status_code=404, detail="Appointment not found")
        
        # Get payment
        payment = db.query(Payment).filter(
            Payment.appointment_id == appointment_id
        ).first()
        
        if not payment:
            # Create payment if it doesn't exist
            from models.doctor import Doctor
            doctor = appointment.doctor
            payment = Payment(
                appointment_id=appointment_id,
                amount=Decimal(str(doctor.opd_fees)),
                currency="INR",
                status=PaymentStatus.PENDING,
                stripe_id=session['id']
            )
            db.add(payment)
        
        # Update payment status
        payment.status = PaymentStatus.SUCCESS
        payment.stripe_id = session['payment_intent'] if 'payment_intent' in session else session['id']
        
        # Update appointment status to PAID
        appointment.status = AppointmentStatus.PAID
        
        # Update slot status (keep it as BOOKED since appointment is confirmed)
        slot = appointment.slot
        if slot:
            # Slot remains BOOKED for confirmed appointments
            pass
        
        db.commit()
        
        return {"status": "success", "message": "Payment processed successfully"}
    
    elif event['type'] == 'payment_intent.payment_failed':
        payment_intent = event['data']['object']
        
        # Try to find payment by stripe_id
        payment = db.query(Payment).filter(
            Payment.stripe_id == payment_intent['id']
        ).first()
        
        if payment:
            payment.status = PaymentStatus.FAILED
            db.commit()
        
        return {"status": "failed", "message": "Payment failed"}
    
    else:
        # Unhandled event type
        return {"status": "unhandled", "type": event['type']}


# ─────────────────────────────────────────────────────────────
# ✅ VERIFY PAYMENT STATUS (For frontend to check after redirect)
# ─────────────────────────────────────────────────────────────
@router.get("/payment/verify")
async def verify_payment(
    appointment_id: int = Query(..., description="Appointment ID"),
    session_id: Optional[str] = Query(None, description="Stripe session ID"),
    token: Optional[str] = Query(None, description="Access token from email"),
    request: Request = None,
    db: Session = Depends(get_db)
):
    """
    Verify payment status after Stripe redirect.
    """
    
    # Authenticate user (from token or bearer)
    current_user = await get_user_from_token_or_bearer(request, token, db)
    
    # Verify patient role
    if current_user.get("role") != "PATIENT":
        raise HTTPException(status_code=403, detail="Only patients can verify payments")
    
    # Get patient
    patient = db.query(Patient).filter(
        Patient.user_id == current_user["user_id"]
    ).first()
    
    if not patient:
        raise HTTPException(status_code=404, detail="Patient profile not found")
    
    # Get appointment
    appointment = db.query(Appointment).filter(
        Appointment.id == appointment_id,
        Appointment.patient_id == patient.id
    ).first()
    
    if not appointment:
        raise HTTPException(status_code=404, detail="Appointment not found")
    
    # Get payment
    payment = db.query(Payment).filter(
        Payment.appointment_id == appointment_id
    ).first()
    
    if not payment:
        return {
            "paid": False,
            "status": "no_payment_found",
            "appointment_status": appointment.status.value
        }
    
    # Verify with Stripe if session_id provided
    if session_id:
        try:
            session = stripe.checkout.Session.retrieve(session_id)
            if session.payment_status == 'paid':
                # Update payment and appointment if not already updated
                if payment.status != PaymentStatus.SUCCESS:
                    payment.status = PaymentStatus.SUCCESS
                    appointment.status = AppointmentStatus.PAID
                    db.commit()
                
                return {
                    "paid": True,
                    "status": "success",
                    "appointment_status": appointment.status.value,
                    "payment_status": payment.status.value
                }
        except stripe.error.StripeError as e:
            return {
                "paid": False,
                "status": "stripe_error",
                "error": str(e)
            }
    
    # Return current status
    return {
        "paid": payment.status == PaymentStatus.SUCCESS,
        "status": payment.status.value,
        "appointment_status": appointment.status.value
    }

