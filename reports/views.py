# reports/views.py - CORRECTED VERSION
from django.shortcuts import render, redirect
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.generic import TemplateView
from django.db.models import (
    Count, Sum, Q, F, DecimalField, Case, When, Value, IntegerField, 
    OuterRef, Subquery, Exists
)
from django.db.models import Count, Sum, Q, F, DecimalField, Case, When, Value
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.http import HttpResponse
from django.template.loader import render_to_string
from datetime import date, datetime, timedelta
from decimal import Decimal

from xhtml2pdf import pisa

from appointments.models import Appointment, Payment, PaymentTransaction, PaymentItem
from patients.models import Patient
from services.models import Service, Discount
from core.models import SystemSetting
from appointments.models import DailySlots


class ReportsView(LoginRequiredMixin, TemplateView):
    """
    Comprehensive reports dashboard with financial, operational, and analytics data
    
    IMPORTANT NOTES:
    - Revenue calculations use PaymentTransaction.payment_date (actual cash received)
    - Service revenue uses appointment_date (services performed in period)
    - All queries optimized with select_related/prefetch_related to avoid N+1
    """
    template_name = 'reports/reports_dashboard.html'
    
    def dispatch(self, request, *args, **kwargs):
        if not hasattr(request.user, 'has_permission') or not request.user.has_permission('reports'):
            messages.error(request, 'You do not have permission to access reports.')
            return redirect('core:dashboard')
        return super().dispatch(request, *args, **kwargs)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        date_range = self.request.GET.get('date_range', 'last_30_days')
        custom_start = self.request.GET.get('custom_start')
        custom_end = self.request.GET.get('custom_end')
        
        start_date, end_date = self._get_date_range(date_range, custom_start, custom_end)
        
        context.update({
            'date_range': date_range,
            'start_date': start_date,
            'end_date': end_date,
            'custom_start': custom_start or '',
            'custom_end': custom_end or '',
        })
        
        context.update(self._get_financial_reports(start_date, end_date))
        context.update(self._get_operational_reports(start_date, end_date))
        context.update(self._get_analytics_reports(start_date, end_date))
        
        return context
    
    def _get_date_range(self, date_range, custom_start=None, custom_end=None):
        """
        Calculate start and end dates based on selected range
        
        Args:
            date_range: Predefined range key
            custom_start: Custom start date string (YYYY-MM-DD)
            custom_end: Custom end date string (YYYY-MM-DD)
            
        Returns:
            Tuple of (start_date, end_date)
        """
        today = date.today()
        
        if date_range == 'today':
            start_date = end_date = today
        elif date_range == 'yesterday':
            start_date = end_date = today - timedelta(days=1)
        elif date_range == 'last_7_days':
            start_date = today - timedelta(days=7)
            end_date = today
        elif date_range == 'last_30_days':
            start_date = today - timedelta(days=30)
            end_date = today
        elif date_range == 'custom' and custom_start and custom_end:
            try:
                start_date = datetime.strptime(custom_start, '%Y-%m-%d').date()
                end_date = datetime.strptime(custom_end, '%Y-%m-%d').date()
                
                # Validate date range
                if start_date > end_date:
                    start_date, end_date = end_date, start_date
                    
            except (ValueError, TypeError):
                start_date = today - timedelta(days=30)
                end_date = today
        else:
            # Default fallback
            start_date = today - timedelta(days=30)
            end_date = today
        
        return start_date, end_date
    
    def _get_financial_reports(self, start_date, end_date):
        """
        Calculate financial metrics
        
        IMPORTANT: 
        - Total revenue uses PaymentTransaction.payment_date (cash received)
        - Service revenue uses Appointment.appointment_date (services performed)
        - This separates cash flow tracking from revenue recognition
        """
        
        # 1. TOTAL REVENUE - Based on cash received (PaymentTransaction.payment_date)
        revenue_data = PaymentTransaction.objects.filter(
            payment_date__gte=start_date,
            payment_date__lte=end_date
        ).aggregate(
            total_revenue=Coalesce(Sum('amount'), Value(0, output_field=DecimalField(max_digits=10, decimal_places=2)))
        )
        
        total_revenue = revenue_data['total_revenue'] or Decimal('0')
        
        # 2. OUTSTANDING BALANCES - All time (not filtered by date)
        outstanding_data = Payment.objects.filter(
            status__in=['pending', 'partially_paid']
        ).aggregate(
            total_outstanding=Coalesce(
                Sum(F('total_amount') - F('amount_paid')),
                Value(0, output_field=DecimalField(max_digits=10, decimal_places=2))
            )
        )
        
        total_outstanding = outstanding_data['total_outstanding'] or Decimal('0')
        
        # 3. OVERDUE PAYMENTS - Installments past due date
        overdue_payments = list(Payment.objects.filter(
            status__in=['pending', 'partially_paid'],
            next_due_date__isnull=False,
            next_due_date__lt=date.today()
        ).select_related('patient', 'appointment__service').order_by('next_due_date')[:10])
        
        overdue_count = Payment.objects.filter(
            status__in=['pending', 'partially_paid'],
            next_due_date__isnull=False,
            next_due_date__lt=date.today()
        ).count()
        
        # 4. RECENT TRANSACTIONS - For detailed list
        recent_transactions = PaymentTransaction.objects.filter(
            payment_date__gte=start_date,
            payment_date__lte=end_date
        ).select_related(
            'payment__patient',
            'payment__appointment__service',
            'created_by'
        ).order_by('-payment_datetime')[:15]
        
        # 5. SERVICE REVENUE BREAKDOWN
        # FIXED: Filter by appointment_date (when service was performed)
        # NOT by payment_date (to avoid duplication from multiple transactions)
        service_revenue = PaymentItem.objects.filter(
            payment__appointment__status='completed',
            payment__appointment__appointment_date__gte=start_date,
            payment__appointment__appointment_date__lte=end_date
        ).values(
            'service__id',
            'service__name'
        ).annotate(
            # Calculate revenue: (unit_price * quantity) for each item
            total_revenue=Sum(F('unit_price') * F('quantity'), output_field=DecimalField()),
            service_count=Sum('quantity')
        ).order_by('-total_revenue')[:10]
        
        # 6. CALCULATE METRICS
        transaction_count = PaymentTransaction.objects.filter(
            payment_date__gte=start_date,
            payment_date__lte=end_date
        ).count()
        
        # Average transaction value
        avg_transaction = total_revenue / transaction_count if transaction_count > 0 else Decimal('0')
        
        # Patients with outstanding balance
        patients_with_balance = Payment.objects.filter(
            status__in=['pending', 'partially_paid']
        ).values('patient').distinct().count()
        
        return {
            'total_revenue': total_revenue,
            'total_outstanding': total_outstanding,
            'overdue_payments': overdue_payments,
            'overdue_count': overdue_count,
            'recent_transactions': recent_transactions,
            'service_revenue': service_revenue,
            'avg_transaction': avg_transaction,
            'transaction_count': transaction_count,
            'patients_with_balance': patients_with_balance,
        }
    
    def _get_operational_reports(self, start_date, end_date):
        """Calculate operational metrics"""
        
        # Base queryset for appointments in date range
        appointments_in_range = Appointment.objects.filter(
            appointment_date__gte=start_date,
            appointment_date__lte=end_date
        )
        
        # Total appointments
        total_appointments = appointments_in_range.count()
        
        # Appointments by status
        appointments_by_status = appointments_in_range.values('status').annotate(
            count=Count('id')
        ).order_by('-count')
        
        # Status counts
        completed_appointments = appointments_in_range.filter(status='completed').count()
        confirmed_appointments = appointments_in_range.filter(status='confirmed').count()
        pending_appointments = appointments_in_range.filter(status='pending').count()
        cancelled_appointments = appointments_in_range.filter(status='cancelled').count()
        
        # No-shows (did_not_arrive only)
        no_shows = appointments_in_range.filter(status='did_not_arrive').count()
        
        # No-show rate calculation
        # Only count completed + no-show (appointments that were expected to happen)
        eligible_for_noshow = completed_appointments + no_shows
        no_show_rate = (no_shows / eligible_for_noshow * 100) if eligible_for_noshow > 0 else 0
        
        # Pending appointment requests (future appointments needing approval)
        pending_requests = Appointment.objects.filter(
            status='pending',
            appointment_date__gte=date.today()
        ).select_related('service', 'patient').order_by('appointment_date', 'period')[:10]
        
        # Daily appointment schedule
        daily_schedule = appointments_in_range.filter(
            status__in=['confirmed', 'completed']
        ).values('appointment_date').annotate(
            am_count=Count('id', filter=Q(period='AM')),
            pm_count=Count('id', filter=Q(period='PM')),
            total_count=Count('id')
        ).order_by('appointment_date')
        
        # Appointment utilization rate
        total_slots_data = DailySlots.objects.filter(
            date__gte=start_date,
            date__lte=end_date
        ).aggregate(
            total_am=Coalesce(Sum('am_slots'), Value(0)),
            total_pm=Coalesce(Sum('pm_slots'), Value(0))
        )
        
        total_slots = (total_slots_data['total_am'] or 0) + (total_slots_data['total_pm'] or 0)
        
        # Slots actually used (confirmed + completed)
        used_slots = appointments_in_range.filter(
            status__in=['confirmed', 'completed']
        ).count()
        
        utilization_rate = (used_slots / total_slots * 100) if total_slots > 0 else 0
        
        return {
            'total_appointments': total_appointments,
            'appointments_by_status': appointments_by_status,
            'completed_appointments': completed_appointments,
            'confirmed_appointments': confirmed_appointments,
            'pending_appointments': pending_appointments,
            'cancelled_appointments': cancelled_appointments,
            'no_shows': no_shows,
            'no_show_rate': round(no_show_rate, 1),
            'pending_requests': pending_requests,
            'daily_schedule': daily_schedule,
            'total_slots': total_slots,
            'used_slots': used_slots,
            'utilization_rate': round(utilization_rate, 1),
        }
    
    def _get_analytics_reports(self, start_date, end_date):
        """Calculate analytics and insights"""
        
        top_services_limit = SystemSetting.get_int_setting('reports_top_services_limit', 10)
        top_discounts_limit = SystemSetting.get_int_setting('reports_top_discounts_limit', 5)
        
        # 1. POPULAR SERVICES BY COUNT (most frequently performed)
        popular_services_by_count = PaymentItem.objects.filter(
            payment__appointment__status='completed',
            payment__appointment__appointment_date__gte=start_date,
            payment__appointment__appointment_date__lte=end_date
        ).values(
            'service__id',
            'service__name'
        ).annotate(
            service_count=Sum('quantity')
        ).order_by('-service_count')[:top_services_limit]
        
        # 2. POPULAR SERVICES BY REVENUE (most income generated)
        popular_services_by_revenue = PaymentItem.objects.filter(
            payment__appointment__status='completed',
            payment__appointment__appointment_date__gte=start_date,
            payment__appointment__appointment_date__lte=end_date
        ).values(
            'service__id',
            'service__name'
        ).annotate(
            total_revenue=Sum(F('quantity') * F('unit_price'), output_field=DecimalField())
        ).order_by('-total_revenue')[:top_services_limit]
        
        # 3. DISCOUNT USAGE ANALYSIS
        # FIXED: Proper discount calculation matching PaymentItem.discount_amount logic
        discount_usage_qs = PaymentItem.objects.filter(
            payment__appointment__status='completed',
            payment__appointment__appointment_date__gte=start_date,
            payment__appointment__appointment_date__lte=end_date,
            discount__isnull=False
        ).values(
            'discount__id',
            'discount__name',
            'discount__is_percentage',
            'discount__amount'
        ).annotate(
            times_used=Count('id')
        ).order_by('-times_used')[:top_discounts_limit]
        
        # Calculate total discount given for each discount type
        # Must replicate PaymentItem.discount_amount property logic
        discount_usage = []
        for item in discount_usage_qs:
            discount_id = item['discount__id']
            
            # Get all payment items with this discount
            items_with_discount = PaymentItem.objects.filter(
                payment__appointment__status='completed',
                payment__appointment__appointment_date__gte=start_date,
                payment__appointment__appointment_date__lte=end_date,
                discount__id=discount_id
            )
            
            # Calculate total discount given (matching PaymentItem.discount_amount logic)
            total_discount = Decimal('0')
            for pi in items_with_discount:
                subtotal = pi.unit_price * pi.quantity
                if item['discount__is_percentage']:
                    discount_amt = subtotal * (item['discount__amount'] / 100)
                else:
                    discount_amt = min(item['discount__amount'], subtotal)
                total_discount += discount_amt
            
            # Calculate average
            avg_discount = total_discount / item['times_used'] if item['times_used'] > 0 else Decimal('0')
            
            discount_usage.append({
                'discount__name': item['discount__name'],
                'discount__is_percentage': item['discount__is_percentage'],
                'discount__amount': item['discount__amount'],
                'times_used': item['times_used'],
                'total_discount_given': total_discount,
                'avg_discount': avg_discount,
            })
        
        # 4. NEW VS RETURNING PATIENTS
        appointments_in_range = Appointment.objects.filter(
            appointment_date__gte=start_date,
            appointment_date__lte=end_date,
            status='completed'
        )
        
        new_patients = appointments_in_range.filter(patient_type='new').count()
        returning_patients = appointments_in_range.filter(patient_type='returning').count()
        
        total_patient_appointments = new_patients + returning_patients
        new_patient_percentage = (new_patients / total_patient_appointments * 100) if total_patient_appointments > 0 else 0
        returning_patient_percentage = (returning_patients / total_patient_appointments * 100) if total_patient_appointments > 0 else 0
        
        # 5. AVERAGE TREATMENT VALUE
        completed_with_payment = Payment.objects.filter(
            appointment__status='completed',
            appointment__appointment_date__gte=start_date,
            appointment__appointment_date__lte=end_date
        ).aggregate(
            total_value=Coalesce(Sum('total_amount'), Value(0, output_field=DecimalField())),
            count=Count('id')
        )
        
        avg_treatment_value = (
            completed_with_payment['total_value'] / completed_with_payment['count']
            if completed_with_payment['count'] > 0 else Decimal('0')
        )
        
        # 6. PAYMENT COLLECTION RATE
        payment_stats = Payment.objects.filter(
            appointment__status='completed',
            appointment__appointment_date__gte=start_date,
            appointment__appointment_date__lte=end_date
        ).aggregate(
            total_billed=Coalesce(Sum('total_amount'), Value(0, output_field=DecimalField())),
            total_collected=Coalesce(Sum('amount_paid'), Value(0, output_field=DecimalField()))
        )
        
        collection_rate = (
            payment_stats['total_collected'] / payment_stats['total_billed'] * 100
            if payment_stats['total_billed'] > 0 else 0
        )
        
        return {
            'popular_services_by_count': popular_services_by_count,
            'popular_services_by_revenue': popular_services_by_revenue,
            'discount_usage': discount_usage,
            'new_patients': new_patients,
            'returning_patients': returning_patients,
            'new_patient_percentage': round(new_patient_percentage, 1),
            'returning_patient_percentage': round(returning_patient_percentage, 1),
            'avg_treatment_value': avg_treatment_value,
            'collection_rate': round(collection_rate, 1),
            'total_billed': payment_stats['total_billed'] or Decimal('0'),
            'total_collected': payment_stats['total_collected'] or Decimal('0'),
        }


@login_required
def export_reports_pdf(request):
    """Export all reports to PDF"""
    if not hasattr(request.user, 'has_permission') or not request.user.has_permission('reports'):
        messages.error(request, 'You do not have permission to export reports.')
        return redirect('core:dashboard')
    
    date_range = request.GET.get('date_range', 'last_30_days')
    custom_start = request.GET.get('custom_start')
    custom_end = request.GET.get('custom_end')
    
    # Calculate dates using view method
    view = ReportsView()
    view.request = request
    start_date, end_date = view._get_date_range(date_range, custom_start, custom_end)
    
    # Get all report data
    context = {
        'date_range': date_range,
        'start_date': start_date,
        'end_date': end_date,
        'generated_at': timezone.now(),
        'generated_by': request.user.get_full_name() or request.user.username,
    }
    
    context.update(view._get_financial_reports(start_date, end_date))
    context.update(view._get_operational_reports(start_date, end_date))
    context.update(view._get_analytics_reports(start_date, end_date))
    
    # Get clinic info
    context['clinic_name'] = SystemSetting.get_setting('clinic_name', 'KingJoy Dental Clinic')
    context['clinic_address'] = SystemSetting.get_setting('clinic_address', '54 Obanic St.\nQuezon City, Metro Manila')
    context['clinic_phone'] = SystemSetting.get_setting('clinic_phone', '+63 956 631 6581')
    context['clinic_email'] = SystemSetting.get_setting('clinic_email', 'contact@kingjoydental.com')
    
    try:
        html_string = render_to_string('reports/reports_pdf.html', context)
        
        response = HttpResponse(content_type='application/pdf')
        filename = f'Reports_{start_date}_{end_date}.pdf'
        response['Content-Disposition'] = f'inline; filename="{filename}"'
        
        pisa_status = pisa.CreatePDF(html_string, dest=response)
        
        if pisa_status.err:
            messages.error(request, 'Error generating PDF. Please try again.')
            return redirect('reports:dashboard')
        
        return response
        
    except Exception as e:
        messages.error(request, f'Error generating PDF: {str(e)}')
        return redirect('reports:dashboard')