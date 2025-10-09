# core/email_service.py
"""
Simple email service for sending appointment notifications and authentication codes
"""
from django.core.mail import send_mail, EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings
from django.utils.html import strip_tags
import logging

logger = logging.getLogger(__name__)


class EmailService:
    """Simple email service wrapper"""
    
    @staticmethod
    def send_appointment_approved_email(appointment):
        """Send email when appointment is approved/confirmed"""
        try:
            logger.info(f"Attempting to send approval email from {settings.DEFAULT_FROM_EMAIL} to {appointment.patient_email}")
            logger.info(f"SMTP Config - Host: {settings.EMAIL_HOST}, Port: {settings.EMAIL_PORT}, User: {settings.EMAIL_HOST_USER}")
            
            subject = 'Appointment Confirmed'
            
            context = {
                'patient_name': appointment.patient_name,
                'appointment_date': appointment.appointment_date.strftime('%B %d, %Y'),
                'period': appointment.get_period_display(),
                'service': appointment.service.name,
                'dentist': appointment.assigned_dentist.get_full_name() if appointment.assigned_dentist else 'To be assigned',
                'clinic_name': settings.DEFAULT_FROM_NAME,
            }
            
            html_message = render_to_string('emails/appointment_approved.html', context)
            plain_message = strip_tags(html_message)
            
            send_mail(
                subject=subject,
                message=plain_message,
                from_email=f"{settings.DEFAULT_FROM_NAME} <{settings.DEFAULT_FROM_EMAIL}>",
                recipient_list=[appointment.patient_email],
                html_message=html_message,
                fail_silently=False,
            )
            
            logger.info(f"Approval email sent successfully to {appointment.patient_email} for appointment {appointment.id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send approval email for appointment {appointment.id}: {str(e)}", exc_info=True)
            return False
    
    @staticmethod
    def send_appointment_rejected_email(appointment):
        """Send email when appointment is rejected"""
        try:
            logger.info(f"Attempting to send rejection email from {settings.DEFAULT_FROM_EMAIL} to {appointment.patient_email}")
            
            subject = 'Appointment Request Update'
            
            context = {
                'patient_name': appointment.patient_name,
                'appointment_date': appointment.appointment_date.strftime('%B %d, %Y'),
                'period': appointment.get_period_display(),
                'service': appointment.service.name,
                'clinic_name': settings.DEFAULT_FROM_NAME,
            }
            
            html_message = render_to_string('emails/appointment_rejected.html', context)
            plain_message = strip_tags(html_message)
            
            send_mail(
                subject=subject,
                message=plain_message,
                from_email=f"{settings.DEFAULT_FROM_NAME} <{settings.DEFAULT_FROM_EMAIL}>",
                recipient_list=[appointment.patient_email],
                html_message=html_message,
                fail_silently=False,
            )
            
            logger.info(f"Rejection email sent successfully to {appointment.patient_email} for appointment {appointment.id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send rejection email for appointment {appointment.id}: {str(e)}", exc_info=True)
            return False
    
    @staticmethod
    def send_appointment_cancelled_email(appointment, cancelled_by_patient=False):
        """Send email when appointment is cancelled"""
        try:
            logger.info(f"Attempting to send cancellation email from {settings.DEFAULT_FROM_EMAIL} to {appointment.patient_email}")
            
            subject = 'Appointment Cancelled'
            
            context = {
                'patient_name': appointment.patient_name,
                'appointment_date': appointment.appointment_date.strftime('%B %d, %Y'),
                'period': appointment.get_period_display(),
                'service': appointment.service.name,
                'cancelled_by_patient': cancelled_by_patient,
                'clinic_name': settings.DEFAULT_FROM_NAME,
            }
            
            html_message = render_to_string('emails/appointment_cancelled.html', context)
            plain_message = strip_tags(html_message)
            
            send_mail(
                subject=subject,
                message=plain_message,
                from_email=f"{settings.DEFAULT_FROM_NAME} <{settings.DEFAULT_FROM_EMAIL}>",
                recipient_list=[appointment.patient_email],
                html_message=html_message,
                fail_silently=False,
            )
            
            logger.info(f"Cancellation email sent successfully to {appointment.patient_email} for appointment {appointment.id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send cancellation email for appointment {appointment.id}: {str(e)}", exc_info=True)
            return False
    
    @staticmethod
    def send_verification_code_email(email, code, patient_name=None):
        """Send verification code for patient portal access"""
        print("=" * 80)
        print("ATTEMPTING TO SEND EMAIL")
        print(f"From: {settings.DEFAULT_FROM_EMAIL}")
        print(f"To: {email}")
        print(f"SMTP Host: {settings.EMAIL_HOST}")
        print(f"SMTP Port: {settings.EMAIL_PORT}")
        print(f"SMTP User: {settings.EMAIL_HOST_USER}")
        print(f"SMTP Password length: {len(settings.EMAIL_HOST_PASSWORD)}")
        print("=" * 80)
        print(f"SMTP Password (first 20 chars): {settings.EMAIL_HOST_PASSWORD[:20]}")
        print(f"SMTP Password (last 20 chars): {settings.EMAIL_HOST_PASSWORD[-20:]}")
        try:
            subject = 'Your Patient Portal Access Code'
            
            context = {
                'patient_name': patient_name or 'Patient',
                'code': code,
                'expiry_minutes': 15,
                'clinic_name': settings.DEFAULT_FROM_NAME,
            }
            
            html_message = render_to_string('emails/verification_code.html', context)
            plain_message = strip_tags(html_message)
            
            print("Email content prepared successfully")
            print(f"Subject: {subject}")
            
            send_mail(
                subject=subject,
                message=plain_message,
                from_email=f"{settings.DEFAULT_FROM_NAME} <{settings.DEFAULT_FROM_EMAIL}>",
                recipient_list=[email],
                html_message=html_message,
                fail_silently=False,
            )
            
            print("✓ EMAIL SENT SUCCESSFULLY!")
            print("=" * 80)
            return True
            
        except Exception as e:
            print("=" * 80)
            print("✗ EMAIL SENDING FAILED!")
            print(f"Error type: {type(e).__name__}")
            print(f"Error message: {str(e)}")
            print("=" * 80)
            import traceback
            traceback.print_exc()
            return False