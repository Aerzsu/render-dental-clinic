# core/views.py - Updated for AM/PM slot system
import json
import re
import logging
from datetime import datetime, timedelta
from decimal import Decimal

from django.shortcuts import redirect
from django.views.generic import TemplateView, ListView
from django.utils import timezone
from django.http import JsonResponse
from django.db import transaction
from django.core.validators import validate_email
from django.core.exceptions import ValidationError as DjangoValidationError
from django.views.decorators.http import require_http_methods
from django.db.models import Sum, F, Case, When, DecimalField

from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.views.generic import FormView
from django.db.models import Q, Count
from django.urls import reverse_lazy
import pytz

from .models import AuditLog, SystemSetting
from appointments.models import Appointment, TimeSlotConfiguration, Payment, PaymentTransaction, PaymentItem
from patients.models import Patient
from patient_portal.models import PatientPortalAccess
from services.models import Service
from users.models import User
from core.email_service import EmailService
from core.forms import SystemSettingsForm
from core.utils import get_manila_today, get_manila_now

logger = logging.getLogger(__name__)

class HomeView(TemplateView):
    """Public landing page with popular services"""
    template_name = 'core/home.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get 6 most popular services (by usage in completed appointments)
        popular_services = Service.active.filter(
            paymentitem__payment__appointment__status='completed'
        ).annotate(
            usage_count=Count('paymentitem')
        ).order_by('-usage_count')[:6]
        
        # If less than 6 popular services exist, fill with any active services
        if popular_services.count() < 6:
            popular_service_ids = [s.id for s in popular_services]
            remaining_count = 6 - popular_services.count()
            
            additional_services = Service.active.exclude(
                id__in=popular_service_ids
            )[:remaining_count]
            
            # Combine both querysets
            context['featured_services'] = list(popular_services) + list(additional_services)
        else:
            context['featured_services'] = popular_services
        
        # Get all active services for modal (alphabetically sorted)
        context['all_services'] = Service.active.all().order_by('name')
        
        # Get active dentists
        context['dentists'] = User.objects.filter(is_active_dentist=True)
        
        return context
    
class DashboardView(LoginRequiredMixin, TemplateView):
    """Enhanced dashboard with role-based templates - UPDATED for timeslot system"""
    
    def get_template_names(self):
        """Return different template based on billing permission"""
        if hasattr(self.request.user, 'has_permission') and self.request.user.has_permission('billing'):
            return ['core/dashboard_billing.html']
        return ['core/dashboard.html']
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get today's date in Manila timezone
        today = get_manila_now()
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
        ).select_related('patient', 'assigned_dentist', 'service').order_by('start_time')
        
        context['todays_appointments'] = todays_appointments
        context['today'] = today
        
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
        
        # Today's timeslot availability summary
        try:
            config = TimeSlotConfiguration.objects.get(date=today)
            
            # Get all timeslots for today
            all_slots = config.get_all_timeslots()
            total_slots = len(all_slots)
            
            # Get available slots (30-minute baseline)
            available_slots = config.get_available_slots(30, include_pending=False)
            available_count = len(available_slots)
            
            # Calculate occupied slots
            occupied_count = total_slots - available_count
            
            # Get pending count
            pending_count = config.get_pending_count()
            
            # Check if fully booked
            is_fully_booked = available_count == 0
            
            # Find next available timeslot
            next_available = None
            if available_slots:
                next_available = available_slots[0].strftime('%I:%M %p')
            
            context['todays_timeslot_summary'] = {
                'has_config': True,
                'start_time': config.start_time.strftime('%I:%M %p'),
                'end_time': config.end_time.strftime('%I:%M %p'),
                'total_slots': total_slots,
                'available_count': available_count,
                'occupied_count': occupied_count,
                'pending_count': pending_count,
                'is_fully_booked': is_fully_booked,
                'next_available': next_available,
            }
            
        except TimeSlotConfiguration.DoesNotExist:
            # If admin hasn't set up timeslots for today
            context['todays_timeslot_summary'] = {
                'has_config': False,
                'total_slots': 0,
                'available_count': 0,
                'occupied_count': 0,
                'pending_count': 0,
                'is_fully_booked': False,
                'next_available': None,
            }
        
        # Upcoming appointments this week (for quick overview)
        week_end = today + timedelta(days=7)
        context['upcoming_appointments'] = Appointment.objects.filter(
            appointment_date__gt=today,
            appointment_date__lte=week_end,
            status__in=['pending', 'confirmed']
        ).select_related('patient', 'service').order_by('appointment_date', 'start_time')[:5]
        
        return context

class BookAppointmentView(TemplateView):
    """
    PUBLIC VIEW: Timeslot-based appointment booking
    UPDATED: Uses TimeSlotConfiguration and specific start_time instead of AM/PM periods
    """
    template_name = 'core/book_appointment.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get all active services with timeslot-relevant data
        services = []
        for service in Service.active.all().order_by('name'):
            services.append({
                'id': service.id,
                'name': service.name,
                'duration_minutes': service.duration_minutes,
                'duration_display': service.duration_display,
                'min_price': float(service.min_price) if service.min_price else 0,
                'max_price': float(service.max_price) if service.max_price else 0,
                'starting_price': service.starting_price_display,
                'price_range': service.price_range_display,
                'description': service.description or "Professional dental service"
            })
        
        # Get clinic hours for display
        clinic_hours = SystemSetting.get_setting('clinic_hours', '10:00 AM - 6:00 PM')
        
        # Pass today's date from server for timezone consistency
        today_date = timezone.now().date().isoformat()
        
        context.update({
            'services_json': json.dumps(services),
            'today_date': today_date,
            'clinic_hours': clinic_hours,
        })
        
        return context
    
    def post(self, request, *args, **kwargs):
        """Handle appointment booking submission - UPDATED for timeslot system"""
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
            logger.error(f'Error in BookAppointmentView: {str(e)}', exc_info=True)
            return JsonResponse({
                'success': False, 
                'error': 'An unexpected error occurred. Please try again.'
            }, status=500)
    
    def _handle_json_request(self, data):
        """Handle JSON appointment request - UPDATED for timeslot system"""
        # Validate required fields
        required_fields = ['patient_type', 'service', 'appointment_date', 'start_time']
        for field in required_fields:
            if not data.get(field):
                field_label = field.replace('_', ' ').title()
                return JsonResponse({'success': False, 'error': f'{field_label} is required'}, status=400)
        
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
                
                # Parse and validate start time
                try:
                    start_time = datetime.strptime(data['start_time'], '%H:%M:%S').time()
                except ValueError:
                    return JsonResponse({'success': False, 'error': 'Invalid time format'}, status=400)
                
                # Validate appointment date constraints
                validation_error = self._validate_appointment_datetime(appointment_date)
                if validation_error:
                    return JsonResponse({'success': False, 'error': validation_error}, status=400)
                
                # Check timeslot availability
                can_book, availability_message = Appointment.check_timeslot_availability(
                    appointment_date=appointment_date,
                    start_time=start_time,
                    duration_minutes=service.duration_minutes
                )
                
                if not can_book:
                    return JsonResponse({'success': False, 'error': availability_message}, status=400)
                
                # Handle patient data
                patient_data, patient_type = self._prepare_patient_data(data)
                if isinstance(patient_data, JsonResponse):  # Error response
                    return patient_data
                
                # Check for double-booking if existing patient
                if patient_data.get('existing_patient'):
                    existing_patient = patient_data['existing_patient']
                    conflicting = Appointment.objects.filter(
                        patient=existing_patient,
                        appointment_date=appointment_date,
                        status__in=Appointment.BLOCKING_STATUSES
                    )
                    
                    if conflicting.exists():
                        existing = conflicting.first()
                        formatted_date = appointment_date.strftime('%B %d, %Y')
                        return JsonResponse({
                            'success': False,
                            'error': f'You already have an appointment on {formatted_date} at {existing.start_time.strftime("%I:%M %p")}. Please select a different date.'
                        }, status=400)
                
                # Create appointment with temp patient data
                appointment = Appointment.objects.create(
                    patient=patient_data.get('existing_patient'),
                    service=service,
                    appointment_date=appointment_date,
                    start_time=start_time,
                    patient_type=patient_type,
                    reason=data.get('reason', '').strip(),
                    status='pending',
                    temp_first_name=patient_data.get('first_name', ''),
                    temp_last_name=patient_data.get('last_name', ''),
                    temp_email=patient_data.get('email', ''),
                    temp_contact_number=patient_data.get('contact_number', ''),
                    temp_address=patient_data.get('address', ''),
                )
                
                # Try auto-approval
                was_auto_approved, approval_reason = appointment.auto_approve_if_eligible()
                
                if was_auto_approved:
                    # Send confirmation email for auto-approved appointment
                    from core.email_service import EmailService
                    EmailService.send_appointment_approved_email(appointment)
                    
                    status_message = 'confirmed'
                    logger.info(f'Appointment {appointment.id} auto-approved: {approval_reason}')
                else:
                    status_message = 'pending'
                    logger.info(f'Appointment {appointment.id} requires manual approval: {approval_reason}')
                
                # Generate reference number
                reference_number = f'APT-{appointment.id:06d}'
                
                # Calculate end time for display
                end_time = appointment.get_end_time()
                
                return JsonResponse({
                    'success': True,
                    'reference_number': reference_number,
                    'appointment_id': appointment.id,
                    'appointment_date': appointment_date.strftime('%Y-%m-%d'),
                    'start_time': start_time.strftime('%I:%M %p'),
                    'end_time': end_time.strftime('%I:%M %p'),
                    'time_range': appointment.time_display,
                    'patient_name': appointment.patient_name,
                    'status': status_message,  # 'confirmed' or 'pending'
                    'auto_approved': was_auto_approved
                })
                
        except Exception as e:
            logger.error(f'Error in _handle_json_request: {str(e)}', exc_info=True)
            return JsonResponse({
                'success': False, 
                'error': 'An error occurred while processing your request. Please try again.'
            }, status=500)
    
    def _prepare_patient_data(self, data):
        """Prepare patient data for temp storage - works with OTP verification"""
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
        Prepare existing patient data - uses patient_id from OTP verification
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
        }, 'existing'
    
    def _validate_appointment_datetime(self, appointment_date):
        """Validate appointment date constraints"""
        # Check past dates
        if appointment_date <= timezone.now().date():
            return 'Appointment date must be in the future'
        
        # Check Sundays
        if appointment_date.weekday() == 6:  # Sunday
            return 'Appointments are not available on Sundays'
        
        return None  # No validation errors
    
    def _handle_form_request(self, request):
        """Handle regular form submission (fallback)"""
        messages.info(request, 'Please use the appointment booking form.')
        return redirect('core:book_appointment')


# =============================================================================
# API ENDPOINTS FOR BOOKING SYSTEM
# =============================================================================

@require_http_methods(["POST"])
def send_booking_otp(request):
    """
    API ENDPOINT: Send OTP code for booking verification
    Used when existing patient enters their email
    """
    try:
        data = json.loads(request.body)
        email = data.get('email', '').strip().lower()
        
        if not email:
            return JsonResponse({
                'success': False,
                'error': 'Please enter your email address.'
            }, status=400)
        
        # Validate email format
        try:
            validate_email(email)
        except DjangoValidationError:
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
    Called when user selects which patient they are from the list
    """
    try:
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
        
        # Link the patient (don't mark as used yet - will be used on submission)
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
    API ENDPOINT: Submit appointment booking
    This is what the frontend calls when user clicks "Submit Request"
    """
    try:
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
        
        # Import models
        from users.models import User
        from services.models import Service, Discount, Product, ProductCategory
        from patients.models import Patient
        from appointments.models import Appointment
        
        # Get counts
        context['users_count'] = User.objects.count()
        context['services_count'] = Service.objects.filter(is_archived=False).count()
        context['discounts_count'] = Discount.objects.filter(is_active=True).count()
        context['products_count'] = Product.objects.filter(is_active=True).count()  # ADD THIS
        context['categories_count'] = ProductCategory.objects.count()  # ADD THIS
        
        # Legacy stats object (if used elsewhere)
        context['stats'] = {
            'users_count': context['users_count'],
            'services_count': context['services_count'],
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