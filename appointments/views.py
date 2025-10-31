# appointments/views.py - Part 1: Calendar, Requests, and List Views
# Timeslot-based appointment system

# Standard library imports
import json
from datetime import datetime, date, timedelta, time

# Django imports
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse, HttpResponse
from django.urls import reverse_lazy, reverse
from django.utils import timezone
from django.views.generic import ListView, DetailView, CreateView, UpdateView, TemplateView
from django.views.decorators.http import require_POST, require_http_methods
from django.contrib.contenttypes.models import ContentType
import logging

# Local imports
from .models import Appointment, Payment, TimeSlotConfiguration, TreatmentRecord, TreatmentRecordService, TreatmentRecordProduct, TreatmentRecordAuditLog
from .forms import AppointmentForm, TimeSlotConfigurationForm, TreatmentRecordForm
from patients.models import Patient
from services.models import Service, Product, ProductCategory
from users.models import User
from core.models import AuditLog
from core.email_service import EmailService

logger = logging.getLogger(__name__)

# BACKEND ADMIN/STAFF VIEWS
# ============================================================================
# SECTION 1: BACKEND - CALENDAR & DASHBOARD VIEWS
# ============================================================================
class AppointmentCalendarView(LoginRequiredMixin, TemplateView):
    """
    BACKEND VIEW: Monthly calendar view showing all appointments with timeslots
    Template: appointments/appointment_calendar.html
    Users: Staff, Dentist, Admin
    """
    template_name = 'appointments/appointment_calendar.html'
    
    def dispatch(self, request, *args, **kwargs):
        if not request.user.has_permission('appointments'):
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('core:dashboard')
        return super().dispatch(request, *args, **kwargs)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get current month or requested month with validation
        today = timezone.now().date()
        
        try:
            month = int(self.request.GET.get('month', today.month))
            year = int(self.request.GET.get('year', today.year))
            
            # Validate month and year ranges
            if not (1 <= month <= 12):
                raise ValueError("Invalid month")
            if not (2020 <= year <= 2030):  # Reasonable range
                raise ValueError("Invalid year")
                
        except (ValueError, TypeError):
            # Fallback to current date if invalid parameters
            month = today.month
            year = today.year
        
        # Calculate date range
        try:
            start_date = date(year, month, 1)
            if month == 12:
                end_date = date(year + 1, 1, 1)
            else:
                end_date = date(year, month + 1, 1)
        except ValueError:
            # Fallback if date creation fails
            start_date = date(today.year, today.month, 1)
            if today.month == 12:
                end_date = date(today.year + 1, 1, 1)
            else:
                end_date = date(today.year, today.month + 1, 1)
            month = today.month
            year = today.year
        
        # Get appointments for the month
        appointments = Appointment.objects.filter(
            appointment_date__gte=start_date,
            appointment_date__lt=end_date,
            status__in=Appointment.BLOCKING_STATUSES,
            patient__isnull=False
        ).select_related('patient', 'assigned_dentist', 'service').order_by(
            'appointment_date', 'start_time'
        )
        
        # Group appointments by date
        appointments_by_date = {}
        for appointment in appointments:
            date_key = appointment.appointment_date.strftime('%Y-%m-%d')
            
            # Validate the appointment has required fields
            if not appointment.patient or not appointment.service:
                continue  # Skip malformed appointments
            
            if date_key not in appointments_by_date:
                appointments_by_date[date_key] = []
            
            appointment_data = {
                'id': appointment.id,
                'patient_name': appointment.patient.full_name or 'Unknown Patient',
                'dentist_name': appointment.assigned_dentist.full_name if appointment.assigned_dentist else None,
                'service_name': appointment.service.name or 'Unknown Service',
                'status': appointment.status,
                'reason': appointment.reason or '',
                'patient_type': appointment.patient_type,
                'start_time': appointment.start_time.strftime('%H:%M'),
                'end_time': appointment.end_time.strftime('%H:%M'),
                'time_display': appointment.time_display,
                'appointment_date': date_key,
            }
            appointments_by_date[date_key].append(appointment_data)
        
        # Get timeslot configurations
        configs = TimeSlotConfiguration.objects.filter(
            date__gte=start_date,
            date__lt=end_date
        )
        
        configs_by_date = {}
        for config in configs:
            date_key = config.date.strftime('%Y-%m-%d')
            
            # Get available slots for 30-minute services (baseline)
            available_slots = config.get_available_slots(30, include_pending=False)
            pending_count = config.get_pending_count()
            
            configs_by_date[date_key] = {
                'start_time': config.start_time.strftime('%I:%M %p'),
                'end_time': config.end_time.strftime('%I:%M %p'),
                'total_slots': len(config.get_all_timeslots()),
                'available_count': len(available_slots),
                'pending_count': pending_count
            }
        
        # Calculate navigation months
        try:
            if month == 1:
                prev_month, prev_year = 12, year - 1
            else:
                prev_month, prev_year = month - 1, year
                
            if month == 12:
                next_month, next_year = 1, year + 1
            else:
                next_month, next_year = month + 1, year
        except:
            # Fallback navigation
            prev_month, prev_year = today.month, today.year
            next_month, next_year = today.month, today.year
        
        context.update({
            'current_month': month,
            'current_year': year,
            'current_month_name': date(year, month, 1).strftime('%B'),
            'prev_month': prev_month,
            'prev_year': prev_year,
            'next_month': next_month,
            'next_year': next_year,
            'appointments_by_date': json.dumps(appointments_by_date, default=str),
            'configs_by_date': json.dumps(configs_by_date, default=str),
            'dentists': User.objects.filter(is_active_dentist=True),
            'today': today.strftime('%Y-%m-%d'),
            'pending_count': Appointment.objects.filter(status='pending').count(),
        })

        context['can_accept_appointments'] = self.request.user.is_active_dentist
        
        return context

# ============================================================================
# SECTION 2: BACKEND - APPOINTMENT REQUEST MANAGEMENT
# ============================================================================
class AppointmentRequestsView(LoginRequiredMixin, ListView):
    """
    BACKEND VIEW: List of pending appointment requests awaiting approval
    Template: appointments/appointment_requests.html
    Users: Dentist, Admin (must be active dentist)
    """
    model = Appointment
    template_name = 'appointments/appointment_requests.html'
    context_object_name = 'appointments'
    paginate_by = 15
    
    def dispatch(self, request, *args, **kwargs):
        if not request.user.has_permission('appointments'):
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('core:dashboard')

        # Check if user can accept appointments
        if not request.user.is_active_dentist:
            messages.error(request, 'Only users who can accept appointments may view pending requests.')
            return redirect('core:dashboard')
        
        return super().dispatch(request, *args, **kwargs)
    
    def get_queryset(self):
        queryset = Appointment.objects.filter(
            status='pending'
        ).select_related('patient', 'assigned_dentist', 'service').order_by('-requested_at')
        
        # Apply filters
        patient_type = self.request.GET.get('patient_type')
        if patient_type:
            queryset = queryset.filter(patient_type=patient_type)
        
        assigned_dentist = self.request.GET.get('assigned_dentist')
        if assigned_dentist:
            queryset = queryset.filter(assigned_dentist_id=assigned_dentist)
        
        # Date range filtering
        date_from = self.request.GET.get('date_from')
        if date_from:
            try:
                date_from = datetime.strptime(date_from, '%Y-%m-%d').date()
                queryset = queryset.filter(appointment_date__gte=date_from)
            except ValueError:
                pass
        
        date_to = self.request.GET.get('date_to')
        if date_to:
            try:
                date_to = datetime.strptime(date_to, '%Y-%m-%d').date()
                queryset = queryset.filter(appointment_date__lte=date_to)
            except ValueError:
                pass
        
        # Text search - handle both patient records and temp data
        search = self.request.GET.get('search')
        if search:
            search_conditions = Q()
            
            # Search in linked patient records
            search_conditions |= (
                Q(patient__first_name__icontains=search) |
                Q(patient__last_name__icontains=search) |
                Q(patient__email__icontains=search) |
                Q(patient__contact_number__icontains=search)
            )
            
            # Search in temporary data (for pending appointments)
            search_conditions |= (
                Q(temp_first_name__icontains=search) |
                Q(temp_last_name__icontains=search) |
                Q(temp_email__icontains=search) |
                Q(temp_contact_number__icontains=search)
            )
            
            queryset = queryset.filter(search_conditions)
        
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            'pending_count': self.get_queryset().count(),
            'patient_types': [('new', 'New Patients'), ('existing', 'Existing Patients')],
            'dentists': User.objects.filter(is_active_dentist=True),
            'filters': {
                'patient_type': self.request.GET.get('patient_type', ''),
                'assigned_dentist': self.request.GET.get('assigned_dentist', ''),
                'date_from': self.request.GET.get('date_from', ''),
                'date_to': self.request.GET.get('date_to', ''),
                'search': self.request.GET.get('search', ''),
            }
        })
        return context


class CheckInView(LoginRequiredMixin, PermissionRequiredMixin, TemplateView):
    """
    Staff check-in page - shows today's appointments for quick patient arrival tracking
    """
    template_name = 'appointments/check_in.html'
    permission_required = 'appointments'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get today's date
        today = timezone.now().date()
        
        # Get all appointments for today (confirmed, pending, completed)
        appointments = Appointment.objects.filter(
            appointment_date=today,
            status__in=['confirmed', 'pending', 'completed']
        ).select_related(
            'patient', 'service', 'assigned_dentist'
        ).order_by('start_time')
        
        # Separate into upcoming and checked-in
        now = timezone.now()
        upcoming = []
        checked_in = []
        
        for appointment in appointments:
            # Calculate if appointment time has passed
            appt_datetime = appointment.appointment_datetime
            
            # Check if already completed
            if appointment.status == 'completed':
                checked_in.append({
                    'appointment': appointment,
                    'checked_in_time': appointment.confirmed_at or appt_datetime,
                    'is_completed': True
                })
            else:
                upcoming.append({
                    'appointment': appointment,
                    'has_passed': appt_datetime < now,
                    'minutes_until': int((appt_datetime - now).total_seconds() / 60) if appt_datetime > now else 0
                })
        
        # Get statistics
        total_today = len(appointments)
        checked_in_count = len(checked_in)
        remaining_count = len(upcoming)
        
        context.update({
            'today': today,
            'upcoming_appointments': upcoming,
            'checked_in_appointments': checked_in,
            'total_today': total_today,
            'checked_in_count': checked_in_count,
            'remaining_count': remaining_count,
        })
        
        return context

@login_required
@require_http_methods(["GET"])
def appointment_requests_partial(request):
    """
    HTMX PARTIAL: Auto-refresh appointment request list
    Template: appointments/partials/_request_list.html
    Used for: Live updates on appointment requests page
    """
    if not request.user.has_permission('appointments'):
        return HttpResponse('Unauthorized', status=403)
    
    if not request.user.is_active_dentist:
        return HttpResponse('Unauthorized', status=403)
    
    # Same filtering logic as main view
    queryset = Appointment.objects.filter(
        status='pending'
    ).select_related('patient', 'assigned_dentist', 'service').order_by('-requested_at')
    
    # Apply filters from GET params
    patient_type = request.GET.get('patient_type')
    if patient_type:
        queryset = queryset.filter(patient_type=patient_type)
    
    assigned_dentist = request.GET.get('assigned_dentist')
    if assigned_dentist:
        queryset = queryset.filter(assigned_dentist_id=assigned_dentist)
    
    date_from = request.GET.get('date_from')
    if date_from:
        try:
            date_from = datetime.strptime(date_from, '%Y-%m-%d').date()
            queryset = queryset.filter(appointment_date__gte=date_from)
        except ValueError:
            pass
    
    date_to = request.GET.get('date_to')
    if date_to:
        try:
            date_to = datetime.strptime(date_to, '%Y-%m-%d').date()
            queryset = queryset.filter(appointment_date__lte=date_to)
        except ValueError:
            pass
    
    search = request.GET.get('search')
    if search:
        search_conditions = Q()
        search_conditions |= (
            Q(patient__first_name__icontains=search) |
            Q(patient__last_name__icontains=search) |
            Q(patient__email__icontains=search) |
            Q(patient__contact_number__icontains=search)
        )
        search_conditions |= (
            Q(temp_first_name__icontains=search) |
            Q(temp_last_name__icontains=search) |
            Q(temp_email__icontains=search) |
            Q(temp_contact_number__icontains=search)
        )
        queryset = queryset.filter(search_conditions)
    
    # Limit to first 50 for performance
    appointments = queryset[:50]
    
    return render(request, 'appointments/partials/_request_list.html', {
        'appointments': appointments,
        'pending_count': queryset.count()
    })

# ============================================================================
# SECTION 3: BACKEND - APPOINTMENT LIST & SEARCH
# ============================================================================
class AppointmentListView(LoginRequiredMixin, ListView):
    """
    BACKEND VIEW: Comprehensive appointment list with filtering
    Template: appointments/appointment_list.html
    Users: Staff, Dentist, Admin
    Features: Search, filter by status/dentist/date
    """
    model = Appointment
    template_name = 'appointments/appointment_list.html'
    context_object_name = 'appointments'
    paginate_by = 15
    
    def dispatch(self, request, *args, **kwargs):
        if not request.user.has_permission('appointments'):
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('core:dashboard')
        return super().dispatch(request, *args, **kwargs)
    
    def get_queryset(self):
        queryset = Appointment.objects.select_related(
            'patient', 'assigned_dentist', 'service'
        )
        
        # Determine if user has applied custom filters
        has_custom_filters = any([
            self.request.GET.get('status'),
            self.request.GET.get('assigned_dentist'),
            self.request.GET.get('date_from'),
            self.request.GET.get('date_to'),
            self.request.GET.get('search'),
        ])
        
        # Apply default filters if no custom filters are set
        if not has_custom_filters:
            queryset = queryset.filter(status='confirmed')
            queryset = queryset.filter(appointment_date__gte=date.today())
        else:
            # Apply custom filters if provided
            status = self.request.GET.get('status')
            if status:
                queryset = queryset.filter(status=status)
            
            # Assigned dentist filtering
            assigned_dentist = self.request.GET.get('assigned_dentist')
            if assigned_dentist:
                queryset = queryset.filter(assigned_dentist_id=assigned_dentist)
            
            # Date range filtering
            date_from = self.request.GET.get('date_from')
            date_to = self.request.GET.get('date_to')
            
            if date_from:
                try:
                    date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
                    queryset = queryset.filter(appointment_date__gte=date_from_obj)
                except ValueError:
                    pass
            
            if date_to:
                try:
                    date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
                    queryset = queryset.filter(appointment_date__lte=date_to_obj)
                except ValueError:
                    pass
            
            # Patient name search
            search = self.request.GET.get('search')
            if search:
                queryset = queryset.filter(
                    Q(patient__first_name__icontains=search) |
                    Q(patient__last_name__icontains=search)
                )
        
        # Ordering: today's appointments with earliest first, then future dates
        return queryset.order_by('appointment_date', 'start_time')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            'status_choices': Appointment.STATUS_CHOICES,
            'dentists': User.objects.filter(is_active_dentist=True),
            'filters': {
                'status': self.request.GET.get('status', ''),
                'assigned_dentist': self.request.GET.get('assigned_dentist', ''),
                'date_from': self.request.GET.get('date_from', ''),
                'date_to': self.request.GET.get('date_to', ''),
                'search': self.request.GET.get('search', ''),
            }
        })
        return context

# ============================================================================
# SECTION 4: BACKEND - APPOINTMENT CRUD OPERATIONS
# ============================================================================
class AppointmentCreateView(LoginRequiredMixin, CreateView):
    """
    BACKEND VIEW: Create new appointment (staff/admin direct booking)
    Template: appointments/appointment_form.html
    Users: Staff, Dentist, Admin
    Features: Patient search, timeslot selection, auto-approval
    """
    model = Appointment
    form_class = AppointmentForm
    template_name = 'appointments/appointment_form.html'
    
    def dispatch(self, request, *args, **kwargs):
        if not request.user.has_permission('appointments'):
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('core:dashboard')
        return super().dispatch(request, *args, **kwargs)
    
    def get_initial(self):
        """Pre-fill patient if provided via query parameter"""
        initial = super().get_initial()
        patient_id = self.request.GET.get('patient')
        
        if patient_id:
            try:
                patient = Patient.objects.get(pk=patient_id, is_active=True)
                initial['patient'] = patient
            except Patient.DoesNotExist:
                messages.warning(
                    self.request,
                    'The selected patient could not be found. Please select a patient below.'
                )
            except ValueError:
                # Invalid patient ID format
                pass
        
        # Pre-fill date if provided (for walk-ins from check-in page)
        if 'date' in self.request.GET:
            initial['appointment_date'] = self.request.GET.get('date')
        
        # Pre-fill patient if provided
        if 'patient' in self.request.GET:
            initial['patient'] = self.request.GET.get('patient')
        
        return initial
    
    def get_context_data(self, **kwargs):
        """Add pre-selected patient info to context"""
        context = super().get_context_data(**kwargs)
        patient_id = self.request.GET.get('patient')
        
        if patient_id:
            try:
                patient = Patient.objects.get(pk=patient_id, is_active=True)
                context['preselected_patient'] = {
                    'id': patient.id,
                    'name': patient.full_name,
                    'email': patient.email or 'No email',
                    'phone': patient.contact_number or 'No phone'
                }
            except (Patient.DoesNotExist, ValueError):
                # Already handled in get_initial
                pass
        
        return context
    
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs
    
    def form_valid(self, form):
        try:
            with transaction.atomic():
                # Auto-approve staff bookings
                if self.request.user.has_permission('appointments'):
                    form.instance.status = 'confirmed'
                    form.instance.confirmed_at = timezone.now()
                    form.instance.confirmed_by = self.request.user
                    
                    # Auto-assign dentist if not specified
                    if not form.instance.assigned_dentist:
                        available_dentist = User.objects.filter(is_active_dentist=True).first()
                        if available_dentist:
                            form.instance.assigned_dentist = available_dentist
                
                response = super().form_valid(form)
                
                # Log the action
                AuditLog.log_action(
                    user=self.request.user,
                    action='create',
                    model_instance=form.instance,
                    changes={'status': form.instance.status},
                    request=self.request
                )
                
                messages.success(
                    self.request, 
                    f'Appointment for {form.instance.patient.full_name} on {form.instance.appointment_date.strftime("%B %d, %Y")} at {form.instance.start_time.strftime("%I:%M %p")} created successfully.'
                )
                return response
                
        except ValidationError as e:
            form.add_error(None, str(e))
            return self.form_invalid(form)
        except Exception as e:
            messages.error(self.request, f'Error creating appointment: {str(e)}')
            return self.form_invalid(form)
    
    def get_success_url(self):
        return reverse_lazy('appointments:appointment_list')


class AppointmentDetailView(LoginRequiredMixin, DetailView):
    """
    BACKEND VIEW: Detailed appointment information
    Template: appointments/appointment_detail.html
    Users: Staff, Dentist, Admin
    Features: Patient stats, timeslot info, clinical notes, actions
    """
    model = Appointment
    template_name = 'appointments/appointment_detail.html'
    context_object_name = 'appointment'
    
    def dispatch(self, request, *args, **kwargs):
        if not request.user.has_permission('appointments'):
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('core:dashboard')
        return super().dispatch(request, *args, **kwargs)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        appointment = self.object
        
        # Patient appointment statistics
        if appointment.patient:
            patient_appointments = appointment.patient.appointments.all()
            context['patient_stats'] = {
                'total_appointments': patient_appointments.count(),
                'completed_appointments': patient_appointments.filter(status='completed').count(),
                'pending_appointments': patient_appointments.filter(status='pending').count(),
                'cancelled_appointments': patient_appointments.filter(status='cancelled').count(),
            }
        else:
            # Handle case where appointment has no linked patient (pending appointments)
            context['patient_stats'] = {
                'total_appointments': 0,
                'completed_appointments': 0,
                'pending_appointments': 1,  # This appointment itself
                'cancelled_appointments': 0,
            }
        
        # Current date for template comparisons
        context['today'] = timezone.now().date()
        
        # Timeslot configuration info
        if appointment.appointment_date:
            config = TimeSlotConfiguration.get_for_date(appointment.appointment_date)
            if config:
                available_slots = config.get_available_slots(
                    appointment.service.duration_minutes,
                    include_pending=False
                )
                context['config_info'] = {
                    'start_time': config.start_time.strftime('%I:%M %p'),
                    'end_time': config.end_time.strftime('%I:%M %p'),
                    'available_slots_count': len(available_slots),
                    'pending_count': config.get_pending_count()
                }
        
        # Available dentists for assignment
        context['available_dentists'] = User.objects.filter(is_active_dentist=True)
        
        return context

@login_required
@require_POST
def clear_invoice_modal(request):
    """Clear the invoice creation modal flag from session"""
    if 'show_invoice_modal' in request.session:
        del request.session['show_invoice_modal']
    if 'invoice_appointment_id' in request.session:
        del request.session['invoice_appointment_id']
    return JsonResponse({'success': True})

class AppointmentUpdateView(LoginRequiredMixin, UpdateView):
    """
    BACKEND VIEW: Edit existing appointment
    Template: appointments/appointment_form.html
    Users: Staff, Dentist, Admin
    Features: Reschedule, change dentist, update details
    """
    model = Appointment
    form_class = AppointmentForm
    template_name = 'appointments/appointment_form.html'
    context_object_name = 'appointment'
    
    def dispatch(self, request, *args, **kwargs):
        if not request.user.has_permission('appointments'):
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('core:dashboard')
        return super().dispatch(request, *args, **kwargs)
    
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs
    
    def form_valid(self, form):
        # Log the changes
        AuditLog.log_action(
            user=self.request.user,
            action='update',
            model_instance=form.instance,
            request=self.request
        )
        
        messages.success(
            self.request,
            f'Appointment for {form.instance.patient.full_name} updated successfully.'
        )
        return super().form_valid(form)
    
    def get_success_url(self):
        return reverse_lazy('appointments:appointment_detail', kwargs={'pk': self.object.pk})

# ============================================================================
# SECTION 5: BACKEND - APPOINTMENT ACTIONS
# ============================================================================
@login_required
@require_POST
def mark_patient_arrived(request, pk):
    """ACTION VIEW: Mark patient as arrived - HTMX compatible"""
    if not request.user.has_permission('appointments'):
        if request.headers.get('HX-Request'):
            return HttpResponse('<div class="text-red-600">Permission denied</div>', status=403)
        messages.error(request, 'You do not have permission to perform this action.')
        return redirect('core:dashboard')
    
    try:
        appointment = get_object_or_404(Appointment, pk=pk)
        
        # Only mark as arrived if appointment is today
        if appointment.appointment_date != timezone.now().date():
            if request.headers.get('HX-Request'):
                return HttpResponse('<div class="text-yellow-600">Can only mark today\'s appointments</div>')
            messages.error(request, 'Can only mark today\'s appointments as arrived.')
            return redirect('appointments:check_in')
        
        # Update status if not already completed
        if appointment.status != 'completed':
            old_status = appointment.status
            
            # Mark as completed (patient arrived and service provided)
            appointment.status = 'completed'
            appointment.save()
            
            # Log the action
            AuditLog.log_action(
                user=request.user,
                action='update',
                model_instance=appointment,
                changes={
                    'status': {'old': old_status, 'new': 'completed', 'label': 'Status'}
                },
                description=f"Marked patient {appointment.patient_name} as arrived and completed check-in",
                request=request
            )
            
            # HTMX Response
            if request.headers.get('HX-Request'):
                # Return updated check-in page section
                response = HttpResponse()
                response['HX-Redirect'] = request.META.get('HTTP_REFERER', reverse('appointments:check_in'))
                return response
            
            messages.success(request, f'Patient {appointment.patient_name} marked as arrived.')
        else:
            if request.headers.get('HX-Request'):
                return HttpResponse('<div class="text-yellow-600">Already checked in</div>')
            messages.info(request, 'Patient already marked as arrived.')
        
    except Exception as e:
        if request.headers.get('HX-Request'):
            return HttpResponse(f'<div class="text-red-600">Error: {str(e)}</div>', status=500)
        messages.error(request, f'Error marking patient as arrived: {str(e)}')
    
    return redirect('appointments:check_in')

# PUBLIC VIEW - No login required (uses token authentication)
def cancel_appointment_confirm(request, token):
    """
    Show cancellation confirmation page
    Accessible via email link - no login required
    """
    try:
        appointment = get_object_or_404(
            Appointment.objects.select_related('patient', 'service', 'assigned_dentist'),
            reschedule_token=token
        )
        
        # Check if appointment can be cancelled
        if appointment.status in ['cancelled', 'completed', 'did_not_arrive']:
            return render(request, 'appointments/cancel_error.html', {
                'error_message': f'This appointment has already been {appointment.get_status_display().lower()}.',
                'appointment': appointment
            })
        
        # Check if cancellation is within allowed timeframe (24 hours before)
        hours_until = (appointment.appointment_datetime - timezone.now()).total_seconds() / 3600
        
        if hours_until < 24:
            return render(request, 'appointments/cancel_error.html', {
                'error_message': 'Appointments can only be cancelled at least 24 hours in advance. Please contact the clinic directly.',
                'appointment': appointment,
                'too_late': True
            })
        
        # Show confirmation page
        context = {
            'appointment': appointment,
            'hours_until': int(hours_until),
            'cancellation_deadline': (appointment.appointment_datetime - timedelta(hours=24)).strftime('%B %d, %Y at %I:%M %p')
        }
        
        return render(request, 'appointments/cancel_confirm.html', context)
        
    except Appointment.DoesNotExist:
        return render(request, 'appointments/cancel_error.html', {
            'error_message': 'Invalid cancellation link. This link may have expired or been used already.'
        })


# PUBLIC VIEW - No login required (uses token authentication)
@require_POST
def cancel_appointment_process(request, token):
    """
    Process appointment cancellation
    Accessible via email link - no login required
    """
    try:
        with transaction.atomic():
            appointment = get_object_or_404(
                Appointment.objects.select_for_update().select_related('patient', 'service'),
                reschedule_token=token
            )
            
            # Validate cancellation eligibility again
            if appointment.status in ['cancelled', 'completed', 'did_not_arrive']:
                return render(request, 'appointments/cancel_error.html', {
                    'error_message': f'This appointment has already been {appointment.get_status_display().lower()}.'
                })
            
            # Check timeframe
            hours_until = (appointment.appointment_datetime - timezone.now()).total_seconds() / 3600
            if hours_until < 24:
                return render(request, 'appointments/cancel_error.html', {
                    'error_message': 'Appointments can only be cancelled at least 24 hours in advance.',
                    'too_late': True
                })
            
            # Get optional cancellation reason
            cancellation_reason = request.POST.get('reason', '').strip()
            
            # Store cancellation info in staff_notes
            old_status = appointment.status
            cancellation_note = f"\n[Patient Self-Cancellation - {timezone.now().strftime('%Y-%m-%d %I:%M %p')}]"
            if cancellation_reason:
                cancellation_note += f"\nReason: {cancellation_reason}"
            
            appointment.staff_notes = (appointment.staff_notes or '') + cancellation_note
            appointment.status = 'cancelled'
            appointment.save()
            
            # Log the cancellation (no user since this is patient-initiated)
            AuditLog.objects.create(
                user=None,  # Patient-initiated, no user
                action='cancel',
                content_type=ContentType.objects.get_for_model(Appointment),
                object_id=appointment.id,
                object_repr=str(appointment),
                changes={
                    'status': {'old': old_status, 'new': 'cancelled', 'label': 'Status'},
                    'cancellation_type': {'old': None, 'new': 'Patient Self-Service', 'label': 'Cancelled By'}
                },
                description=f"Patient {appointment.patient_name} cancelled appointment via email link" + (f" - Reason: {cancellation_reason}" if cancellation_reason else ""),
                ip_address=request.META.get('REMOTE_ADDR'),
                user_agent=request.META.get('HTTP_USER_AGENT', '')[:200]
            )
            
            # Send cancellation confirmation to patient
            EmailService.send_appointment_cancelled_email(appointment, cancelled_by_patient=True)
            
            # Show success page
            context = {
                'appointment': appointment,
                'cancellation_reason': cancellation_reason
            }
            
            return render(request, 'appointments/cancel_success.html', context)
            
    except Appointment.DoesNotExist:
        return render(request, 'appointments/cancel_error.html', {
            'error_message': 'Invalid cancellation link. This link may have expired or been used already.'
        })
    except Exception as e:
        logger.error(f"Error processing cancellation for token {token}: {str(e)}")
        return render(request, 'appointments/cancel_error.html', {
            'error_message': 'An error occurred while processing your cancellation. Please contact the clinic directly.'
        })

@login_required
@require_POST
def approve_appointment(request, pk):
    """ACTION VIEW: Approve pending appointment - HTMX compatible"""
    if not request.user.has_permission('appointments'):
        if request.headers.get('HX-Request'):
            return HttpResponse('<div class="text-red-600">Permission denied</div>', status=403)
        messages.error(request, 'You do not have permission to perform this action.')
        return redirect('core:dashboard')
    
    try:
        with transaction.atomic():
            appointment = get_object_or_404(Appointment.objects.select_for_update(), pk=pk)
            
            if appointment.status != 'pending':
                if request.headers.get('HX-Request'):
                    return HttpResponse('<div class="text-yellow-600">Already processed</div>')
                messages.error(request, 'Only pending appointments can be approved.')
                return redirect('appointments:appointment_detail', pk=pk)
            
            # Check timeslot availability
            can_book, message = Appointment.check_timeslot_availability(
                appointment_date=appointment.appointment_date,
                start_time=appointment.start_time,
                duration_minutes=appointment.service.duration_minutes,
                exclude_appointment_id=appointment.id
            )
            
            if not can_book:
                if request.headers.get('HX-Request'):
                    return HttpResponse(f'<div class="text-red-600">{message}</div>')
                messages.error(request, f'Cannot approve: {message}')
                return redirect('appointments:appointment_detail', pk=pk)
            
            # Check for double-booking
            if appointment.patient:
                conflicting = Appointment.objects.filter(
                    patient=appointment.patient,
                    appointment_date=appointment.appointment_date,
                    status__in=Appointment.BLOCKING_STATUSES
                ).exclude(id=appointment.id)
                
                if conflicting.exists():
                    existing = conflicting.first()
                    formatted_date = appointment.appointment_date.strftime('%B %d, %Y')
                    error_msg = (
                        f'Cannot approve: Patient already has an appointment on {formatted_date} '
                        f'at {existing.start_time.strftime("%I:%M %p")} for {existing.service.name}. '
                        f'Please reschedule or cancel the other appointment first.'
                    )
                    
                    if request.headers.get('HX-Request'):
                        return HttpResponse(f'<div class="text-red-600">{error_msg}</div>')
                    messages.error(request, error_msg)
                    return redirect('appointments:appointment_detail', pk=pk)
            
            # For new patients, check by temp_email
            elif appointment.temp_email:
                conflicting = Appointment.objects.filter(
                    temp_email=appointment.temp_email,
                    appointment_date=appointment.appointment_date,
                    status__in=Appointment.BLOCKING_STATUSES
                ).exclude(id=appointment.id)
                
                if conflicting.exists():
                    existing = conflicting.first()
                    formatted_date = appointment.appointment_date.strftime('%B %d, %Y')
                    error_msg = (
                        f'Cannot approve: This patient (email: {appointment.temp_email}) already has '
                        f'an appointment on {formatted_date} at {existing.start_time.strftime("%I:%M %p")} '
                        f'for {existing.service.name}. Please reschedule or reject one of the requests.'
                    )
                    
                    if request.headers.get('HX-Request'):
                        return HttpResponse(f'<div class="text-red-600">{error_msg}</div>')
                    messages.error(request, error_msg)
                    return redirect('appointments:appointment_detail', pk=pk)
            
            # Get assigned dentist from form
            assigned_dentist_id = request.POST.get('assigned_dentist')
            if assigned_dentist_id:
                try:
                    assigned_dentist = User.objects.get(id=assigned_dentist_id, is_active_dentist=True)
                except User.DoesNotExist:
                    assigned_dentist = None
            else:
                assigned_dentist = User.objects.filter(is_active_dentist=True).first()
            
            patient_name = appointment.patient_name
            patient_email = appointment.patient_email
            was_new_patient = appointment.patient_type == 'new'
            
            appointment.approve(request.user, assigned_dentist)
            
            changes = {
                'status': {'old': 'pending', 'new': 'confirmed', 'label': 'Status'},
                'assigned_dentist': {
                    'old': None, 
                    'new': assigned_dentist.full_name if assigned_dentist else 'Unassigned',
                    'label': 'Assigned Dentist'
                }
            }
            
            if was_new_patient:
                changes['patient_created'] = {
                    'old': None,
                    'new': f'Created patient record for {patient_name}',
                    'label': 'Patient Record'
                }
            
            description = f"Approved appointment for {patient_name} on {appointment.appointment_date.strftime('%B %d, %Y')} at {appointment.start_time.strftime('%I:%M %p')}"
            if was_new_patient:
                description += " (new patient)"
            if assigned_dentist:
                description += f" and assigned to Dr. {assigned_dentist.get_full_name()}"
            
            AuditLog.log_action(
                user=request.user,
                action='approve',
                model_instance=appointment,
                changes=changes,
                description=description,
                request=request
            )
            
            email_sent = EmailService.send_appointment_approved_email(appointment)
            
            # HTMX Response
            if request.headers.get('HX-Request'):
                success_html = f'''
                <div class="bg-green-50 border border-green-200 rounded-lg p-4 text-sm">
                    <div class="flex items-center">
                        <span class="text-green-600 mr-2">✓</span>
                        <span class="text-green-800">Approved appointment for {patient_name}</span>
                    </div>
                </div>
                '''
                response = HttpResponse(success_html)
                response['HX-Trigger'] = 'appointmentApproved'
                return response
            
            if email_sent:
                messages.success(request, f'Appointment for {patient_name} has been approved and confirmation email sent.')
            else:
                messages.success(request, f'Appointment for {patient_name} has been approved.')
                messages.warning(request, 'Failed to send confirmation email. Please contact the patient manually.')
            
    except Exception as e:
        if request.headers.get('HX-Request'):
            return HttpResponse(f'<div class="text-red-600">Error: {str(e)}</div>', status=500)
        messages.error(request, f'Error approving appointment: {str(e)}')
    
    return redirect('appointments:appointment_detail', pk=pk)


@login_required
@require_POST
def reject_appointment(request, pk):
    """ACTION VIEW: Reject pending appointment - HTMX compatible"""
    if not request.user.has_permission('appointments'):
        if request.headers.get('HX-Request'):
            return HttpResponse('<div class="text-red-600">Permission denied</div>', status=403)
        messages.error(request, 'You do not have permission to perform this action.')
        return redirect('core:dashboard')
    
    try:
        with transaction.atomic():
            appointment = get_object_or_404(Appointment.objects.select_for_update(), pk=pk)
            
            if appointment.status != 'pending':
                if request.headers.get('HX-Request'):
                    return HttpResponse('<div class="text-yellow-600">Already processed</div>')
                messages.error(request, 'Only pending appointments can be rejected.')
                return redirect('appointments:appointment_detail', pk=pk)
            
            patient_name = appointment.patient_name
            old_status = appointment.status
            
            appointment._skip_audit_log = True
            appointment.reject()
            
            AuditLog.log_action(
                user=request.user,
                action='reject',
                model_instance=appointment,
                changes={
                    'status': {'old': old_status, 'new': 'rejected', 'label': 'Status'}
                },
                description=f"Rejected appointment request from {patient_name} for {appointment.appointment_date.strftime('%B %d, %Y')} at {appointment.start_time.strftime('%I:%M %p')}",
                request=request
            )
            
            email_sent = EmailService.send_appointment_rejected_email(appointment)
            
            # HTMX Response
            if request.headers.get('HX-Request'):
                success_html = f'''
                <div class="bg-red-50 border border-red-200 rounded-lg p-4 text-sm">
                    <div class="flex items-center">
                        <span class="text-red-600 mr-2">✗</span>
                        <span class="text-red-800">Rejected appointment for {patient_name}</span>
                    </div>
                </div>
                '''
                response = HttpResponse(success_html)
                response['HX-Trigger'] = 'appointmentRejected'
                return response
            
            if email_sent:
                messages.success(request, f'Appointment for {patient_name} has been rejected and notification email sent.')
            else:
                messages.success(request, f'Appointment for {patient_name} has been rejected.')
                messages.warning(request, 'Failed to send notification email.')
            
    except Exception as e:
        if request.headers.get('HX-Request'):
            return HttpResponse(f'<div class="text-red-600">Error: {str(e)}</div>', status=500)
        messages.error(request, f'Error rejecting appointment: {str(e)}')
    
    return redirect('appointments:appointment_requests')


@login_required
@require_POST
def update_appointment_status(request, pk):
    """ACTION VIEW: Update appointment status via dropdown"""
    if not request.user.has_permission('appointments'):
        messages.error(request, 'You do not have permission to perform this action.')
        return redirect('core:dashboard')
    
    try:
        with transaction.atomic():
            appointment = get_object_or_404(Appointment.objects.select_for_update(), pk=pk)
            new_status = request.POST.get('status')
            
            # Date validation for completed and did_not_arrive statuses
            today = timezone.now().date()
            if new_status in ['completed', 'did_not_arrive']:
                if appointment.appointment_date > today:
                    status_display = dict(Appointment.STATUS_CHOICES).get(new_status, new_status)
                    messages.error(
                        request,
                        f'Cannot mark appointment as "{status_display}" for future dates. '
                        f'This appointment is scheduled for {appointment.appointment_date.strftime("%B %d, %Y")}.'
                    )
                    return redirect('appointments:appointment_detail', pk=pk)
            
            # Status validation rules
            valid_transitions = {
                'confirmed': ['cancelled', 'completed', 'did_not_arrive'],
                'cancelled': ['confirmed'],
                'completed': [],
                'did_not_arrive': ['confirmed'],
            }
            
            current_status = appointment.status
            
            # Check if transition is allowed
            if new_status not in valid_transitions.get(current_status, []):
                messages.error(
                    request, 
                    f'Cannot change status from {appointment.get_status_display()} to {dict(Appointment.STATUS_CHOICES).get(new_status, new_status)}'
                )
                return redirect('appointments:appointment_detail', pk=pk)
            
            # Additional validation for cancellation
            if new_status == 'cancelled' and not appointment.can_be_cancelled:
                messages.error(request, 'This appointment cannot be cancelled.')
                return redirect('appointments:appointment_detail', pk=pk)
            
            # Store old status and patient info for logging and email
            old_status = appointment.status
            patient_name = appointment.patient_name
            patient_email = appointment.patient_email
            
            # Update status
            appointment.status = new_status
            appointment.save(update_fields=['status'])
            
            # Log the action
            AuditLog.log_action(
                user=request.user,
                action='status_change',
                model_instance=appointment,
                changes={
                    'old_status': old_status,
                    'new_status': new_status
                },
                request=request
            )
            
            # Send email notification for cancellation
            email_sent = False
            if new_status == 'cancelled':
                email_sent = EmailService.send_appointment_cancelled_email(
                    appointment, 
                    cancelled_by_patient=False
                )
            
            # NEW: Check if invoice already exists before prompting
            if new_status == 'completed':
                existing_invoice = Payment.objects.filter(appointment=appointment).exists()
                
                if not existing_invoice:
                    # Store a session flag to show the invoice creation modal
                    request.session['show_invoice_modal'] = True
                    request.session['invoice_appointment_id'] = appointment.id
            
            # Success message
            status_display = appointment.get_status_display()
            if email_sent:
                messages.success(
                    request, 
                    f'Appointment for {patient_name} has been marked as {status_display.lower()} and notification email sent.'
                )
            else:
                messages.success(
                    request, 
                    f'Appointment for {patient_name} has been marked as {status_display.lower()}.'
                )
                if new_status == 'cancelled' and patient_email:
                    messages.warning(request, 'Failed to send cancellation email.')
            
    except Exception as e:
        messages.error(request, f'Error updating appointment status: {str(e)}')
    
    return redirect('appointments:appointment_detail', pk=pk)

# ============================================================================
# SECTION 6: BACKEND - TIMESLOT CONFIGURATION MANAGEMENT
# ============================================================================

class TimeSlotConfigurationListView(LoginRequiredMixin, ListView):
    """
    BACKEND VIEW: Manage daily timeslot configurations
    Template: appointments/daily_slots_list.html
    Users: Admin, Staff with permission
    Features: View configurations, availability stats, filter by date range
    """
    model = TimeSlotConfiguration
    template_name = 'appointments/daily_slots_list.html'
    context_object_name = 'configurations'
    paginate_by = 30
    
    def dispatch(self, request, *args, **kwargs):
        if not request.user.has_permission('appointments.view_timeslotconfiguration'):
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('core:dashboard')
        return super().dispatch(request, *args, **kwargs)
    
    def get_queryset(self):
        queryset = TimeSlotConfiguration.objects.all()
        
        date_from = self.request.GET.get('date_from')
        date_to = self.request.GET.get('date_to')
        
        # If no filters provided, default to next 90 days
        if not date_from and not date_to:
            today = timezone.now().date()
            queryset = queryset.filter(
                date__gte=today,
                date__lte=today + timedelta(days=90)
            )
        else:
            if date_from:
                try:
                    date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
                    queryset = queryset.filter(date__gte=date_from_obj)
                except ValueError:
                    pass
            
            if date_to:
                try:
                    date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
                    queryset = queryset.filter(date__lte=date_to_obj)
                except ValueError:
                    pass
        
        return queryset.order_by('date')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Enhance configurations with availability data
        enhanced_configs = []
        for config in context['configurations']:
            # Get available slots for 30-minute baseline
            available_slots = config.get_available_slots(30, include_pending=False)
            pending_count = config.get_pending_count()
            
            config.available_slots_count = len(available_slots)
            config.total_slots = len(config.get_all_timeslots())
            config.pending_count = pending_count
            
            enhanced_configs.append(config)
        
        context['configurations'] = enhanced_configs
        context['filters'] = {
            'date_from': self.request.GET.get('date_from', ''),
            'date_to': self.request.GET.get('date_to', ''),
        }
        
        # Add info message about default range
        today = timezone.now().date()
        if not self.request.GET.get('date_from') and not self.request.GET.get('date_to'):
            end_range = today + timedelta(days=90)
            context['default_range_info'] = f"Showing configurations from {today.strftime('%b %d, %Y')} to {end_range.strftime('%b %d, %Y')}"
        
        return context


class TimeSlotConfigurationCreateView(LoginRequiredMixin, CreateView):
    """
    BACKEND VIEW: Create timeslot configuration for single date
    Template: appointments/daily_slots_form.html
    Users: Admin, Staff with permission
    Features: Set operating hours (start/end time) for a specific date
    """
    model = TimeSlotConfiguration
    form_class = TimeSlotConfigurationForm
    template_name = 'appointments/daily_slots_form.html'
    
    def dispatch(self, request, *args, **kwargs):
        if not request.user.has_permission('appointments.add_timeslotconfiguration'):
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('core:dashboard')
        return super().dispatch(request, *args, **kwargs)
    
    def form_valid(self, form):
        form.instance.created_by = self.request.user
        
        # Check if configuration already exists for this date
        date_value = form.cleaned_data.get('date')
        if TimeSlotConfiguration.objects.filter(date=date_value).exists():
            form.add_error('date', 'Configuration already exists for this date. Use the Edit option to modify it.')
            return self.form_invalid(form)
        
        response = super().form_valid(form)
        
        messages.success(
            self.request,
            f'Timeslot configuration for {form.instance.date.strftime("%A, %b %d, %Y")} '
            f'({form.instance.start_time.strftime("%I:%M %p")} - {form.instance.end_time.strftime("%I:%M %p")}) '
            f'created successfully.'
        )
        return response
    
    def get_success_url(self):
        return reverse_lazy('appointments:daily_slots_list')


class TimeSlotConfigurationUpdateView(LoginRequiredMixin, UpdateView):
    """
    BACKEND VIEW: Edit timeslot configuration for single date
    Template: appointments/daily_slots_form.html
    Users: Admin, Staff with permission
    Features: Modify operating hours for existing date
    """
    model = TimeSlotConfiguration
    form_class = TimeSlotConfigurationForm
    template_name = 'appointments/daily_slots_form.html'
    
    def dispatch(self, request, *args, **kwargs):
        if not request.user.has_permission('appointments.change_timeslotconfiguration'):
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('core:dashboard')
        return super().dispatch(request, *args, **kwargs)
    
    def form_valid(self, form):
        response = super().form_valid(form)
        
        messages.success(
            self.request,
            f'Timeslot configuration for {form.instance.date.strftime("%A, %b %d, %Y")} updated successfully.'
        )
        return response
    
    def get_success_url(self):
        return reverse_lazy('appointments:daily_slots_list')


@login_required
@require_POST
def bulk_create_timeslot_configs_preview(request):
    """
    AJAX: Preview bulk timeslot creation for date range
    Users: Admin, Staff with permission
    Returns: JSON with creation plan (what will be created/skipped)
    Used for: Bulk creation confirmation modal
    """
    if not request.user.has_permission('appointments.add_timeslotconfiguration'):
        return JsonResponse({'error': 'Permission denied'}, status=403)
    
    try:
        start_date_str = request.POST.get('start_date')
        end_date_str = request.POST.get('end_date')
        start_time_str = request.POST.get('start_time')
        end_time_str = request.POST.get('end_time')
        
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        start_time = datetime.strptime(start_time_str, '%H:%M').time()
        end_time = datetime.strptime(end_time_str, '%H:%M').time()
        
        if start_date > end_date:
            return JsonResponse({'error': 'Start date must be before end date'}, status=400)
        
        if start_time >= end_time:
            return JsonResponse({'error': 'Start time must be before end time'}, status=400)
        
        # Calculate what will be created
        to_create = []
        to_skip = []
        skipped_sundays = 0
        
        current_date = start_date
        while current_date <= end_date:
            if current_date.weekday() == 6:  # Sunday
                skipped_sundays += 1
            elif TimeSlotConfiguration.objects.filter(date=current_date).exists():
                to_skip.append({
                    'date': current_date.strftime('%Y-%m-%d'),
                    'day_name': current_date.strftime('%A'),
                    'reason': 'Already exists'
                })
            else:
                # Calculate number of slots
                start_dt = datetime.combine(date.today(), start_time)
                end_dt = datetime.combine(date.today(), end_time)
                duration_minutes = (end_dt - start_dt).total_seconds() / 60
                num_slots = int(duration_minutes / 30)
                
                to_create.append({
                    'date': current_date.strftime('%Y-%m-%d'),
                    'day_name': current_date.strftime('%A'),
                    'start_time': start_time.strftime('%I:%M %p'),
                    'end_time': end_time.strftime('%I:%M %p'),
                    'num_slots': num_slots
                })
            
            current_date += timedelta(days=1)
        
        return JsonResponse({
            'success': True,
            'summary': {
                'will_create': len(to_create),
                'will_skip': len(to_skip),
                'skipped_sundays': skipped_sundays,
                'total_days_in_range': (end_date - start_date).days + 1
            },
            'to_create': to_create,
            'to_skip': to_skip,
            'start_date': start_date.strftime('%b %d, %Y'),
            'end_date': end_date.strftime('%b %d, %Y'),
            'time_range': f"{start_time.strftime('%I:%M %p')} - {end_time.strftime('%I:%M %p')}"
        })
    
    except ValueError as e:
        return JsonResponse({'error': f'Invalid input: {str(e)}'}, status=400)
    except Exception as e:
        return JsonResponse({'error': f'An error occurred: {str(e)}'}, status=500)


@login_required
@require_POST
def bulk_create_timeslot_configs_confirm(request):
    """
    ACTION: Execute bulk timeslot creation after preview
    Users: Admin, Staff with permission
    Features: Creates timeslots for date range, skips Sundays/existing
    Redirects to: daily_slots_list
    """
    if not request.user.has_permission('appointments.add_timeslotconfiguration'):
        messages.error(request, 'You do not have permission to perform this action.')
        return redirect('appointments:daily_slots_list')
    
    try:
        start_date_str = request.POST.get('start_date')
        end_date_str = request.POST.get('end_date')
        start_time_str = request.POST.get('start_time')
        end_time_str = request.POST.get('end_time')
        
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        start_time = datetime.strptime(start_time_str, '%H:%M').time()
        end_time = datetime.strptime(end_time_str, '%H:%M').time()
        
        created_count = 0
        current_date = start_date
        
        with transaction.atomic():
            while current_date <= end_date:
                if current_date.weekday() != 6:  # Skip Sundays
                    config, created = TimeSlotConfiguration.objects.get_or_create(
                        date=current_date,
                        defaults={
                            'start_time': start_time,
                            'end_time': end_time,
                            'created_by': request.user
                        }
                    )
                    
                    if created:
                        created_count += 1
                
                current_date += timedelta(days=1)
        
        if created_count > 0:
            messages.success(
                request,
                f'Successfully created timeslot configurations for {created_count} working days '
                f'({start_date.strftime("%b %d")} - {end_date.strftime("%b %d, %Y")}) '
                f'with hours {start_time.strftime("%I:%M %p")} - {end_time.strftime("%I:%M %p")}.'
            )
        else:
            messages.warning(
                request,
                f'No new configurations created. All dates in this range already have configurations or fell on Sundays.'
            )
    
    except ValueError:
        messages.error(request, 'Invalid date or time format.')
    except Exception as e:
        messages.error(request, f'Error creating configurations: {str(e)}')
    
    return redirect('appointments:daily_slots_list')



# ============================================================================
# SECTION 8: API ENDPOINTS - PUBLIC & BACKEND
# ============================================================================

@require_http_methods(["GET"])
def get_timeslot_availability_api(request):
    """
    PUBLIC API: Get timeslot availability for date range
    Used by: Public booking page (JavaScript calendar)
    Query params: start_date, end_date, service_id/duration
    Returns: JSON with available dates and slot counts
    """
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    service_id = request.GET.get('service_id')
    duration_str = request.GET.get('duration', '30')
    
    if not start_date_str or not end_date_str:
        return JsonResponse({'error': 'start_date and end_date are required'}, status=400)
    
    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
    except ValueError:
        return JsonResponse({'error': 'Invalid date format. Use YYYY-MM-DD'}, status=400)
    
    # Validate date range
    today = timezone.now().date()
    
    # Adjust start_date if in the past
    if start_date < today:
        start_date = today
    
    if end_date < start_date:
        return JsonResponse({'error': 'End date must be after or equal to start date'}, status=400)
    
    # Limit range to prevent excessive queries
    if (end_date - start_date).days > 90:
        return JsonResponse({'error': 'Date range too large. Maximum 90 days.'}, status=400)
    
    # Determine service duration
    if service_id:
        try:
            from services.models import Service
            service = Service.objects.get(id=service_id, is_archived=False)
            duration_minutes = service.duration_minutes
        except Service.DoesNotExist:
            return JsonResponse({'error': 'Invalid service ID'}, status=400)
    else:
        try:
            duration_minutes = int(duration_str)
            if duration_minutes % 30 != 0:
                return JsonResponse({'error': 'Duration must be in 30-minute increments'}, status=400)
        except ValueError:
            return JsonResponse({'error': 'Invalid duration'}, status=400)
    
    # Get availability for date range
    availability = TimeSlotConfiguration.get_availability_for_range(
        start_date, 
        end_date,
        service_duration_minutes=duration_minutes,
        include_pending=True  # For public booking
    )
    
    # Format for frontend
    formatted_availability = {}
    for date_obj, data in availability.items():
        date_str = date_obj.strftime('%Y-%m-%d')
        
        # Skip Sundays and past dates
        if date_obj.weekday() == 6 or date_obj < today:
            continue
        
        if data['has_config']:
            formatted_availability[date_str] = {
                'date': date_str,
                'weekday': date_obj.strftime('%A'),
                'has_config': True,
                'start_time': data['start_time'],
                'end_time': data['end_time'],
                'available_slots': data['available_slots'],
                'available_count': data['available_count'],
                'total_slots': data['total_slots'],
                'has_availability': data['available_count'] > 0
            }
        else:
            formatted_availability[date_str] = {
                'date': date_str,
                'weekday': date_obj.strftime('%A'),
                'has_config': False,
                'available_count': 0,
                'has_availability': False
            }
    
    return JsonResponse({
        'availability': formatted_availability,
        'date_range': {
            'start': start_date_str,
            'end': end_date_str,
            'adjusted_start': start_date.strftime('%Y-%m-%d') if start_date.strftime('%Y-%m-%d') != start_date_str else None
        },
        'duration_minutes': duration_minutes
    })


@require_http_methods(["GET"])
def get_timeslots_for_date_api(request):
    """
    PUBLIC API: Get available timeslots for specific date and service
    Used by: Public booking page (timeslot dropdown)
    Query params: date, service_id
    Returns: JSON with list of available start times
    """
    date_str = request.GET.get('date')
    service_id = request.GET.get('service_id')
    
    if not date_str or not service_id:
        return JsonResponse({'error': 'date and service_id are required'}, status=400)
    
    try:
        appointment_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return JsonResponse({'error': 'Invalid date format. Use YYYY-MM-DD'}, status=400)
    
    try:
        from services.models import Service
        service = Service.objects.get(id=service_id, is_archived=False)
    except Service.DoesNotExist:
        return JsonResponse({'error': 'Invalid service ID'}, status=400)
    
    # Get configuration for date
    config = TimeSlotConfiguration.get_for_date(appointment_date)
    
    if not config:
        return JsonResponse({
            'error': f'No timeslots configured for {appointment_date.strftime("%B %d, %Y")}',
            'has_config': False
        })
    
    # Get available slots
    available_slots = config.get_available_slots(
        service.duration_minutes,
        include_pending=True
    )
    
    # Format slots for display
    formatted_slots = []
    for slot_time in available_slots:
        # Calculate end time
        start_dt = datetime.combine(date.today(), slot_time)
        end_dt = start_dt + timedelta(minutes=service.duration_minutes)
        
        formatted_slots.append({
            'value': slot_time.strftime('%H:%M:%S'),
            'display': slot_time.strftime('%I:%M %p'),
            'end_time': end_dt.time().strftime('%I:%M %p'),
            'time_range': f"{slot_time.strftime('%I:%M %p')} - {end_dt.time().strftime('%I:%M %p')}"
        })
    
    return JsonResponse({
        'date': date_str,
        'has_config': True,
        'config': {
            'start_time': config.start_time.strftime('%I:%M %p'),
            'end_time': config.end_time.strftime('%I:%M %p')
        },
        'service': {
            'id': service.id,
            'name': service.name,
            'duration_minutes': service.duration_minutes,
            'duration_display': service.duration_display
        },
        'available_slots': formatted_slots,
        'available_count': len(formatted_slots)
    })


@require_http_methods(["GET"])
def find_patient_api(request):
    """
    PUBLIC/BACKEND API: Find patient by email/phone or autocomplete search
    Used by: Public booking (existing patient), Backend appointment form
    Query params: identifier, type (exact/autocomplete)
    Returns: JSON with patient data or list of matches
    """
    if request.method != 'GET':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    identifier = request.GET.get('identifier', '').strip()
    search_type = request.GET.get('type', 'exact')  # 'exact' or 'autocomplete'
    
    if not identifier or len(identifier) < 2:
        return JsonResponse({'found': False, 'patients': []})
    
    # AUTOCOMPLETE MODE: Return list of matching patients
    if search_type == 'autocomplete':
        # Split search query into words for full name search
        search_words = identifier.lower().split()
        
        if len(search_words) == 1:
            # Single word: search in first name OR last name
            patients = Patient.objects.filter(
                is_active=True
            ).filter(
                Q(first_name__icontains=identifier) |
                Q(last_name__icontains=identifier)
            ).select_related().order_by('last_name', 'first_name')[:10]
        else:
            # Multiple words: search for full name combinations
            first_word = search_words[0]
            second_word = search_words[1]
            
            patients = Patient.objects.filter(
                is_active=True
            ).filter(
                # Match "first last" order
                (Q(first_name__icontains=first_word) & Q(last_name__icontains=second_word)) |
                # Match "last first" order (reversed)
                (Q(last_name__icontains=first_word) & Q(first_name__icontains=second_word))
            ).select_related().order_by('last_name', 'first_name')[:10]
        
        patient_list = [{
            'id': p.id,
            'name': p.full_name,
            'email': p.email or 'No email',
            'contact_number': p.contact_number or 'No phone'
        } for p in patients]
        
        return JsonResponse({
            'patients': patient_list,
            'count': len(patient_list)
        })
    
    # EXACT MODE: Original functionality for booking form
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


@login_required
@require_http_methods(["GET"])
def check_double_booking_api(request):
    """
    BACKEND API: Check if patient already has appointment on date
    Used by: Backend appointment form (JavaScript validation)
    Query params: patient_id, date, exclude_id
    Returns: JSON with conflict status and details
    """
    patient_id = request.GET.get('patient_id')
    date_str = request.GET.get('date')
    exclude_id = request.GET.get('exclude_id')
    
    if not patient_id or not date_str:
        return JsonResponse({
            'error': 'Missing required parameters'
        }, status=400)
    
    try:
        # Parse date
        appointment_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        
        # Get patient
        patient = Patient.objects.get(id=patient_id, is_active=True)
        
        # Check for existing appointments on this date
        conflicting_appointments = Appointment.objects.filter(
            patient=patient,
            appointment_date=appointment_date,
            status__in=Appointment.BLOCKING_STATUSES
        )
        
        # Exclude current appointment if editing
        if exclude_id:
            conflicting_appointments = conflicting_appointments.exclude(id=exclude_id)
        
        if conflicting_appointments.exists():
            existing = conflicting_appointments.first()
            formatted_date = appointment_date.strftime('%B %d, %Y')
            
            return JsonResponse({
                'has_conflict': True,
                'message': f'This patient already has an appointment on {formatted_date} at {existing.start_time.strftime("%I:%M %p")} for {existing.service.name}. Please choose a different date or time.',
                'existing_appointment': {
                    'id': existing.id,
                    'date': existing.appointment_date.isoformat(),
                    'start_time': existing.start_time.strftime('%H:%M:%S'),
                    'time_display': existing.time_display,
                    'service': existing.service.name,
                    'status': existing.get_status_display()
                }
            })
        else:
            return JsonResponse({
                'has_conflict': False,
                'message': 'No conflicts found'
            })
            
    except Patient.DoesNotExist:
        return JsonResponse({
            'error': 'Patient not found'
        }, status=404)
    except ValueError:
        return JsonResponse({
            'error': 'Invalid date format'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'error': str(e)
        }, status=500)


@login_required
@require_http_methods(["GET"])
def pending_count_api(request):
    """
    BACKEND API: Get count of pending appointments
    Used by: Sidebar notification badge (auto-refresh every 45 seconds)
    Returns: JSON with pending count
    """
    # Check if user has appointments permission
    if not (request.user.is_superuser or request.user.has_perm('appointments.view_appointment')):
        return JsonResponse({'error': 'Permission denied'}, status=403)
    
    pending_count = Appointment.objects.filter(status='pending').count()
    
    return JsonResponse({
        'pending_count': pending_count,
        'success': True
    })


# View name aliases for URL routing compatibility
DailySlotsManagementView = TimeSlotConfigurationListView
DailySlotsCreateView = TimeSlotConfigurationCreateView
DailySlotsUpdateView = TimeSlotConfigurationUpdateView
bulk_create_daily_slots_preview = bulk_create_timeslot_configs_preview
bulk_create_daily_slots_confirm = bulk_create_timeslot_configs_confirm
get_slot_availability_api = get_timeslot_availability_api

@login_required
@require_POST
def update_treatment_record_notes(request, appointment_pk):
    """
    Update treatment record clinical notes via AJAX
    Only the assigned dentist can edit
    """
    if not request.user.has_permission('patients'):
        return JsonResponse({'error': 'Permission denied'}, status=403)
    
    appointment = get_object_or_404(
        Appointment.objects.select_related('assigned_dentist', 'treatment_record'),
        pk=appointment_pk
    )
    
    # Check if appointment has a treatment record
    if not hasattr(appointment, 'treatment_record'):
        return JsonResponse({
            'error': 'No treatment record found. Treatment records are created when appointments are confirmed.'
        }, status=400)
    
    treatment_record = appointment.treatment_record
    
    # Permission check: Only assigned dentist can edit
    if not treatment_record.can_edit(request.user):
        return JsonResponse({
            'error': 'Only the assigned dentist can edit clinical notes for this appointment.'
        }, status=403)
    
    try:
        data = json.loads(request.body)
        clinical_notes = data.get('clinical_notes', '').strip()
        
        # Update clinical notes
        treatment_record.clinical_notes = clinical_notes
        treatment_record.last_modified_by = request.user
        treatment_record.save(update_fields=['clinical_notes', 'last_modified_by', 'updated_at'])
        
        return JsonResponse({
            'success': True,
            'message': 'Clinical notes updated successfully',
            'clinical_notes': clinical_notes,
            'last_modified_by': request.user.get_full_name() or request.user.username,
            'updated_at': treatment_record.updated_at.strftime('%b %d, %Y at %I:%M %p')
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON data'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def get_treatment_record_notes(request, appointment_pk):
    """
    Get treatment record details via AJAX
    Anyone with patients permission can view
    """
    if not request.user.has_permission('patients'):
        return JsonResponse({'error': 'Permission denied'}, status=403)
    
    appointment = get_object_or_404(
        Appointment.objects.select_related(
            'assigned_dentist',
            'treatment_record__created_by',
            'treatment_record__last_modified_by',
            'service',
            'patient'
        ).prefetch_related(
            'treatment_record__service_records__service'
        ),
        pk=appointment_pk
    )
    
    # Check if appointment has a treatment record
    if not hasattr(appointment, 'treatment_record'):
        return JsonResponse({
            'error': 'No treatment record found',
            'has_treatment_record': False
        })
    
    treatment_record = appointment.treatment_record
    
    # Get services performed
    services_performed = [
        {
            'name': sr.service.name,
            'notes': sr.notes
        }
        for sr in treatment_record.service_records.all()
    ]
    
    return JsonResponse({
        'success': True,
        'has_treatment_record': True,
        'appointment_id': appointment.pk,
        'clinical_notes': treatment_record.clinical_notes,
        'services_performed': services_performed,
        'patient_name': appointment.patient_name,
        'appointment_date': appointment.appointment_date.strftime('%B %d, %Y'),
        'time_display': appointment.time_display,
        'assigned_dentist': appointment.assigned_dentist.get_full_name() if appointment.assigned_dentist else 'Not assigned',
        'created_by': treatment_record.created_by.get_full_name() if treatment_record.created_by else 'Unknown',
        'last_modified_by': treatment_record.last_modified_by.get_full_name() if treatment_record.last_modified_by else 'Unknown',
        'created_at': treatment_record.created_at.strftime('%b %d, %Y at %I:%M %p'),
        'updated_at': treatment_record.updated_at.strftime('%b %d, %Y at %I:%M %p'),
        'can_edit': treatment_record.can_edit(request.user)
    })

@login_required
def treatment_record_view(request, appointment_pk):
    """View/Create/Update treatment record for an appointment"""
    appointment = get_object_or_404(
        Appointment.objects.select_related('patient', 'service', 'assigned_dentist'),
        pk=appointment_pk
    )
    
    # Check permissions
    if not hasattr(request.user, 'has_permission') or not request.user.has_permission('appointments'):
        messages.error(request, 'You do not have permission to access this page.')
        return redirect('core:dashboard')
    
    # Get or create treatment record
    treatment_record = None
    try:
        treatment_record = appointment.treatment_record
    except TreatmentRecord.DoesNotExist:
        pass
    
    # Check if user can edit (only assigned dentist or admin)
    can_edit = request.user.is_superuser or appointment.assigned_dentist == request.user
    
    if not can_edit and treatment_record:
        messages.warning(request, 'Only the assigned dentist can edit treatment notes.')
        return redirect('appointments:appointment_detail', pk=appointment.pk)
    
    if request.method == 'POST':
        if not can_edit:
            messages.error(request, 'You do not have permission to edit this treatment record.')
            return redirect('appointments:appointment_detail', pk=appointment.pk)
        
        form = TreatmentRecordForm(
            request.POST,
            instance=treatment_record,
            appointment=appointment,
            user=request.user
        )
        
        if form.is_valid():
            try:
                treatment_record = form.save()
                messages.success(request, 'Treatment notes saved successfully.')
                return redirect('appointments:appointment_detail', pk=appointment.pk)
            except Exception as e:
                messages.error(request, f'Error saving treatment notes: {str(e)}')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')
    else:
        form = TreatmentRecordForm(
            instance=treatment_record,
            appointment=appointment,
            user=request.user
        )
    
    # Get available services and products
    services_data = []
    for service in Service.active.all():
        services_data.append({
            'id': service.id,
            'name': service.name,
        })
    
    products_data = []
    for product in Product.objects.filter(is_active=True).select_related('category'):
        products_data.append({
            'id': product.id,
            'name': product.name,
            'category_id': product.category.id,
            'category_name': product.category.name,
        })
    
    categories_data = []
    for category in ProductCategory.objects.all():
        categories_data.append({
            'id': category.id,
            'name': category.name,
        })
    
    # Get audit logs if editing
    audit_logs = []
    if treatment_record:
        audit_logs = treatment_record.audit_logs.select_related('modified_by').order_by('-modified_at')[:10]
    
    context = {
        'appointment': appointment,
        'treatment_record': treatment_record,
        'form': form,
        'can_edit': can_edit,
        'services_json': json.dumps(services_data),
        'products_json': json.dumps(products_data),
        'categories_json': json.dumps(categories_data),
        'audit_logs': audit_logs,
    }
    
    return render(request, 'appointments/treatment_record_form.html', context)


@login_required
def delete_treatment_record(request, appointment_pk):
    
    """Delete treatment record (admin only or assigned dentist)"""
    appointment = get_object_or_404(Appointment, pk=appointment_pk)
    
    if not hasattr(request.user, 'has_permission') or not request.user.has_permission('appointments'):
        messages.error(request, 'You do not have permission to access this page.')
        return redirect('core:dashboard')
    
    try:
        treatment_record = appointment.treatment_record
    except TreatmentRecord.DoesNotExist:
        messages.error(request, 'No treatment record found.')
        return redirect('appointments:appointment_detail', pk=appointment.pk)
    
    # Check permissions
    if not (request.user.is_superuser or appointment.assigned_dentist == request.user):
        messages.error(request, 'Only the assigned dentist can delete treatment notes.')
        return redirect('appointments:appointment_detail', pk=appointment.pk)
    
    if request.method == 'POST':
        # Create final audit log before deletion
        TreatmentRecordAuditLog.objects.create(
            treatment_record=treatment_record,
            modified_by=request.user,
            action='deleted',
            changes={
                'deleted_at': timezone.now().isoformat(),
                'clinical_notes': treatment_record.clinical_notes
            }
        )
        
        treatment_record.delete()
        messages.success(request, 'Treatment record deleted successfully.')
        return redirect('appointments:appointment_detail', pk=appointment.pk)
    
    return redirect('appointments:appointment_detail', pk=appointment.pk)