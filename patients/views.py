# patients/views.py - Updated for AM/PM slot system
from django.shortcuts import get_object_or_404, redirect
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.urls import reverse_lazy
from django.views.generic import ListView, DetailView, CreateView, UpdateView
from django.db.models import Q, F, Prefetch, Sum, Max, Count, Case, When, Value, DecimalField
from django.http import JsonResponse, HttpResponse
from django.template.loader import render_to_string
from django.utils import timezone as django_timezone
from datetime import date, timedelta, timezone
import csv
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from io import BytesIO
from xhtml2pdf import pisa

from .models import Patient
from .forms import PatientForm, PatientSearchForm, FindPatientForm
from appointments.models import Appointment


class PatientListView(LoginRequiredMixin, ListView):
    """Enhanced list view with filtering, search, and PDF export functionality"""
    model = Patient
    template_name = 'patients/patient_list.html'
    context_object_name = 'patients'
    paginate_by = 25
    
    def dispatch(self, request, *args, **kwargs):
        if not request.user.has_permission('patients'):
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('core:dashboard')
        return super().dispatch(request, *args, **kwargs)
    
    def get(self, request, *args, **kwargs):
        """Override get to handle PDF export before template rendering"""
        export_format = request.GET.get('export')
        
        if export_format == 'pdf':
            # Get the full queryset (not paginated) for export
            self.object_list = self.get_queryset()
            
            # Limit export to reasonable number
            if self.object_list.count() > 1000:
                messages.warning(
                    request, 
                    'Export limited to first 1000 patients. Please use filters to narrow your search.'
                )
                self.object_list = self.object_list[:1000]
            
            return self.export_to_pdf_xhtml2pdf()
        
        # Normal list view
        return super().get(request, *args, **kwargs)
    
    def get_queryset(self):
        # Same as before - no changes needed
        queryset = Patient.objects.all().select_related()
        
        queryset = queryset.annotate(
            visit_count=Count(
                'appointments',
                filter=Q(appointments__status='completed'),
                distinct=True
            )
        )
        
        queryset = queryset.annotate(
            outstanding_balance=Sum(
                Case(
                    When(
                        appointments__payments__isnull=False,
                        then=F('appointments__payments__total_amount') - F('appointments__payments__amount_paid')
                    ),
                    default=Value(0),
                    output_field=DecimalField(max_digits=10, decimal_places=2)
                )
            )
        )
        
        queryset = queryset.prefetch_related(
            Prefetch(
                'appointments',
                queryset=Appointment.objects.filter(
                    status='completed'
                ).select_related('service').order_by('-appointment_date'),
                to_attr='completed_appointments'
            ),
            Prefetch(
                'appointments',
                queryset=Appointment.objects.filter(
                    status__in=['confirmed', 'pending'],
                    appointment_date__gte=django_timezone.now().date()
                ).select_related('service').order_by('appointment_date'),
                to_attr='upcoming_appointments'
            )
        )
        
        # Apply filters (same as before)
        search = self.request.GET.get('search', '').strip()
        status = self.request.GET.get('status', '')
        contact = self.request.GET.get('contact', '')
        activity = self.request.GET.get('activity', '')
        sort_by = self.request.GET.get('sort', 'name_asc')
        
        if search:
            queryset = queryset.filter(
                Q(first_name__icontains=search) |
                Q(last_name__icontains=search) |
                Q(email__icontains=search) |
                Q(contact_number__icontains=search)
            )
        
        if status:
            if status == 'active':
                queryset = queryset.filter(is_active=True)
            elif status == 'inactive':
                queryset = queryset.filter(is_active=False)
        
        if contact:
            if contact == 'email_only':
                queryset = queryset.filter(email__isnull=False).exclude(email='')
                queryset = queryset.filter(Q(contact_number__isnull=True) | Q(contact_number=''))
            elif contact == 'phone_only':
                queryset = queryset.filter(contact_number__isnull=False).exclude(contact_number='')
                queryset = queryset.filter(Q(email__isnull=True) | Q(email=''))
            elif contact == 'both':
                queryset = queryset.filter(email__isnull=False, contact_number__isnull=False)
                queryset = queryset.exclude(Q(email='') | Q(contact_number=''))
            elif contact == 'none':
                queryset = queryset.filter(
                    Q(email__isnull=True) | Q(email=''),
                    Q(contact_number__isnull=True) | Q(contact_number='')
                )
        
        if activity:
            today = date.today()
            if activity == 'recent':
                recent_date = today - timedelta(days=30)
                recent_patient_ids = Appointment.objects.filter(
                    appointment_date__gte=recent_date,
                    status='completed'
                ).values_list('patient_id', flat=True).distinct()
                queryset = queryset.filter(id__in=recent_patient_ids)
            elif activity == 'upcoming':
                upcoming_patient_ids = Appointment.objects.filter(
                    appointment_date__gte=today,
                    status__in=['confirmed', 'pending']
                ).values_list('patient_id', flat=True).distinct()
                queryset = queryset.filter(id__in=upcoming_patient_ids)
            elif activity == 'no_recent':
                old_date = today - timedelta(days=90)
                recent_patient_ids = Appointment.objects.filter(
                    appointment_date__gte=old_date
                ).values_list('patient_id', flat=True).distinct()
                queryset = queryset.exclude(id__in=recent_patient_ids)
        
        if sort_by == 'name_asc':
            queryset = queryset.order_by('last_name', 'first_name')
        elif sort_by == 'name_desc':
            queryset = queryset.order_by('-last_name', '-first_name')
        elif sort_by == 'date_added_desc':
            queryset = queryset.order_by('-created_at')
        elif sort_by == 'date_added_asc':
            queryset = queryset.order_by('created_at')
        elif sort_by == 'last_visit_desc':
            queryset = queryset.annotate(
                last_visit_date=Max('appointments__appointment_date')
            ).order_by(F('last_visit_date').desc(nulls_last=True))
        elif sort_by == 'last_visit_asc':
            queryset = queryset.annotate(
                last_visit_date=Max('appointments__appointment_date')
            ).order_by(F('last_visit_date').asc(nulls_last=True))
        
        return queryset
    
    def get_context_data(self, **kwargs):
        # Same as before - no changes needed
        context = super().get_context_data(**kwargs)
        
        context['current_filters'] = {
            'search': self.request.GET.get('search', ''),
            'status': self.request.GET.get('status', ''),
            'contact': self.request.GET.get('contact', ''),
            'activity': self.request.GET.get('activity', ''),
            'sort': self.request.GET.get('sort', 'name_asc'),
        }
        
        active_filters = []
        if context['current_filters']['search']:
            active_filters.append(f"Search: {context['current_filters']['search']}")
        if context['current_filters']['status']:
            active_filters.append(f"Status: {context['current_filters']['status'].title()}")
        if context['current_filters']['contact']:
            active_filters.append(f"Contact: {context['current_filters']['contact'].replace('_', ' ').title()}")
        if context['current_filters']['activity']:
            active_filters.append(f"Activity: {context['current_filters']['activity'].replace('_', ' ').title()}")
        
        context['active_filters'] = active_filters
        
        total_patients = Patient.objects.filter(is_active=True).count()
        today = date.today()
        
        upcoming_appointments = Appointment.objects.filter(
            appointment_date__gte=today,
            status__in=['confirmed', 'pending'],
            patient__isnull=False
        ).values('patient').distinct().count()
        
        with_email = Patient.objects.filter(is_active=True, email__isnull=False).exclude(email='').count()
        
        old_date = today - timedelta(days=90)
        no_recent_visits = Patient.objects.filter(is_active=True).exclude(
            appointments__appointment_date__gte=old_date,
            appointments__status='completed',
            appointments__patient__isnull=False
        ).count()
        
        context['insights'] = {
            'total_active': total_patients,
            'upcoming_appointments': upcoming_appointments,
            'with_email': with_email,
            'no_recent_visits': no_recent_visits,
        }
        
        context['total_count'] = Patient.objects.count()
        
        return context
    
    def export_to_pdf_xhtml2pdf(self):
        """Generate PDF using xhtml2pdf (no system dependencies required)"""
        try:
            patients_qs = self.object_list
            
            # Convert queryset to list with explicit data extraction
            patients_data = []
            for patient in patients_qs:
                patient_dict = {
                    'full_name': patient.full_name,
                    'email': patient.email,
                    'contact_number': patient.contact_number,
                    'visit_count': patient.visit_count if hasattr(patient, 'visit_count') else 0,
                    'outstanding_balance': patient.outstanding_balance if hasattr(patient, 'outstanding_balance') else None,
                }
                
                # Get completed appointments
                if hasattr(patient, 'completed_appointments') and patient.completed_appointments:
                    last_appt = patient.completed_appointments[0]
                    patient_dict['last_visit'] = {
                        'date': last_appt.appointment_date,
                        'service_name': last_appt.service.name if last_appt.service else 'N/A',
                    }
                else:
                    patient_dict['last_visit'] = None
                
                # Get upcoming appointments
                if hasattr(patient, 'upcoming_appointments') and patient.upcoming_appointments:
                    next_appt = patient.upcoming_appointments[0]
                    patient_dict['next_appointment'] = {
                        'date': next_appt.appointment_date,
                        'period': next_appt.get_period_display() if hasattr(next_appt, 'get_period_display') else '',
                    }
                else:
                    patient_dict['next_appointment'] = None
                
                patients_data.append(patient_dict)
            
            context = {
                'patients': patients_data,
                'total_count': len(patients_data),
                'generated_date': django_timezone.now(),
                'clinic_name': 'KingJoy Dental Clinic',
                'filters_applied': self._get_filters_description(),
            }
            
            # Render HTML template
            html_string = render_to_string('patients/patient_list_pdf_simple.html', context)
            
            # Create PDF
            result = BytesIO()
            pdf = pisa.pisaDocument(BytesIO(html_string.encode("UTF-8")), result)
            
            if not pdf.err:
                response = HttpResponse(result.getvalue(), content_type='application/pdf')
                response['Content-Disposition'] = f'attachment; filename="patients_report_{date.today()}.pdf"'
                return response
            else:
                # Return error response instead of redirect
                return HttpResponse(
                    'Error generating PDF. Please try again.',
                    status=500,
                    content_type='text/plain'
                )
        
        except Exception as e:
            # Log the error for debugging
            import traceback
            print(f"PDF Generation Error: {str(e)}")
            print(traceback.format_exc())
            return HttpResponse(
                f'Error generating PDF: {str(e)}',
                status=500,
                content_type='text/plain'
            )
    
    def _get_filters_description(self):
        """Get human-readable description of applied filters"""
        filters = []
        
        search = self.request.GET.get('search', '').strip()
        if search:
            filters.append(f"Search: '{search}'")
        
        status = self.request.GET.get('status', '')
        if status:
            filters.append(f"Status: {status.title()}")
        
        contact = self.request.GET.get('contact', '')
        if contact:
            filters.append(f"Contact: {contact.replace('_', ' ').title()}")
        
        activity = self.request.GET.get('activity', '')
        if activity:
            filters.append(f"Activity: {activity.replace('_', ' ').title()}")
        
        if not filters:
            return "All patients"
        
        return " | ".join(filters)


class PatientDetailView(LoginRequiredMixin, DetailView):
    """View patient details with appointment history - UPDATED for AM/PM system and payment context"""
    model = Patient
    template_name = 'patients/patient_detail.html'
    context_object_name = 'patient'
    
    def dispatch(self, request, *args, **kwargs):
        if not request.user.has_permission('patients'):
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('core:dashboard')
        return super().dispatch(request, *args, **kwargs)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        patient = self.object
        
        # Get all appointments ordered by date (most recent first) - UPDATED for AM/PM system
        appointments = Appointment.objects.filter(patient=patient).select_related(
            'service', 'assigned_dentist'
        ).order_by('-appointment_date', '-period', '-requested_at')
        
        # Categorize appointments - UPDATED to use appointment_date
        today = date.today()
        completed_appointments = appointments.filter(status='completed')
        upcoming_appointments = appointments.filter(
            appointment_date__gte=today, 
            status__in=['confirmed', 'pending']
        )
        cancelled_appointments = appointments.filter(status__in=['cancelled', 'rejected'])
        
        # Payment context - NEW
        from appointments.models import Payment, PaymentTransaction
        from decimal import Decimal
        
        # Get all payments for this patient
        patient_payments = Payment.objects.filter(patient=patient).select_related('appointment__service')
        
        # Calculate payment summary
        total_amount_due = Decimal('0')
        total_amount_paid = Decimal('0')
        
        for payment in patient_payments:
            total_amount_due += payment.total_amount
            total_amount_paid += payment.amount_paid
        
        outstanding_balance = total_amount_due - total_amount_paid
        
        # Get recent payments for display (last 5)
        recent_payments = patient_payments.order_by('-created_at')[:5]
        
        # Get next due date and check if overdue
        next_due_date = None
        is_overdue = False
        
        overdue_payment = patient_payments.filter(
            status__in=['pending', 'partially_paid'],
            next_due_date__isnull=False
        ).order_by('next_due_date').first()
        
        if overdue_payment:
            next_due_date = overdue_payment.next_due_date
            is_overdue = next_due_date < today
        
        # Get last payment transaction
        last_payment = None
        if patient_payments.exists():
            last_payment = PaymentTransaction.objects.filter(
                payment__patient=patient
            ).order_by('-payment_datetime').first()
        
        context.update({
            'appointments': appointments,
            'completed_appointments': completed_appointments,
            'upcoming_appointments': upcoming_appointments,
            'cancelled_appointments': cancelled_appointments,
            
            # Payment context
            'patient_payments': patient_payments,
            'total_amount_due': total_amount_due,
            'total_amount_paid': total_amount_paid,
            'outstanding_balance': outstanding_balance,
            'recent_payments': recent_payments,
            'next_due_date': next_due_date,
            'is_overdue': is_overdue,
            'last_payment': last_payment,
        })
        
        return context

class PatientCreateView(LoginRequiredMixin, CreateView):
    """Create new patient"""
    model = Patient
    form_class = PatientForm
    template_name = 'patients/patient_form.html'
    
    def dispatch(self, request, *args, **kwargs):
        if not request.user.has_permission('patients'):
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('core:dashboard')
        return super().dispatch(request, *args, **kwargs)
    
    def form_valid(self, form):
        messages.success(self.request, f'Patient {form.instance.full_name} created successfully.')
        return super().form_valid(form)
    
    def get_success_url(self):
        return reverse_lazy('patients:patient_detail', kwargs={'pk': self.object.pk})


class PatientUpdateView(LoginRequiredMixin, UpdateView):
    """Update patient information"""
    model = Patient
    form_class = PatientForm
    template_name = 'patients/patient_form.html'
    context_object_name = 'patient'
    
    def dispatch(self, request, *args, **kwargs):
        if not request.user.has_permission('patients'):
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('core:dashboard')
        return super().dispatch(request, *args, **kwargs)
    
    def form_valid(self, form):
        messages.success(self.request, f'Patient {form.instance.full_name} updated successfully.')
        return super().form_valid(form)
    
    def get_success_url(self):
        return reverse_lazy('patients:patient_detail', kwargs={'pk': self.object.pk})


class PatientSearchView(LoginRequiredMixin, ListView):
    """Search patients with advanced filtering"""
    model = Patient
    template_name = 'patients/patient_search.html'
    context_object_name = 'patients'
    paginate_by = 20
    
    def dispatch(self, request, *args, **kwargs):
        if not request.user.has_permission('patients'):
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('core:dashboard')
        return super().dispatch(request, *args, **kwargs)
    
    def get_queryset(self):
        form = PatientSearchForm(self.request.GET)
        queryset = Patient.objects.none()
        
        if form.is_valid():
            query = form.cleaned_data.get('query')
            search_type = form.cleaned_data.get('search_type', 'all')
            
            if query:
                if search_type == 'name':
                    queryset = Patient.objects.filter(
                        Q(first_name__icontains=query) | Q(last_name__icontains=query)
                    )
                elif search_type == 'email':
                    queryset = Patient.objects.filter(email__icontains=query)
                elif search_type == 'phone':
                    queryset = Patient.objects.filter(contact_number__icontains=query)
                else:  # all
                    queryset = Patient.objects.filter(
                        Q(first_name__icontains=query) |
                        Q(last_name__icontains=query) |
                        Q(email__icontains=query) |
                        Q(contact_number__icontains=query)
                    )
        
        return queryset.order_by('last_name', 'first_name')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['form'] = PatientSearchForm(self.request.GET)
        context['query'] = self.request.GET.get('query', '')
        return context


class FindPatientView(LoginRequiredMixin, ListView):
    """Find patient by email or phone for appointment booking"""
    model = Patient
    template_name = 'patients/find_patient.html'
    context_object_name = 'patients'
    
    def dispatch(self, request, *args, **kwargs):
        if not request.user.has_permission('patients'):
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('core:dashboard')
        return super().dispatch(request, *args, **kwargs)
    
    def get_queryset(self):
        identifier = self.request.GET.get('identifier', '').strip()
        if not identifier:
            return Patient.objects.none()
        
        # Search by email or phone number
        return Patient.objects.filter(
            Q(email__iexact=identifier) | Q(contact_number=identifier)
        ).order_by('last_name', 'first_name')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['form'] = FindPatientForm(self.request.GET)
        context['identifier'] = self.request.GET.get('identifier', '')
        
        # If no results and identifier provided, suggest creating new patient
        if context['identifier'] and not context['patients']:
            context['suggest_create'] = True
        
        return context


@login_required
def toggle_patient_active(request, pk):
    """Toggle patient active status"""
    if not request.user.has_permission('patients'):
        messages.error(request, 'You do not have permission to perform this action.')
        return redirect('core:dashboard')
    
    patient = get_object_or_404(Patient, pk=pk)
    patient.is_active = not patient.is_active
    patient.save()
    
    status = 'activated' if patient.is_active else 'deactivated'
    messages.success(request, f'Patient {patient.full_name} has been {status}.')
    
    return redirect('patients:patient_detail', pk=pk)


@login_required  
def patient_quick_info(request, pk):
    """Return quick patient info as JSON for AJAX requests - UPDATED for AM/PM system"""
    if not request.user.has_permission('patients'):
        return JsonResponse({'error': 'Permission denied'}, status=403)
    
    try:
        patient = Patient.objects.get(pk=pk)
        
        # Get recent appointments - UPDATED to use appointment_date
        recent_appointments = patient.appointments.filter(
            appointment_date__gte=date.today() - timedelta(days=30)
        ).order_by('-appointment_date', '-period')[:3]
        
        appointments_data = []
        for apt in recent_appointments:
            appointments_data.append({
                'date': apt.appointment_date.strftime('%Y-%m-%d'),
                'period': apt.get_period_display(),  # 'Morning' or 'Afternoon'
                'service': apt.service.name,
                'status': apt.get_status_display(),
            })
        
        data = {
            'id': patient.pk,
            'name': patient.full_name,
            'email': patient.email,
            'phone': patient.contact_number,
            'age': patient.age,
            'is_minor': patient.is_minor,
            'medical_notes': patient.medical_notes,
            'recent_appointments': appointments_data,
            'total_visits': patient.appointments.filter(status='completed').count(),
        }
        
        return JsonResponse(data)
        
    except Patient.DoesNotExist:
        return JsonResponse({'error': 'Patient not found'}, status=404)