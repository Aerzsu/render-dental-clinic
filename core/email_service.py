"""
Email service using Brevo API (works on free hosting, no SMTP port issues)
"""
from django.template.loader import render_to_string
from django.conf import settings
from django.utils.html import strip_tags
from core.models import SystemSetting
import logging
import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException

logger = logging.getLogger(__name__)


def send_email_via_api(recipient_email, subject, html_content, recipient_name=None):
    """
    Send email using Brevo API instead of SMTP
    This avoids port blocking issues on free hosting tiers
    """
    try:
        logger.info(f"Attempting to send email via Brevo API")
        logger.info(f"From: {settings.DEFAULT_FROM_EMAIL}, To: {recipient_email}")
        
        # Configure Brevo API
        configuration = sib_api_v3_sdk.Configuration()
        configuration.api_key['api-key'] = settings.BREVO_API_KEY
        
        api_instance = sib_api_v3_sdk.TransactionalEmailsApi(
            sib_api_v3_sdk.ApiClient(configuration)
        )
        
        # Prepare sender
        sender = {
            "name": settings.DEFAULT_FROM_NAME,
            "email": settings.DEFAULT_FROM_EMAIL
        }
        
        # Prepare recipient
        to = [{"email": recipient_email}]
        if recipient_name:
            to[0]["name"] = recipient_name
        
        # Create email object
        send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(
            to=to,
            sender=sender,
            subject=subject,
            html_content=html_content
        )
        
        # Send email via API
        api_response = api_instance.send_transac_email(send_smtp_email)
        
        logger.info(f"✅ Email sent successfully via Brevo API!")
        logger.info(f"Message ID: {api_response.message_id}")
        return True
        
    except ApiException as e:
        logger.error(f"❌ Brevo API error: {e}")
        logger.error(f"Response body: {e.body if hasattr(e, 'body') else 'No body'}")
        return False
        
    except Exception as e:
        logger.error(f"❌ Failed to send email: {str(e)}")
        logger.exception("Full traceback:")
        return False


class EmailService:
    """Email service wrapper using Brevo API"""
    
    @staticmethod
    def send_appointment_approved_email(appointment):
        """Send email when appointment is approved/confirmed"""
        try:
            logger.info(f"Preparing approval email for appointment {appointment.id}")
            
            subject = 'Appointment Confirmed'
            
            # Build cancellation URL - handles both development and production
            if settings.DEBUG:
                # Development mode
                domain = 'localhost:8000'
                protocol = 'http'
            else:
                # Production mode - use ALLOWED_HOSTS
                domain = settings.ALLOWED_HOSTS[0] if settings.ALLOWED_HOSTS else 'kingjoy-dental-clinic.onrender.com'
                protocol = 'https'

            cancel_url = f"{protocol}://{domain}/appointments/cancel/{appointment.reschedule_token}/"

            context = {
                'patient_name': appointment.patient_name,
                'appointment_date': appointment.appointment_date.strftime('%B %d, %Y'),
                'period': appointment.time_display,  # FIXED: Use time_display instead of period
                'service': appointment.service.name,
                'dentist': appointment.assigned_dentist.get_full_name() if appointment.assigned_dentist else 'To be assigned',
                'clinic_name': settings.DEFAULT_FROM_NAME,
                'cancel_url': cancel_url,
            }
            
            # Render HTML email
            html_message = render_to_string('emails/appointment_approved.html', context)
            
            # Send via API
            success = send_email_via_api(
                recipient_email=appointment.patient_email,
                subject=subject,
                html_content=html_message,
                recipient_name=appointment.patient_name
            )
            
            if success:
                logger.info(f"Approval email sent successfully for appointment {appointment.id}")
            else:
                logger.error(f"Failed to send approval email for appointment {appointment.id}")
            
            return success
            
        except Exception as e:
            logger.error(f"Error preparing approval email for appointment {appointment.id}: {str(e)}")
            logger.exception("Full traceback:")
            return False
    
    @staticmethod
    def send_appointment_rejected_email(appointment):
        """Send email when appointment is rejected"""
        try:
            logger.info(f"Preparing rejection email for appointment {appointment.id}")
            
            subject = 'Appointment Request Update'
            
            context = {
                'patient_name': appointment.patient_name,
                'appointment_date': appointment.appointment_date.strftime('%B %d, %Y'),
                'period': appointment.time_display,  # FIXED: Use time_display instead of period
                'service': appointment.service.name,
                'clinic_name': settings.DEFAULT_FROM_NAME,
            }
            
            html_message = render_to_string('emails/appointment_rejected.html', context)
            
            success = send_email_via_api(
                recipient_email=appointment.patient_email,
                subject=subject,
                html_content=html_message,
                recipient_name=appointment.patient_name
            )
            
            if success:
                logger.info(f"Rejection email sent successfully for appointment {appointment.id}")
            else:
                logger.error(f"Failed to send rejection email for appointment {appointment.id}")
            
            return success
            
        except Exception as e:
            logger.error(f"Error preparing rejection email for appointment {appointment.id}: {str(e)}")
            logger.exception("Full traceback:")
            return False
    
    @staticmethod
    def send_appointment_cancelled_email(appointment, cancelled_by_patient=False):
        """Send email when appointment is cancelled"""
        try:
            logger.info(f"Preparing cancellation email for appointment {appointment.id}")
            
            subject = 'Appointment Cancelled'
            
            context = {
                'patient_name': appointment.patient_name,
                'appointment_date': appointment.appointment_date.strftime('%B %d, %Y'),
                'period': appointment.time_display,  # FIXED: Use time_display instead of period
                'service': appointment.service.name,
                'cancelled_by_patient': cancelled_by_patient,
                'clinic_name': settings.DEFAULT_FROM_NAME,
            }
            
            html_message = render_to_string('emails/appointment_cancelled.html', context)
            
            success = send_email_via_api(
                recipient_email=appointment.patient_email,
                subject=subject,
                html_content=html_message,
                recipient_name=appointment.patient_name
            )
            
            if success:
                logger.info(f"Cancellation email sent successfully for appointment {appointment.id}")
            else:
                logger.error(f"Failed to send cancellation email for appointment {appointment.id}")
            
            return success
            
        except Exception as e:
            logger.error(f"Error preparing cancellation email for appointment {appointment.id}: {str(e)}")
            logger.exception("Full traceback:")
            return False
    
    @staticmethod
    def send_verification_code_email(email, code, patient_name=None):
        """Send verification code for patient portal access"""
        try:
            logger.info("=" * 80)
            logger.info("ATTEMPTING TO SEND VERIFICATION CODE VIA BREVO API")
            logger.info(f"From: {settings.DEFAULT_FROM_EMAIL}")
            logger.info(f"To: {email}")
            logger.info(f"Code: {code}")
            logger.info("=" * 80)
            
            subject = 'Your Patient Portal Access Code'
            
            context = {
                'patient_name': patient_name or 'Patient',
                'code': code,
                'expiry_minutes': 15,
                'clinic_name': settings.DEFAULT_FROM_NAME,
            }
            
            html_message = render_to_string('emails/verification_code.html', context)
            
            logger.info("Email content prepared successfully")
            logger.info(f"Subject: {subject}")
            
            success = send_email_via_api(
                recipient_email=email,
                subject=subject,
                html_content=html_message,
                recipient_name=patient_name
            )
            
            if success:
                logger.info("✓ VERIFICATION CODE EMAIL SENT SUCCESSFULLY!")
            else:
                logger.error("✗ VERIFICATION CODE EMAIL FAILED!")
            
            logger.info("=" * 80)
            return success
            
        except Exception as e:
            logger.error("=" * 80)
            logger.error("✗ EMAIL SENDING FAILED!")
            logger.error(f"Error type: {type(e).__name__}")
            logger.error(f"Error message: {str(e)}")
            logger.error("=" * 80)
            logger.exception("Full traceback:")
            return False
        
    def send_invoice_email(self, payment, transaction):
        """
        Send invoice and receipt email to patient after first payment
        
        Args:
            payment: Payment instance
            transaction: PaymentTransaction instance (the payment just received)
        """
        if not payment.patient.email:
            print(f"Cannot send invoice - patient {payment.patient.full_name} has no email")
            return False
        
        try:
            subject = f"Invoice & Receipt - {payment.appointment.service.name}"
            
            # Email context
            context = {
                'patient_name': payment.patient.first_name,
                'invoice_number': f"{payment.id:06d}",
                'appointment_date': payment.appointment.appointment_date.strftime('%B %d, %Y'),
                'service_name': payment.appointment.service.name,
                'total_amount': f"₱{payment.total_amount:,.2f}",
                'amount_paid': f"₱{transaction.amount:,.2f}",
                'outstanding_balance': f"₱{payment.outstanding_balance:,.2f}",
                'receipt_number': transaction.receipt_number,
                'payment_date': transaction.payment_date.strftime('%B %d, %Y'),
                'is_fully_paid': payment.is_fully_paid,
                'next_due_date': payment.next_due_date.strftime('%B %d, %Y') if payment.next_due_date else None,
                'clinic_name': 'KingJoy Dental Clinic',
                'portal_url': 'https://yoursite.com/patient-portal/',  # Update with actual URL
            }
            
            # Render email template
            html_content = render_to_string('emails/invoice_receipt.html', context)
            
            # Send email
            success = send_email_via_api(
                to_email=payment.patient.email,
                to_name=payment.patient.full_name,
                subject=subject,
                html_content=html_content
            )
            
            if success:
                # Mark invoice as sent
                payment.mark_invoice_sent()
                print(f"Invoice email sent to {payment.patient.email}")
                return True
            else:
                print(f"Failed to send invoice email to {payment.patient.email}")
                return False
                
        except Exception as e:
            print(f"Error sending invoice email: {str(e)}")
            return False