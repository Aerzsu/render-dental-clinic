# patient_portal/views.py
"""
Patient portal views for authentication and appointment management
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.views.generic import TemplateView, View
from django.http import JsonResponse
from django.utils import timezone
from django.db.models import Sum, Q
from django.views.decorators.http import require_POST
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from .models import PatientPortalAccess, PatientPortalSession
from patients.models import Patient
from appointments.models import Appointment
from core.email_service import EmailService
from core.models import AuditLog


def get_client_ip(request):
    """Get client IP address from request"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


class PatientPortalLoginView(TemplateView):
    """Patient portal login - request verification code"""
    template_name = 'patient_portal/login.html'
    
    def post(self, request):
        email = request.POST.get('email', '').strip().lower()
        
        if not email:
            messages.error(request, 'Please enter your email address.')
            return render(request, self.template_name)
        
        # Check if patient exists
        try:
            patient = Patient.objects.get(email__iexact=email, is_active=True)
        except Patient.DoesNotExist:
            messages.error(request, 'No patient record found with this email address.')
            return render(request, self.template_name)
        
        # Create access code
        ip_address = get_client_ip(request)
        access_code, created = PatientPortalAccess.create_access_code(email, ip_address)
        
        if not created:
            messages.error(request, 'Too many verification requests. Please try again in an hour.')
            return render(request, self.template_name)
        
        # Send verification email
        email_sent = EmailService.send_verification_code_email(
            email=email,
            code=access_code.code,
            patient_name=patient.full_name
        )
        
        if email_sent:
            # Store email in session for verification step
            request.session['portal_email'] = email
            messages.success(request, f'Verification code sent to {email}. Please check your email.')
            return redirect('patient_portal:verify_code')
        else:
            messages.error(request, 'Failed to send verification code. Please try again.')
            return render(request, self.template_name)


class PatientPortalVerifyView(TemplateView):
    """Verify code and create session"""
    template_name = 'patient_portal/verify_code.html'
    
    def get(self, request):
        # Check if email is in session
        if 'portal_email' not in request.session:
            messages.error(request, 'Please request a verification code first.')
            return redirect('patient_portal:login')
        
        return render(request, self.template_name, {
            'email': request.session.get('portal_email')
        })
    
    def post(self, request):
        email = request.session.get('portal_email')
        
        if not email:
            messages.error(request, 'Session expired. Please request a new verification code.')
            return redirect('patient_portal:login')
        
        code = request.POST.get('code', '').strip()
        
        if not code:
            messages.error(request, 'Please enter the verification code.')
            return render(request, self.template_name, {'email': email})
        
        # Verify code
        is_valid, result = PatientPortalAccess.verify_code(email, code)
        
        if not is_valid:
            messages.error(request, result)  # result contains error message
            return render(request, self.template_name, {'email': email})
        
        # Mark code as used
        access_code = result
        access_code.mark_as_used()
        
        # Get patient
        try:
            patient = Patient.objects.get(email__iexact=email, is_active=True)
        except Patient.DoesNotExist:
            messages.error(request, 'Patient record not found.')
            return redirect('patient_portal:login')
        
        # Create portal session
        ip_address = get_client_ip(request)
        portal_session = PatientPortalSession.create_session(email, patient, ip_address)
        
        # Store session key in Django session
        request.session['portal_session_key'] = portal_session.session_key
        request.session['portal_patient_id'] = patient.id
        
        # Clear the temporary email
        del request.session['portal_email']
        
        messages.success(request, f'Welcome, {patient.full_name}!')
        return redirect('patient_portal:dashboard')


class PatientPortalDashboardView(TemplateView):
    """Patient portal dashboard"""
    template_name = 'patient_portal/dashboard.html'
    
    def dispatch(self, request, *args, **kwargs):
        # Check if authenticated
        session_key = request.session.get('portal_session_key')
        if not session_key:
            messages.error(request, 'Please log in to access the patient portal.')
            return redirect('patient_portal:login')
        
        # Validate session
        portal_session = PatientPortalSession.get_valid_session(session_key)
        if not portal_session:
            # Session expired or invalid
            if 'portal_session_key' in request.session:
                del request.session['portal_session_key']
            if 'portal_patient_id' in request.session:
                del request.session['portal_patient_id']
            messages.error(request, 'Your session has expired. Please log in again.')
            return redirect('patient_portal:login')
        
        # Store in request for use in views
        request.portal_session = portal_session
        request.portal_patient = portal_session.patient
        
        return super().dispatch(request, *args, **kwargs)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        patient = self.request.portal_patient
        
        # Base queryset for upcoming appointments
        upcoming_base = Appointment.objects.filter(
            patient=patient,
            appointment_date__gte=timezone.now().date(),
            status__in=['pending', 'confirmed']
        ).select_related('service', 'assigned_dentist').order_by('appointment_date', 'period')
        
        # Get count of pending appointments before slicing
        pending_count = upcoming_base.filter(status='pending').count()
        
        # Now slice for display
        upcoming_appointments = upcoming_base[:5]
        
        # Get recent appointments
        recent_appointments = Appointment.objects.filter(
            patient=patient,
            appointment_date__lt=timezone.now().date()
        ).select_related('service', 'assigned_dentist').order_by('-appointment_date', '-period')[:5]
        
        # Get billing summary
        from appointments.models import Payment
        payments = Payment.objects.filter(patient=patient)
        
        total_billed = payments.aggregate(total=Sum('total_amount'))['total'] or 0
        total_paid = payments.aggregate(total=Sum('amount_paid'))['total'] or 0
        outstanding = total_billed - total_paid
        
        context.update({
            'patient': patient,
            'upcoming_appointments': upcoming_appointments,
            'recent_appointments': recent_appointments,
            'billing_summary': {
                'total_billed': total_billed,
                'total_paid': total_paid,
                'outstanding': outstanding,
            },
            'pending_count': pending_count,
        })
        
        return context


class PatientPortalAppointmentsView(TemplateView):
    """View all appointments"""
    template_name = 'patient_portal/appointments.html'
    
    def dispatch(self, request, *args, **kwargs):
        # Use same authentication as dashboard
        session_key = request.session.get('portal_session_key')
        if not session_key:
            messages.error(request, 'Please log in to access the patient portal.')
            return redirect('patient_portal:login')
        
        portal_session = PatientPortalSession.get_valid_session(session_key)
        if not portal_session:
            if 'portal_session_key' in request.session:
                del request.session['portal_session_key']
            if 'portal_patient_id' in request.session:
                del request.session['portal_patient_id']
            messages.error(request, 'Your session has expired. Please log in again.')
            return redirect('patient_portal:login')
        
        request.portal_session = portal_session
        request.portal_patient = portal_session.patient
        
        return super().dispatch(request, *args, **kwargs)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        patient = self.request.portal_patient
        
        # Get all appointments with filtering
        appointments = Appointment.objects.filter(
            patient=patient
        ).select_related('service', 'assigned_dentist').order_by('-appointment_date', '-period')
        
        # Apply filters
        status_filter = self.request.GET.get('status')
        if status_filter:
            appointments = appointments.filter(status=status_filter)
        
        context.update({
            'patient': patient,
            'appointments': appointments,
            'status_filter': status_filter,
            'status_choices': Appointment.STATUS_CHOICES,
            'today': timezone.now().date(),
        })
        
        return context


class PatientPortalBillingView(TemplateView):
    """View billing summary"""
    template_name = 'patient_portal/billing.html'
    
    def dispatch(self, request, *args, **kwargs):
        session_key = request.session.get('portal_session_key')
        if not session_key:
            messages.error(request, 'Please log in to access the patient portal.')
            return redirect('patient_portal:login')
        
        portal_session = PatientPortalSession.get_valid_session(session_key)
        if not portal_session:
            if 'portal_session_key' in request.session:
                del request.session['portal_session_key']
            if 'portal_patient_id' in request.session:
                del request.session['portal_patient_id']
            messages.error(request, 'Your session has expired. Please log in again.')
            return redirect('patient_portal:login')
        
        request.portal_session = portal_session
        request.portal_patient = portal_session.patient
        
        return super().dispatch(request, *args, **kwargs)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        patient = self.request.portal_patient
        
        # Get all payments
        from appointments.models import Payment
        payments = Payment.objects.filter(
            patient=patient
        ).select_related('appointment', 'appointment__service').prefetch_related('items').order_by('-created_at')
        
        # Calculate totals
        total_billed = payments.aggregate(total=Sum('total_amount'))['total'] or 0
        total_paid = payments.aggregate(total=Sum('amount_paid'))['total'] or 0
        outstanding = total_billed - total_paid
        
        context.update({
            'patient': patient,
            'payments': payments,
            'total_billed': total_billed,
            'total_paid': total_paid,
            'outstanding': outstanding,
        })
        
        return context


@require_POST
def cancel_appointment_view(request, appointment_id):
    """Cancel appointment from patient portal"""
    # Check authentication
    session_key = request.session.get('portal_session_key')
    if not session_key:
        messages.error(request, 'Please log in to cancel appointments.')
        return redirect('patient_portal:login')
    
    portal_session = PatientPortalSession.get_valid_session(session_key)
    if not portal_session:
        messages.error(request, 'Your session has expired. Please log in again.')
        return redirect('patient_portal:login')
    
    patient = portal_session.patient
    
    # Get appointment
    appointment = get_object_or_404(
        Appointment,
        id=appointment_id,
        patient=patient
    )
    
    # Check if can be cancelled
    if not appointment.can_be_cancelled:
        messages.error(request, 'This appointment cannot be cancelled. It must be at least 24 hours before the appointment date.')
        return redirect('patient_portal:appointments')
    
    if appointment.status not in ['pending', 'confirmed']:
        messages.error(request, 'This appointment cannot be cancelled.')
        return redirect('patient_portal:appointments')
    
    # Cancel appointment
    old_status = appointment.status
    appointment.status = 'cancelled'
    appointment.save(update_fields=['status'])
    
    # Log the cancellation
    AuditLog.log_action(
        user=None,  # Patient-initiated
        action='cancel',
        model_instance=appointment,
        changes={
            'status': {'old': old_status, 'new': 'cancelled', 'label': 'Status'},
            'cancelled_by': 'Patient via portal'
        },
        description=f"Patient {patient.full_name} cancelled their appointment via portal",
        request=request
    )
    
    # Send cancellation email
    EmailService.send_appointment_cancelled_email(appointment, cancelled_by_patient=True)
    
    messages.success(request, 'Your appointment has been cancelled successfully.')
    return redirect('patient_portal:appointments')


def logout_view(request):
    """Logout from patient portal"""
    session_key = request.session.get('portal_session_key')
    
    if session_key:
        portal_session = PatientPortalSession.get_valid_session(session_key)
        if portal_session:
            portal_session.terminate()
    
    # Clear session
    if 'portal_session_key' in request.session:
        del request.session['portal_session_key']
    if 'portal_patient_id' in request.session:
        del request.session['portal_patient_id']
    if 'portal_email' in request.session:
        del request.session['portal_email']
    
    messages.success(request, 'You have been logged out successfully.')
    return redirect('patient_portal:login')