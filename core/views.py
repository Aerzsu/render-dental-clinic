# core/views.py - Updated for AM/PM slot system
import json
from django.shortcuts import redirect
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.views.generic import TemplateView, ListView
from django.utils import timezone
from django.views.generic import FormView
from django.db.models import Q
from django.http import JsonResponse
from datetime import datetime
from django.db import transaction
from django.core.validators import validate_email
from django.core.exceptions import ValidationError as DjangoValidationError
from django.urls import reverse_lazy
import re
import pytz

from .models import AuditLog, SystemSetting
from appointments.models import Appointment, DailySlots, Payment, PaymentTransaction
from patients.models import Patient
from patient_portal.models import PatientPortalAccess
from services.models import Service
from users.models import User
from core.email_service import EmailService
from core.forms import SystemSettingsForm
import logging

logger = logging.getLogger(__name__)

class HomeView(TemplateView):
    """Public landing page"""
    template_name = 'core/home.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['services'] = Service.active.all()[:6]
        context['dentists'] = User.objects.filter(is_active_dentist=True)
        return context

class BookAppointmentView(TemplateView):
    """
    PUBLIC VIEW: Simplified appointment booking using AM/PM slots
    UPDATED: Now supports OTP verification for existing patients
    """
    template_name = 'core/book_appointment.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get services for booking form
        services = []
        for service in Service.active.all().order_by('name'):
            services.append({
                'id': service.id,
                'name': service.name,
                'duration_minutes': service.duration_minutes if hasattr(service, 'duration_minutes') else 30,
                'price_range': f"₱{service.min_price:,.0f} - ₱{service.max_price:,.0f}" if hasattr(service, 'min_price') else "Contact clinic for pricing",
                'description': service.description or "Professional dental service"
            })
        
        # Get period descriptions (configurable in future)
        am_period_display = SystemSetting.get_setting('am_period_display', '8:00 AM - 12:00 PM')
        pm_period_display = SystemSetting.get_setting('pm_period_display', '1:00 PM - 6:00 PM')
        
        context.update({
            'services_json': json.dumps(services),
            'am_period_display': am_period_display,
            'pm_period_display': pm_period_display,
        })
        
        return context
    
    def post(self, request, *args, **kwargs):
        """Handle appointment booking submission - UPDATED for OTP flow"""
        try:
            # Check if request is JSON
            if request.content_type == 'application/json':
                data = json.loads(request.body)
                return self._handle_json_request(data)
            else:
                return self._handle_form_request(request)
                
        except json.JSONDecodeError:
            return JsonResponse({'success': False, 'error': 'Invalid JSON data'}, status=400)
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f'Error in BookAppointmentView: {str(e)}', exc_info=True)
            
            return JsonResponse({
                'success': False, 
                'error': 'An unexpected error occurred. Please try again.'
            }, status=500)
    
    def _handle_json_request(self, data):
        """Handle JSON appointment request - UPDATED for OTP-verified patients"""
        # Validate required fields
        required_fields = ['patient_type', 'service', 'appointment_date', 'period']
        for field in required_fields:
            if not data.get(field):
                return JsonResponse({'success': False, 'error': f'{field} is required'}, status=400)
        
        # Validate terms agreement
        if not data.get('agreed_to_terms'):
            return JsonResponse({'success': False, 'error': 'You must agree to the terms and conditions'}, status=400)
        
        try:
            with transaction.atomic():
                # Get and validate service
                try:
                    service = Service.objects.get(id=data['service'], is_archived=False)
                except Service.DoesNotExist:
                    return JsonResponse({'success': False, 'error': 'Invalid service selected'}, status=400)
                
                # Parse and validate appointment date
                try:
                    appointment_date = datetime.strptime(data['appointment_date'], '%Y-%m-%d').date()
                except ValueError:
                    return JsonResponse({'success': False, 'error': 'Invalid date format'}, status=400)
                
                # Validate period
                period = data.get('period')
                if period not in ['AM', 'PM']:
                    return JsonResponse({'success': False, 'error': 'Invalid period. Must be AM or PM'}, status=400)
                
                # Validate appointment date/period constraints
                validation_error = self._validate_appointment_datetime(appointment_date, period)
                if validation_error:
                    return JsonResponse({'success': False, 'error': validation_error}, status=400)
                
                # Check slot availability
                can_book, availability_message = Appointment.can_book_appointment(appointment_date, period)
                if not can_book:
                    return JsonResponse({'success': False, 'error': availability_message}, status=400)
                
                # Handle patient data - UPDATED for OTP flow
                patient_data, patient_type = self._prepare_patient_data(data)
                if isinstance(patient_data, JsonResponse):  # Error response
                    return patient_data
                
                # Create appointment with temp patient data
                appointment = Appointment.objects.create(
                    patient=patient_data.get('existing_patient'),
                    service=service,
                    appointment_date=appointment_date,
                    period=period,
                    patient_type=patient_type,
                    reason=data.get('reason', '').strip(),
                    status='pending',
                    temp_first_name=patient_data.get('first_name', ''),
                    temp_last_name=patient_data.get('last_name', ''),
                    temp_email=patient_data.get('email', ''),
                    temp_contact_number=patient_data.get('contact_number', ''),
                    temp_address=patient_data.get('address', ''),
                )
                
                # Generate reference number
                reference_number = f'APT-{appointment.id:06d}'
                
                return JsonResponse({
                    'success': True,
                    'reference_number': reference_number,
                    'appointment_id': appointment.id,
                    'appointment_date': appointment_date.strftime('%Y-%m-%d'),
                    'period': period,
                    'period_display': 'Morning' if period == 'AM' else 'Afternoon',
                    'patient_name': appointment.patient_name
                })
                
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f'Error in _handle_json_request: {str(e)}', exc_info=True)
            
            return JsonResponse({
                'success': False, 
                'error': 'An error occurred while processing your request. Please try again.'
            }, status=500)
        
    def _prepare_patient_data(self, data):
        """Prepare patient data for temp storage - UPDATED for OTP flow"""
        patient_type_raw = data['patient_type']
        
        if patient_type_raw == 'new':
            return self._prepare_new_patient_data(data)
        elif patient_type_raw == 'existing':
            return self._prepare_existing_patient_data_with_otp(data)
        else:
            return JsonResponse({'success': False, 'error': 'Invalid patient type'}, status=400), None

    def _prepare_new_patient_data(self, data):
        """Prepare new patient data for temp storage"""
        required_new_fields = ['first_name', 'last_name', 'email']
        for field in required_new_fields:
            if not data.get(field, '').strip():
                field_label = field.replace('_', ' ').title()
                return JsonResponse({
                    'success': False, 
                    'error': f'{field_label} is required for new patients'
                }, status=400), None
        
        # Extract and validate data
        first_name = data.get('first_name', '').strip()
        last_name = data.get('last_name', '').strip()
        email = data.get('email', '').strip()
        contact_number = data.get('contact_number', '').strip()
        address = data.get('address', '').strip()
        
        # Validate name fields
        name_pattern = re.compile(r'^[a-zA-Z\s\-\']+$')
        
        if not name_pattern.match(first_name):
            return JsonResponse({
                'success': False,
                'error': 'First name should only contain letters, spaces, hyphens, and apostrophes'
            }, status=400), None
        
        if not name_pattern.match(last_name):
            return JsonResponse({
                'success': False,
                'error': 'Last name should only contain letters, spaces, hyphens, and apostrophes'
            }, status=400), None
        
        # Validate email format
        try:
            validate_email(email)
        except DjangoValidationError:
            return JsonResponse({
                'success': False,
                'error': 'Please enter a valid email address'
            }, status=400), None
        
        # Validate contact number if provided
        if contact_number:
            phone_pattern = re.compile(r'^(\+63|0)?9\d{9}$')
            clean_contact = contact_number.replace(' ', '').replace('-', '')
            if not phone_pattern.match(clean_contact):
                return JsonResponse({
                    'success': False,
                    'error': 'Please enter a valid Philippine mobile number (e.g., +639123456789)'
                }, status=400), None
            contact_number = clean_contact
        
        return {
            'first_name': first_name,
            'last_name': last_name,
            'email': email,
            'contact_number': contact_number,
            'address': address,
            'existing_patient': None
        }, 'new'

    def _prepare_existing_patient_data_with_otp(self, data):
        """
        Prepare existing patient data - UPDATED to use patient_id from OTP verification
        The frontend has already verified the OTP and selected the patient
        """
        patient_id = data.get('patient_id')
        
        if not patient_id:
            return JsonResponse({
                'success': False, 
                'error': 'Patient verification required. Please verify your email.'
            }, status=400), None
        
        # Get the patient by ID
        try:
            patient = Patient.objects.get(id=patient_id, is_active=True)
        except Patient.DoesNotExist:
            return JsonResponse({
                'success': False, 
                'error': 'Invalid patient selection. Please try again.'
            }, status=400), None
        
        # Return patient data for temp storage
        return {
            'first_name': patient.first_name,
            'last_name': patient.last_name,
            'email': patient.email,
            'contact_number': patient.contact_number,
            'address': patient.address,
            'existing_patient': patient  # Link to existing patient
        }, 'returning'
    
    def _validate_appointment_datetime(self, appointment_date, period):
        """Validate appointment date and period constraints"""
        # Check past dates
        if appointment_date <= timezone.now().date():
            return 'Appointment date must be in the future'
        
        # Check Sundays
        if appointment_date.weekday() == 6:  # Sunday
            return 'Appointments are not available on Sundays'
        
        # Basic period validation
        if period not in ['AM', 'PM']:
            return 'Invalid period selected'
        
        return None  # No validation errors
    
    def _handle_form_request(self, request):
        """Handle regular form submission (fallback)"""
        messages.info(request, 'Please use the appointment booking form.')
        return redirect('core:book_appointment')


# Add new API endpoints for AM/PM slot availability
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt


@require_http_methods(["GET"])
def get_slot_availability_api(request):
    """
    API ENDPOINT: Get AM/PM slot availability for date range
    Used by the booking calendar
    """
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date', start_date_str)  # Default to same date if not provided
    
    if not start_date_str:
        return JsonResponse({'error': 'start_date is required'}, status=400)
    
    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
    except ValueError:
        return JsonResponse({'error': 'Invalid date format. Use YYYY-MM-DD'}, status=400)
    
    # Validate date range
    today = timezone.now().date()
    if start_date <= today:
        return JsonResponse({'error': 'Start date must be in the future'}, status=400)
    
    if end_date < start_date:
        return JsonResponse({'error': 'End date must be after start date'}, status=400)
    
    # Limit range to prevent excessive queries
    if (end_date - start_date).days > 90:
        return JsonResponse({'error': 'Date range too large. Maximum 90 days.'}, status=400)
    
    # Get availability for date range
    availability = DailySlots.get_availability_for_range(start_date, end_date)
    
    # Format for frontend
    formatted_availability = {}
    for date_obj, slots in availability.items():
        date_str = date_obj.strftime('%Y-%m-%d')
        
        # Skip Sundays and past dates
        if date_obj.weekday() == 6 or date_obj <= today:
            continue
        
        formatted_availability[date_str] = {
            'date': date_str,
            'weekday': date_obj.strftime('%A'),
            'am_slots': {
                'available': slots['am_available'],
                'total': slots['am_total'],
                'is_available': slots['am_available'] > 0
            },
            'pm_slots': {
                'available': slots['pm_available'],
                'total': slots['pm_total'],
                'is_available': slots['pm_available'] > 0
            },
            'has_availability': (slots['am_available'] > 0 or slots['pm_available'] > 0)
        }
    
    return JsonResponse({
        'availability': formatted_availability,
        'date_range': {
            'start': start_date_str,
            'end': end_date_str
        }
    })


@require_http_methods(["GET"])
def find_patient_api(request):
    """
    API ENDPOINT: Find existing patient by email or contact number
    """
    identifier = request.GET.get('identifier', '').strip()
    if not identifier or len(identifier) < 3:
        return JsonResponse({'found': False})
    
    # Search logic
    query = Q(is_active=True)
    
    if '@' in identifier:
        query &= Q(email__iexact=identifier)
    else:
        # Handle contact number with flexible formatting
        clean_identifier = identifier.replace(' ', '').replace('-', '').replace('+', '')
        query &= (
            Q(contact_number=identifier) | 
            Q(contact_number=clean_identifier) |
            (Q(contact_number__endswith=clean_identifier[-10:]) if len(clean_identifier) >= 10 else Q())
        )
    
    patient = Patient.objects.filter(query).first()
    
    if patient:
        return JsonResponse({
            'found': True,
            'patient': {
                'id': patient.id,
                'name': patient.full_name,
                'email': patient.email or '',
                'contact_number': patient.contact_number or ''
            }
        })
    else:
        return JsonResponse({'found': False})

class DashboardView(LoginRequiredMixin, TemplateView):
    """Enhanced dashboard with role-based templates - UPDATED for AM/PM system"""
    
    def get_template_names(self):
        """Return different template based on billing permission"""
        if hasattr(self.request.user, 'has_permission') and self.request.user.has_permission('billing'):
            return ['core/dashboard_billing.html']
        return ['core/dashboard.html']
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get today's date in Manila timezone
        manila_tz = pytz.timezone('Asia/Manila')
        manila_now = timezone.now().astimezone(manila_tz)
        today = manila_now.date()
        this_month = today.replace(day=1)
        
        # Check if user has billing permissions
        has_billing_permission = (
            hasattr(self.request.user, 'has_permission') and 
            self.request.user.has_permission('billing')
        )
        
        # Today's appointments - Use BLOCKING_STATUSES for consistency
        todays_appointments = Appointment.objects.filter(
            appointment_date=today,
            status__in=Appointment.BLOCKING_STATUSES
        ).select_related('patient', 'assigned_dentist', 'service').order_by('period', 'requested_at')
        
        context['todays_appointments'] = todays_appointments
        
        # Pending appointment requests
        context['pending_requests'] = Appointment.objects.filter(
            status='pending'
        ).count()
        
        # Recent patients (only if user has patient permissions)
        if hasattr(self.request.user, 'has_permission') and self.request.user.has_permission('patients'):
            context['recent_patients'] = Patient.objects.filter(
                is_active=True
            ).order_by('-created_at')[:5]
        
        # Base statistics
        context['stats'] = {
            'total_patients': Patient.objects.filter(is_active=True).count(),
            'todays_appointments_count': todays_appointments.count(),
            'pending_requests_count': context['pending_requests'],
            'active_dentists': User.objects.filter(is_active_dentist=True).count(),
        }
        
        # Add payment metrics ONLY if user has billing permissions
        if has_billing_permission:
            from decimal import Decimal
            from django.db.models import Sum, F, Case, When, DecimalField
            
            context['stats'].update({
                'total_outstanding': Payment.objects.filter(
                    status__in=['pending', 'partially_paid']
                ).aggregate(
                    total=Sum(
                        Case(
                            When(status__in=['pending', 'partially_paid'], 
                                 then=F('total_amount') - F('amount_paid')),
                            default=0,
                            output_field=DecimalField()
                        )
                    )
                )['total'] or Decimal('0'),
                
                'overdue_payments_count': Payment.objects.filter(
                    next_due_date__lt=today,
                    status__in=['pending', 'partially_paid']
                ).count(),
                
                'this_month_revenue': PaymentTransaction.objects.filter(
                    payment_date__gte=this_month
                ).aggregate(Sum('amount'))['amount__sum'] or Decimal('0'),
            })
            
            # Overdue payments for attention section
            context['overdue_payments'] = Payment.objects.filter(
                next_due_date__lt=today,
                status__in=['pending', 'partially_paid']
            ).select_related('patient').order_by('next_due_date')[:5]
            
            # Recent payment transactions
            context['recent_transactions'] = PaymentTransaction.objects.select_related(
                'payment__patient'
            ).order_by('-payment_datetime')[:5]
        
        context['has_billing_permission'] = has_billing_permission
        
        # Today's slot availability summary with percentage calculations
        try:
            daily_slots = DailySlots.objects.get(date=today)
            
            # Calculate availability
            am_available = daily_slots.get_available_am_slots()
            am_total = daily_slots.am_slots
            pm_available = daily_slots.get_available_pm_slots()
            pm_total = daily_slots.pm_slots
            
            # Calculate percentages
            am_percentage = (am_available / am_total * 100) if am_total > 0 else 0
            pm_percentage = (pm_available / pm_total * 100) if pm_total > 0 else 0
            
            context['todays_slot_summary'] = {
                'am_available': am_available,
                'am_total': am_total,
                'am_percentage': round(am_percentage, 1),
                'pm_available': pm_available,
                'pm_total': pm_total,
                'pm_percentage': round(pm_percentage, 1),
            }
            
        except DailySlots.DoesNotExist:
            # Try to create default slots for today
            daily_slots, created = DailySlots.get_or_create_for_date(today)
            if daily_slots:
                am_available = daily_slots.get_available_am_slots()
                am_total = daily_slots.am_slots
                pm_available = daily_slots.get_available_pm_slots()
                pm_total = daily_slots.pm_slots
                
                am_percentage = (am_available / am_total * 100) if am_total > 0 else 0
                pm_percentage = (pm_available / pm_total * 100) if pm_total > 0 else 0
                
                context['todays_slot_summary'] = {
                    'am_available': am_available,
                    'am_total': am_total,
                    'am_percentage': round(am_percentage, 1),
                    'pm_available': pm_available,
                    'pm_total': pm_total,
                    'pm_percentage': round(pm_percentage, 1),
                }
            else:
                context['todays_slot_summary'] = {
                    'am_available': 0,
                    'am_total': 0,
                    'am_percentage': 0,
                    'pm_available': 0,
                    'pm_total': 0,
                    'pm_percentage': 0,
                }
        
        return context

@require_http_methods(["POST"])
def send_booking_otp(request):
    """
    API ENDPOINT: Send OTP code for booking verification
    Used when existing patient enters their email
    """
    try:
        import json
        data = json.loads(request.body)
        email = data.get('email', '').strip().lower()
        
        if not email:
            return JsonResponse({
                'success': False,
                'error': 'Please enter your email address.'
            }, status=400)
        
        # Validate email format
        from django.core.validators import validate_email as django_validate_email
        from django.core.exceptions import ValidationError
        try:
            django_validate_email(email)
        except ValidationError:
            return JsonResponse({
                'success': False,
                'error': 'Please enter a valid email address.'
            }, status=400)
        
        # Check if any patients exist with this email
        patients = Patient.objects.filter(
            email__iexact=email,
            is_active=True
        )
        
        if not patients.exists():
            return JsonResponse({
                'success': False,
                'error': 'We couldn\'t find a patient record with this email address. Please check your email or register as a new patient.'
            }, status=404)
        
        # Get client IP
        ip_address = request.META.get('REMOTE_ADDR')
        
        # Create OTP code with rate limiting
        access_code, created, error_msg = PatientPortalAccess.create_access_code(
            email=email,
            purpose='booking',
            ip_address=ip_address
        )
        
        if not created:
            return JsonResponse({
                'success': False,
                'error': error_msg
            }, status=429)
        
        # Send email with OTP
        patient_name = patients.first().first_name if patients.count() == 1 else 'Patient'
        email_sent = EmailService.send_verification_code_email(
            email=email,
            code=access_code.code,
            patient_name=patient_name
        )
        
        if not email_sent:
            logger.error(f"Failed to send OTP email to {email}")
            return JsonResponse({
                'success': False,
                'error': 'Failed to send verification code. Please try again.'
            }, status=500)
        
        # Get remaining attempts
        remaining = PatientPortalAccess.get_remaining_attempts(email, purpose='booking')
        
        logger.info(f"OTP sent successfully to {email} for booking verification")
        
        return JsonResponse({
            'success': True,
            'message': 'Verification code sent to your email.',
            'remaining_attempts': remaining,
            'expires_in_minutes': 15
        })
        
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid request data.'
        }, status=400)
    except Exception as e:
        logger.error(f"Error in send_booking_otp: {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': 'An error occurred. Please try again.'
        }, status=500)


@require_http_methods(["POST"])
def verify_booking_otp(request):
    """
    API ENDPOINT: Verify OTP code and return patient selection if multiple found
    """
    try:
        import json
        data = json.loads(request.body)
        email = data.get('email', '').strip().lower()
        code = data.get('code', '').strip()
        
        if not email or not code:
            return JsonResponse({
                'success': False,
                'error': 'Email and verification code are required.'
            }, status=400)
        
        # Verify the code
        is_valid, result = PatientPortalAccess.verify_code(email, code, purpose='booking')
        
        if not is_valid:
            return JsonResponse({
                'success': False,
                'error': result  # Error message from verify_code
            }, status=400)
        
        # Code is valid, get the access_code object
        access_code = result
        
        # Find all patients with this email
        patients = Patient.objects.filter(
            email__iexact=email,
            is_active=True
        ).order_by('-created_at')
        
        if not patients.exists():
            return JsonResponse({
                'success': False,
                'error': 'No patient records found. This should not happen.'
            }, status=404)
        
        # Format patient data for selection
        patient_options = []
        for patient in patients:
            # Get last appointment date if exists
            last_appointment = patient.appointments.filter(
                status__in=['completed', 'confirmed']
            ).order_by('-appointment_date').first()
            
            last_visit = None
            if last_appointment:
                last_visit = last_appointment.appointment_date.strftime('%B %Y')
            
            patient_options.append({
                'id': patient.id,
                'name': patient.full_name,
                'registered': patient.created_at.strftime('%B %Y'),
                'last_visit': last_visit
            })
        
        # Store access_code ID in response for later linking
        return JsonResponse({
            'success': True,
            'verified': True,
            'access_code_id': access_code.id,
            'multiple_patients': len(patient_options) > 1,
            'patients': patient_options
        })
        
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid request data.'
        }, status=400)
    except Exception as e:
        logger.error(f"Error in verify_booking_otp: {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': 'An error occurred. Please try again.'
        }, status=500)


@require_http_methods(["POST"])
def select_booking_patient(request):
    """
    API ENDPOINT: Link selected patient to verified OTP session
    This is called when user selects which patient they are from the list
    """
    try:
        import json
        data = json.loads(request.body)
        access_code_id = data.get('access_code_id')
        patient_id = data.get('patient_id')
        
        if not access_code_id or not patient_id:
            return JsonResponse({
                'success': False,
                'error': 'Missing required data.'
            }, status=400)
        
        # Get the access code
        try:
            access_code = PatientPortalAccess.objects.get(
                id=access_code_id,
                purpose='booking',
                is_used=False
            )
        except PatientPortalAccess.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Verification session expired. Please start over.'
            }, status=400)
        
        # Check if expired
        if access_code.is_expired:
            return JsonResponse({
                'success': False,
                'error': 'Verification code has expired. Please request a new code.'
            }, status=400)
        
        # Get the patient
        try:
            patient = Patient.objects.get(
                id=patient_id,
                email__iexact=access_code.email,
                is_active=True
            )
        except Patient.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Invalid patient selection.'
            }, status=400)
        
        # DON'T mark as used yet - just link the patient
        # It will be marked as used when the appointment is actually submitted
        access_code.verified_patient = patient
        access_code.save(update_fields=['verified_patient'])
        
        logger.info(f"Patient {patient.id} selected for booking via OTP")
        
        return JsonResponse({
            'success': True,
            'patient': {
                'id': patient.id,
                'name': patient.full_name,
                'email': patient.email,
                'contact_number': patient.contact_number or ''
            }
        })
        
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid request data.'
        }, status=400)
    except Exception as e:
        logger.error(f"Error in select_booking_patient: {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': 'An error occurred. Please try again.'
        }, status=500)

@require_http_methods(["POST"])
def submit_booking_appointment(request):
    """
    API ENDPOINT: Submit appointment booking (handles the actual booking creation)
    This is what the frontend calls when user clicks "Submit Request"
    """
    try:
        import json
        data = json.loads(request.body)
        
        # Use the existing _handle_json_request logic from BookAppointmentView
        view = BookAppointmentView()
        view.request = request
        return view._handle_json_request(data)
        
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid request data.'
        }, status=400)
    except Exception as e:
        logger.error(f"Error in submit_booking_appointment: {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': 'An error occurred. Please try again.'
        }, status=500)

class AuditLogListView(LoginRequiredMixin, ListView):
    """Enhanced view for audit logs with comprehensive filtering"""
    model = AuditLog
    template_name = 'core/audit_log_list.html'
    context_object_name = 'logs'
    paginate_by = 50
    
    def dispatch(self, request, *args, **kwargs):
        if not request.user.has_permission('maintenance'):
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('core:dashboard')
        return super().dispatch(request, *args, **kwargs)
    
    def get_queryset(self):
        queryset = AuditLog.objects.select_related('user').order_by('-timestamp')
        
        # Build active filters list for display
        self.active_filters = []
        
        # Filter by user
        user_filter = self.request.GET.get('user')
        if user_filter:
            try:
                user_id = int(user_filter)
                queryset = queryset.filter(user_id=user_id)
                user = User.objects.get(id=user_id)
                self.active_filters.append(f"User: {user.get_full_name()}")
            except (ValueError, User.DoesNotExist):
                pass
        
        # Filter by action
        action_filter = self.request.GET.get('action')
        if action_filter:
            queryset = queryset.filter(action=action_filter)
            action_display = dict(AuditLog.ACTION_CHOICES).get(action_filter, action_filter)
            self.active_filters.append(f"Action: {action_display}")
        
        # Filter by model name
        model_filter = self.request.GET.get('model_name')
        if model_filter:
            queryset = queryset.filter(model_name=model_filter)
            self.active_filters.append(f"Module: {model_filter.title()}")
        
        # Filter by date range
        date_from = self.request.GET.get('date_from')
        date_to = self.request.GET.get('date_to')
        
        if date_from:
            try:
                date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
                queryset = queryset.filter(timestamp__date__gte=date_from_obj)
                self.active_filters.append(f"From: {date_from_obj.strftime('%b %d, %Y')}")
            except ValueError:
                pass
        
        if date_to:
            try:
                date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
                queryset = queryset.filter(timestamp__date__lte=date_to_obj)
                self.active_filters.append(f"To: {date_to_obj.strftime('%b %d, %Y')}")
            except ValueError:
                pass
        
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get all users for filter dropdown
        context['users'] = User.objects.filter(is_active=True).order_by('first_name', 'last_name')
        
        # Action choices
        context['action_choices'] = AuditLog.ACTION_CHOICES
        
        # Get unique model names for filter
        context['model_choices'] = AuditLog.objects.values_list('model_name', flat=True).distinct().order_by('model_name')
        
        # Current filters
        context['filters'] = {
            'user': self.request.GET.get('user', ''),
            'action': self.request.GET.get('action', ''),
            'model_name': self.request.GET.get('model_name', ''),
            'date_from': self.request.GET.get('date_from', ''),
            'date_to': self.request.GET.get('date_to', ''),
        }
        
        # Active filters for display
        context['active_filters'] = getattr(self, 'active_filters', [])
        
        # Total count
        context['total_count'] = self.get_queryset().count()
        
        return context

class MaintenanceHubView(LoginRequiredMixin, TemplateView):
    """Maintenance hub for admin functions"""
    template_name = 'core/maintenance_hub.html'
    
    def dispatch(self, request, *args, **kwargs):
        if not request.user.has_permission('maintenance'):
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('core:dashboard')
        return super().dispatch(request, *args, **kwargs)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['stats'] = {
            'users_count': User.objects.count(),
            'services_count': Service.objects.count(),
            'patients_count': Patient.objects.count(),
            'appointments_count': Appointment.objects.count(),
        }
        return context

class SystemSettingsView(LoginRequiredMixin, FormView):
    """System settings management"""
    template_name = 'core/system_settings.html'
    form_class = SystemSettingsForm
    success_url = reverse_lazy('core:settings')  # Redirect back to settings page
    
    def dispatch(self, request, *args, **kwargs):
        if not request.user.has_permission('maintenance'):
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('core:dashboard')
        return super().dispatch(request, *args, **kwargs)
    
    def form_valid(self, form):
        try:
            # Save settings and get changes
            changes = form.save(user=self.request.user)
            
            if changes:
                # Log the changes
                AuditLog.log_action(
                    user=self.request.user,
                    action='update',
                    model_instance=SystemSetting.objects.first() or SystemSetting(key='settings'),
                    changes=changes,
                    request=self.request,
                    description=f"Updated {len(changes)} system setting(s)"
                )
                
                messages.success(
                    self.request,
                    f'✓ Settings updated successfully. {len(changes)} setting(s) changed.'
                )
            else:
                messages.info(self.request, 'No changes were made.')
                
        except Exception as e:
            messages.error(
                self.request,
                'An error occurred while saving settings. Please try again.'
            )
            # Log the error
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error saving system settings: {str(e)}", exc_info=True)
            return self.form_invalid(form)
        
        return super().form_valid(form)
    
    def form_invalid(self, form):
        """Handle invalid form submission"""
        messages.error(
            self.request,
            'Please correct the errors in the form.'
        )
        return super().form_invalid(form)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Stats for the settings page
        context['stats'] = {
            'total_appointments': Appointment.objects.count(),
            'total_patients': Patient.objects.count(),
            'total_services': Service.objects.count(),
            'total_users': User.objects.count(),
        }
        
        context['page_title'] = 'System Settings'
        
        return context