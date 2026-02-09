import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
from core.config import settings
from services.security import create_access_token


class EmailService:
    """Service for sending email notifications"""
    
    # Configure these in your .env file
    SMTP_SERVER = settings.SMTP_SERVER
    SMTP_PORT = settings.SMTP_PORT
    SMTP_USERNAME = settings.SMTP_USERNAME
    SMTP_PASSWORD = settings.SMTP_PASSWORD
    
    @staticmethod
    async def send_email(
        to_email: str,
        subject: str,
        html_content: str
    ) -> bool:
        """
        Send HTML email
        
        Args:
            to_email: Recipient email
            subject: Email subject
            html_content: HTML content
            
        Returns:
            True if sent successfully, False otherwise
        """
        try:
            # Create message
            msg = MIMEMultipart('alternative')
            msg['From'] = EmailService.SMTP_USERNAME
            msg['To'] = to_email
            msg['Subject'] = subject
            
            # Attach HTML content
            html_part = MIMEText(html_content, 'html')
            msg.attach(html_part)
            
            # Send email
            with smtplib.SMTP(EmailService.SMTP_SERVER, EmailService.SMTP_PORT) as server:
                server.starttls()
                server.login(EmailService.SMTP_USERNAME, EmailService.SMTP_PASSWORD)
                server.send_message(msg)
            
            return True
            
        except Exception as e:
            print(f"Email sending error: {str(e)}")
            return False
    
    @staticmethod
    async def send_appointment_request_to_doctor(
        doctor_email: str,
        doctor_name: str,
        patient_name: str,
        patient_age: int,
        patient_contact: str,
        appointment_id: int,
        slot_date: str,
        slot_time: str,
        report_url: Optional[str],
        expiry_time: str,
        doctor_user_id: int,
        doctor_role: str,
        doctor_device_id: int
    ) -> bool:
        """
        Send appointment request email to doctor with 24-hour approval window
        
        Args:
            doctor_email: Doctor's email
            doctor_name: Doctor's name
            patient_name: Patient's name
            patient_age: Patient's age
            patient_contact: Patient's contact
            appointment_id: Appointment ID
            slot_date: Formatted slot date
            slot_time: Formatted slot time
            report_url: Cloudinary URL of medical report (optional)
            expiry_time: Formatted expiry time (24 hours from now)
        """
        
        # Generate access token for doctor (valid for 7 days for email links)
        doctor_token = create_access_token(
            data={
                "user_id": doctor_user_id,
                "email": doctor_email,
                "role": doctor_role,
                "device_id": doctor_device_id
            },
            expires_minutes=7 * 24 * 60  # 7 days
        )
        
        # Create approval/rejection links with token
        frontend_url = settings.FRONTEND_URL
        approve_link = f"{frontend_url}/doctor/appointments/{appointment_id}/approve?token={doctor_token}"
        reject_link = f"{frontend_url}/doctor/appointments/{appointment_id}/reject?token={doctor_token}"
        view_report_link = report_url if report_url else None
        
        subject = f"New Appointment Request from {patient_name}"
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    line-height: 1.6;
                    color: #333;
                }}
                .container {{
                    max-width: 600px;
                    margin: 0 auto;
                    padding: 20px;
                    background-color: #f9fafb;
                }}
                .header {{
                    background: linear-gradient(135deg, #0f172a 0%, #334155 100%);
                    color: white;
                    padding: 30px;
                    border-radius: 10px 10px 0 0;
                    text-align: center;
                }}
                .content {{
                    background-color: white;
                    padding: 30px;
                    border-radius: 0 0 10px 10px;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                }}
                .info-box {{
                    background-color: #f1f5f9;
                    padding: 20px;
                    border-radius: 8px;
                    margin: 20px 0;
                    border-left: 4px solid #0f172a;
                }}
                .info-row {{
                    display: flex;
                    padding: 8px 0;
                    border-bottom: 1px solid #e2e8f0;
                }}
                .info-row:last-child {{
                    border-bottom: none;
                }}
                .info-label {{
                    font-weight: bold;
                    color: #475569;
                    min-width: 140px;
                }}
                .info-value {{
                    color: #0f172a;
                }}
                .button-container {{
                    text-align: center;
                    margin: 30px 0;
                }}
                .button {{
                    display: inline-block;
                    padding: 14px 28px;
                    margin: 0 10px;
                    text-decoration: none;
                    border-radius: 8px;
                    font-weight: bold;
                    font-size: 16px;
                    transition: all 0.3s;
                }}
                .button-approve {{
                    background-color: #10b981;
                    color: white;
                }}
                .button-approve:hover {{
                    background-color: #059669;
                }}
                .button-reject {{
                    background-color: #ef4444;
                    color: white;
                }}
                .button-reject:hover {{
                    background-color: #dc2626;
                }}
                .button-view {{
                    background-color: #3b82f6;
                    color: white;
                }}
                .button-view:hover {{
                    background-color: #2563eb;
                }}
                .warning {{
                    background-color: #fef3c7;
                    border-left: 4px solid #f59e0b;
                    padding: 15px;
                    border-radius: 8px;
                    margin: 20px 0;
                }}
                .footer {{
                    text-align: center;
                    color: #64748b;
                    font-size: 14px;
                    margin-top: 30px;
                    padding-top: 20px;
                    border-top: 1px solid #e2e8f0;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1 style="margin: 0;">🏥 New Appointment Request</h1>
                </div>
                
                <div class="content">
                    <p>Dear Dr. {doctor_name},</p>
                    
                    <p>You have received a new appointment request from <strong>{patient_name}</strong>.</p>
                    
                    <div class="info-box">
                        <h3 style="margin-top: 0; color: #0f172a;">📋 Patient Details</h3>
                        <div class="info-row">
                            <span class="info-label">Name:</span>
                            <span class="info-value">{patient_name}</span>
                        </div>
                        <div class="info-row">
                            <span class="info-label">Age:</span>
                            <span class="info-value">{patient_age} years</span>
                        </div>
                        <div class="info-row">
                            <span class="info-label">Contact:</span>
                            <span class="info-value">{patient_contact}</span>
                        </div>
                    </div>
                    
                    <div class="info-box">
                        <h3 style="margin-top: 0; color: #0f172a;">📅 Appointment Details</h3>
                        <div class="info-row">
                            <span class="info-label">Date:</span>
                            <span class="info-value">{slot_date}</span>
                        </div>
                        <div class="info-row">
                            <span class="info-label">Time:</span>
                            <span class="info-value">{slot_time}</span>
                        </div>
                        <div class="info-row">
                            <span class="info-label">Appointment ID:</span>
                            <span class="info-value">#{appointment_id}</span>
                        </div>
                    </div>
                    
                    {f'''
                    <div class="button-container">
                        <a href="{view_report_link}" class="button button-view">📄 View Medical Report</a>
                    </div>
                    ''' if view_report_link else ''}
                    
                    <div class="warning">
                        <strong>⏰ Action Required:</strong> Please review and respond to this appointment request before <strong>{expiry_time}</strong>. If no action is taken, the request will be automatically cancelled and the slot will be released.
                    </div>
                    
                    <div class="button-container">
                        <a href="{approve_link}" class="button button-approve">✅ Approve Appointment</a>
                        <a href="{reject_link}" class="button button-reject">❌ Reject Appointment</a>
                    </div>
                    
                    <div class="footer">
                        <p>This is an automated message from Healthcare Appointment System</p>
                        <p>© 2026 Healthcare Platform. All rights reserved.</p>
                    </div>
                </div>
            </div>
        </body>
        </html>
        """
        
        return await EmailService.send_email(doctor_email, subject, html_content)
    
    @staticmethod
    async def send_appointment_cancellation_to_doctor(
        doctor_email: str,
        doctor_name: str,
        patient_name: str,
        appointment_id: int,
        slot_date: str,
        slot_time: str
    ) -> bool:
        """Send appointment cancellation notification to doctor"""
        
        subject = f"Appointment Cancelled - {patient_name}"
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    line-height: 1.6;
                    color: #333;
                }}
                .container {{
                    max-width: 600px;
                    margin: 0 auto;
                    padding: 20px;
                    background-color: #f9fafb;
                }}
                .header {{
                    background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%);
                    color: white;
                    padding: 30px;
                    border-radius: 10px 10px 0 0;
                    text-align: center;
                }}
                .content {{
                    background-color: white;
                    padding: 30px;
                    border-radius: 0 0 10px 10px;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                }}
                .info-box {{
                    background-color: #fee2e2;
                    padding: 20px;
                    border-radius: 8px;
                    margin: 20px 0;
                    border-left: 4px solid #ef4444;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1 style="margin: 0;">🚫 Appointment Cancelled</h1>
                </div>
                
                <div class="content">
                    <p>Dear Dr. {doctor_name},</p>
                    
                    <p>The patient <strong>{patient_name}</strong> has cancelled their appointment.</p>
                    
                    <div class="info-box">
                        <h3 style="margin-top: 0;">Cancelled Appointment Details</h3>
                        <p><strong>Appointment ID:</strong> #{appointment_id}</p>
                        <p><strong>Date:</strong> {slot_date}</p>
                        <p><strong>Time:</strong> {slot_time}</p>
                        <p><strong>Patient:</strong> {patient_name}</p>
                    </div>
                    
                    <p>The time slot has been freed and is now available for other patients to book.</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        return await EmailService.send_email(doctor_email, subject, html_content)
    
    @staticmethod
    async def send_approval_confirmation_to_patient(
        patient_email: str,
        patient_name: str,
        doctor_name: str,
        appointment_id: int,
        slot_date: str,
        slot_time: str,
        opd_fees: float,
        payment_expiry: str,
        patient_user_id: int,
        patient_role: str,
        patient_device_id: int
    ) -> bool:
        """
        Send appointment approval confirmation to patient with payment link.
        Includes 15-minute payment deadline.
        """
        
        subject = f"✅ Appointment Approved - Dr. {doctor_name}"
        
        # Generate access token for patient (valid for 7 days for email links)
        patient_token = create_access_token(
            data={
                "user_id": patient_user_id,
                "email": patient_email,
                "role": patient_role,
                "device_id": patient_device_id
            },
            expires_minutes=7 * 24 * 60  # 7 days
        )
        
        payment_link = f"{settings.FRONTEND_URL}/patient/payment?appointment_id={appointment_id}&token={patient_token}"
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    line-height: 1.6;
                    color: #333;
                }}
                .container {{
                    max-width: 600px;
                    margin: 0 auto;
                    padding: 20px;
                    background-color: #f9fafb;
                }}
                .header {{
                    background: linear-gradient(135deg, #10b981 0%, #059669 100%);
                    color: white;
                    padding: 30px;
                    border-radius: 10px 10px 0 0;
                    text-align: center;
                }}
                .content {{
                    background-color: white;
                    padding: 30px;
                    border-radius: 0 0 10px 10px;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                }}
                .success-box {{
                    background-color: #d1fae5;
                    padding: 20px;
                    border-radius: 8px;
                    margin: 20px 0;
                    border-left: 4px solid #10b981;
                }}
                .urgent-box {{
                    background-color: #fef3c7;
                    border-left: 4px solid #f59e0b;
                    padding: 20px;
                    border-radius: 8px;
                    margin: 20px 0;
                    text-align: center;
                }}
                .button {{
                    display: inline-block;
                    padding: 16px 32px;
                    background-color: #10b981;
                    color: white;
                    text-decoration: none;
                    border-radius: 8px;
                    font-weight: bold;
                    font-size: 18px;
                    margin: 20px 0;
                    transition: all 0.3s;
                }}
                .button:hover {{
                    background-color: #059669;
                    transform: translateY(-2px);
                    box-shadow: 0 4px 8px rgba(0,0,0,0.2);
                }}
                .timer {{
                    font-size: 24px;
                    color: #f59e0b;
                    font-weight: bold;
                    margin: 15px 0;
                }}
                .fee {{
                    font-size: 32px;
                    color: #0f172a;
                    font-weight: bold;
                    margin: 10px 0;
                }}
                .footer {{
                    text-align: center;
                    color: #64748b;
                    font-size: 14px;
                    margin-top: 30px;
                    padding-top: 20px;
                    border-top: 1px solid #e2e8f0;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1 style="margin: 0;">✅ Appointment Approved!</h1>
                </div>
                
                <div class="content">
                    <p>Dear {patient_name},</p>
                    
                    <p style="font-size: 18px;">Great news! <strong>Dr. {doctor_name}</strong> has approved your appointment request.</p>
                    
                    <div class="success-box">
                        <h3 style="margin-top: 0; color: #0f172a;">📅 Appointment Details</h3>
                        <p style="margin: 8px 0;"><strong>Doctor:</strong> Dr. {doctor_name}</p>
                        <p style="margin: 8px 0;"><strong>Date:</strong> {slot_date}</p>
                        <p style="margin: 8px 0;"><strong>Time:</strong> {slot_time}</p>
                        <p style="margin: 8px 0;"><strong>Appointment ID:</strong> #{appointment_id}</p>
                    </div>
                    
                    <div style="text-align: center; margin: 30px 0;">
                        <p style="color: #64748b; margin: 5px 0;">Consultation Fee</p>
                        <div class="fee">₹{opd_fees}</div>
                    </div>
                    
                    <div class="urgent-box">
                        <h3 style="margin: 0 0 10px 0; color: #f59e0b;">⏰ URGENT: Complete Payment Now!</h3>
                        <p style="margin: 10px 0;">You have <strong>15 MINUTES</strong> to complete the payment</p>
                        <div class="timer">Payment Deadline: {payment_expiry}</div>
                        <p style="color: #dc2626; font-weight: bold; margin: 15px 0;">
                            ⚠️ If payment is not completed within 15 minutes, your appointment will be automatically cancelled.
                        </p>
                    </div>
                    
                    <div style="text-align: center; margin: 30px 0;">
                        <a href="{payment_link}" class="button">💳 PAY NOW - ₹{opd_fees}</a>
                    </div>
                    
                    <div style="background-color: #f1f5f9; padding: 15px; border-radius: 8px; margin: 20px 0;">
                        <p style="margin: 5px 0; font-size: 14px; color: #475569;">
                            <strong>Important:</strong> After successful payment, your appointment will be confirmed and you'll receive a confirmation email with all details.
                        </p>
                    </div>
                    
                    <div class="footer">
                        <p>This is an automated message from Healthcare Appointment System</p>
                        <p>Need help? Contact our support team</p>
                        <p>© 2026 Healthcare Platform. All rights reserved.</p>
                    </div>
                </div>
            </div>
        </body>
        </html>
        """
        
        return await EmailService.send_email(patient_email, subject, html_content)
    
    @staticmethod
    async def send_rejection_notification_to_patient(
        patient_email: str,
        patient_name: str,
        doctor_name: str,
        slot_date: str,
        slot_time: str,
        rejection_reason: Optional[str]
    ) -> bool:
        """Send appointment rejection notification to patient"""
        
        subject = f"Appointment Request Update - Dr. {doctor_name}"
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    line-height: 1.6;
                    color: #333;
                }}
                .container {{
                    max-width: 600px;
                    margin: 0 auto;
                    padding: 20px;
                    background-color: #f9fafb;
                }}
                .header {{
                    background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%);
                    color: white;
                    padding: 30px;
                    border-radius: 10px 10px 0 0;
                    text-align: center;
                }}
                .content {{
                    background-color: white;
                    padding: 30px;
                    border-radius: 0 0 10px 10px;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1 style="margin: 0;">📋 Appointment Update</h1>
                </div>
                
                <div class="content">
                    <p>Dear {patient_name},</p>
                    
                    <p>We regret to inform you that Dr. {doctor_name} is unable to accept your appointment request for {slot_date} at {slot_time}.</p>
                    
                    {f'<p><strong>Reason:</strong> {rejection_reason}</p>' if rejection_reason else ''}
                    
                    <p>Please feel free to book another available slot or consult with another doctor.</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        return await EmailService.send_email(patient_email, subject, html_content)
    @staticmethod
    async def send_password_reset_email(
        user_email: str,
        reset_token: str,
        user_name: str = "User",
        expiry_minutes: int = 15
    ) -> bool:
        """
        Send password reset email with secure token link
        
        Args:
            user_email: User's email address
            reset_token: Secure reset token
            user_name: User's name (optional, defaults to "User")
            expiry_minutes: Token expiry time in minutes (default: 15)
            
        Returns:
            True if sent successfully, False otherwise
        """
        frontend_url = settings.FRONTEND_URL
        reset_link = f"{frontend_url}/reset-password?token={reset_token}"
        
        subject = "Password Reset Request - Healthcare Platform"
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
                    line-height: 1.6;
                    color: #1e293b;
                    margin: 0;
                    padding: 0;
                    background-color: #f8fafc;
                }}
                .email-wrapper {{
                    max-width: 600px;
                    margin: 0 auto;
                    background-color: #ffffff;
                }}
                .header {{
                    background: linear-gradient(135deg, #0f172a 0%, #1e293b 50%, #334155 100%);
                    padding: 40px 30px;
                    text-align: center;
                    border-radius: 12px 12px 0 0;
                }}
                .header h1 {{
                    margin: 0;
                    color: #ffffff;
                    font-size: 28px;
                    font-weight: 700;
                    letter-spacing: -0.5px;
                }}
                .header-icon {{
                    font-size: 48px;
                    margin-bottom: 15px;
                }}
                .content {{
                    padding: 40px 30px;
                    background-color: #ffffff;
                }}
                .greeting {{
                    font-size: 18px;
                    color: #0f172a;
                    margin-bottom: 20px;
                    font-weight: 500;
                }}
                .message {{
                    font-size: 15px;
                    color: #475569;
                    margin-bottom: 25px;
                    line-height: 1.7;
                }}
                .security-notice {{
                    background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%);
                    border-left: 4px solid #f59e0b;
                    padding: 20px;
                    border-radius: 8px;
                    margin: 25px 0;
                }}
                .security-notice-title {{
                    color: #92400e;
                    font-weight: 700;
                    margin: 0 0 10px 0;
                    font-size: 16px;
                    display: flex;
                    align-items: center;
                    gap: 8px;
                }}
                .security-notice-text {{
                    color: #78350f;
                    margin: 0;
                    font-size: 14px;
                    line-height: 1.6;
                }}
                .expiry-info {{
                    background-color: #fee2e2;
                    border-left: 4px solid #ef4444;
                    padding: 15px;
                    border-radius: 8px;
                    margin: 20px 0;
                }}
                .expiry-info p {{
                    margin: 0;
                    color: #991b1b;
                    font-size: 14px;
                    font-weight: 600;
                }}
                .expiry-time {{
                    color: #dc2626;
                    font-weight: 700;
                    font-size: 18px;
                    margin-top: 5px;
                }}
                .button-container {{
                    text-align: center;
                    margin: 35px 0;
                }}
                .reset-button {{
                    display: inline-block;
                    padding: 16px 40px;
                    background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
                    color: #ffffff !important;
                    text-decoration: none;
                    border-radius: 10px;
                    font-weight: 700;
                    font-size: 16px;
                    letter-spacing: 0.5px;
                    box-shadow: 0 4px 14px rgba(15, 23, 42, 0.4);
                    transition: all 0.3s ease;
                }}
                .reset-button:hover {{
                    background: linear-gradient(135deg, #1e293b 0%, #334155 100%);
                    transform: translateY(-2px);
                    box-shadow: 0 6px 20px rgba(15, 23, 42, 0.5);
                }}
                .alternative-link {{
                    background-color: #f1f5f9;
                    padding: 20px;
                    border-radius: 8px;
                    margin: 25px 0;
                    border: 1px dashed #cbd5e1;
                }}
                .alternative-link p {{
                    margin: 0 0 10px 0;
                    color: #475569;
                    font-size: 13px;
                    font-weight: 600;
                }}
                .alternative-link a {{
                    color: #0f172a;
                    word-break: break-all;
                    font-size: 12px;
                    text-decoration: none;
                    font-family: monospace;
                    background-color: #ffffff;
                    padding: 8px;
                    border-radius: 4px;
                    display: block;
                    border: 1px solid #e2e8f0;
                }}
                .help-section {{
                    background-color: #eff6ff;
                    border-left: 4px solid #3b82f6;
                    padding: 20px;
                    border-radius: 8px;
                    margin: 25px 0;
                }}
                .help-section-title {{
                    color: #1e40af;
                    font-weight: 700;
                    margin: 0 0 10px 0;
                    font-size: 15px;
                }}
                .help-section ul {{
                    margin: 10px 0;
                    padding-left: 20px;
                    color: #1e40af;
                }}
                .help-section li {{
                    margin: 8px 0;
                    font-size: 14px;
                    line-height: 1.5;
                }}
                .divider {{
                    height: 1px;
                    background: linear-gradient(to right, transparent, #e2e8f0, transparent);
                    margin: 30px 0;
                }}
                .footer {{
                    background-color: #f8fafc;
                    padding: 30px;
                    text-align: center;
                    border-radius: 0 0 12px 12px;
                    border-top: 1px solid #e2e8f0;
                }}
                .footer p {{
                    margin: 8px 0;
                    color: #64748b;
                    font-size: 13px;
                }}
                .footer-brand {{
                    color: #0f172a;
                    font-weight: 700;
                    font-size: 14px;
                    margin-top: 15px;
                }}
                .warning-text {{
                    color: #dc2626;
                    font-weight: 600;
                    font-size: 14px;
                }}
            </style>
        </head>
        <body>
            <div class="email-wrapper">
                <div class="header">
                    <div class="header-icon">🔐</div>
                    <h1>Password Reset Request</h1>
                </div>
                
                <div class="content">
                    <p class="greeting">Hello {user_name},</p>
                    
                    <p class="message">
                        We received a request to reset the password for your Healthcare Platform account. 
                        If you made this request, click the button below to set a new password.
                    </p>
                    
                    <div class="expiry-info">
                        <p>⏰ This reset link will expire in:</p>
                        <p class="expiry-time">{expiry_minutes} minutes</p>
                    </div>
                    
                    <div class="button-container">
                        <a href="{reset_link}" class="reset-button">Reset My Password</a>
                    </div>
                    
                    <div class="alternative-link">
                        <p>If the button doesn't work, copy and paste this link into your browser:</p>
                        <a href="{reset_link}">{reset_link}</a>
                    </div>
                    
                    <div class="security-notice">
                        <p class="security-notice-title">
                            <span>⚠️</span>
                            <span>Security Notice</span>
                        </p>
                        <p class="security-notice-text">
                            <strong>Did not request a password reset?</strong><br>
                            If you didn't make this request, you can safely ignore this email. 
                            Your password will remain unchanged and your account is secure. 
                            However, you may want to change your password as a precaution.
                        </p>
                    </div>
                    
                    <div class="help-section">
                        <p class="help-section-title">🛡️ Security Best Practices:</p>
                        <ul>
                            <li>Never share your password with anyone</li>
                            <li>Use a strong, unique password for your account</li>
                            <li>Enable two-factor authentication if available</li>
                            <li>Be cautious of phishing emails asking for personal information</li>
                        </ul>
                    </div>
                    
                    <div class="divider"></div>
                    
                    <p class="message" style="margin-top: 25px;">
                        <span class="warning-text">Important:</span> This is an automated security email. 
                        For your protection, this link can only be used once and expires in {expiry_minutes} minutes.
                    </p>
                </div>
                
                <div class="footer">
                    <p>This email was sent to <strong>{user_email}</strong></p>
                    <p>If you need assistance, please contact our support team</p>
                    <p class="footer-brand">Healthcare Platform Security Team</p>
                    <p style="margin-top: 15px;">© 2026 Healthcare Platform. All rights reserved.</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        return await EmailService.send_email(user_email, subject, html_content)