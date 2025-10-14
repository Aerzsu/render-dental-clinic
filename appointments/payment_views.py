# appointments/payment_views.py - UPDATED with receipt functionality and proper messages
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.urls import reverse_lazy
from django.views.generic import ListView, DetailView, CreateView, UpdateView
from django.db.models import Q, Sum, Case, When, DecimalField, F
from django.http import JsonResponse, HttpResponse
from django.db import transaction, models
from django.template.loader import render_to_string
from decimal import Decimal
from datetime import date, timedelta, datetime
from django.utils import timezone
import json

# PDF generation imports
from xhtml2pdf import pisa
from io import BytesIO

from .models import Appointment, Payment, PaymentItem, PaymentTransaction
from patients.models import Patient
from .forms import PaymentForm, AdminOverrideForm
from services.models import Service, Discount


class PaymentListView(LoginRequiredMixin, ListView):
    """Payment list with filtering capabilities"""
    model = Payment
    template_name = 'payment/payment_list.html'
    context_object_name = 'payments'
    paginate_by = 15
    
    def dispatch(self, request, *args, **kwargs):
        if not hasattr(request.user, 'has_permission') or not request.user.has_permission('billing'):
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('core:dashboard')
        return super().dispatch(request, *args, **kwargs)
    
    def get_queryset(self):
        queryset = Payment.objects.select_related('patient', 'appointment__service').prefetch_related('items', 'transactions')
        
        # Apply filters
        status = self.request.GET.get('status')
        if status and status in ['pending', 'partially_paid', 'completed']:
            queryset = queryset.filter(status=status)
        
        amount_min = self.request.GET.get('amount_min')
        if amount_min:
            try:
                queryset = queryset.filter(total_amount__gte=Decimal(amount_min))
            except (ValueError, TypeError):
                pass
        
        amount_max = self.request.GET.get('amount_max')
        if amount_max:
            try:
                queryset = queryset.filter(total_amount__lte=Decimal(amount_max))
            except (ValueError, TypeError):
                pass
        
        # Payment date range
        date_from = self.request.GET.get('date_from')
        date_to = self.request.GET.get('date_to')
        
        if date_from:
            try:
                date_from = datetime.strptime(date_from, '%Y-%m-%d').date()
                queryset = queryset.filter(created_at__date__gte=date_from)
            except ValueError:
                pass
        
        if date_to:
            try:
                date_to = datetime.strptime(date_to, '%Y-%m-%d').date()
                queryset = queryset.filter(created_at__date__lte=date_to)
            except ValueError:
                pass
        
        # Search by patient name
        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(
                Q(patient__first_name__icontains=search) |
                Q(patient__last_name__icontains=search)
            )
        
        return queryset.order_by('-created_at')
    
    def get_patients_without_payments(self):
        """Get patients with completed appointments but no payment records"""
        from .models import Appointment
        
        # Calculate date 90 days ago
        ninety_days_ago = timezone.now().date() - timedelta(days=90)
        
        # Get completed appointments without payment records
        appointments = Appointment.objects.filter(
            status='completed',
            appointment_date__gte=ninety_days_ago
        ).select_related(
            'patient', 'service', 'assigned_dentist'
        ).prefetch_related(
            'payments'
        ).order_by('-appointment_date', '-period')
        
        # Filter to only those without payments
        appointments_without_payments = []
        for appointment in appointments:
            if not appointment.payments.exists():
                # Add days_since_completion as an attribute
                days_diff = (timezone.now().date() - appointment.appointment_date).days
                appointment.days_since_completion = days_diff
                appointments_without_payments.append(appointment)
        
        return appointments_without_payments
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get patients without payment records (limit to 15 for display)
        patients_without_payments = self.get_patients_without_payments()
        context['patients_without_payments'] = patients_without_payments[:15]
        context['total_patients_without_payments'] = len(patients_without_payments)
        
        # Current filters for form population
        context['filters'] = {
            'status': self.request.GET.get('status', ''),
            'amount_min': self.request.GET.get('amount_min', ''),
            'amount_max': self.request.GET.get('amount_max', ''),
            'date_from': self.request.GET.get('date_from', ''),
            'date_to': self.request.GET.get('date_to', ''),
            'search': self.request.GET.get('search', ''),
        }
        
        return context

class PaymentDetailView(LoginRequiredMixin, DetailView):
    """Payment detail view with edit capabilities"""
    model = Payment
    template_name = 'payment/payment_detail.html'
    context_object_name = 'payment'
    
    def dispatch(self, request, *args, **kwargs):
        if not hasattr(request.user, 'has_permission') or not request.user.has_permission('billing'):
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('core:dashboard')
        return super().dispatch(request, *args, **kwargs)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        payment = self.object
        
        # Get all payment items and transactions
        context['payment_items'] = payment.items.all().select_related('service', 'discount')
        context['transactions'] = payment.transactions.all().select_related('created_by').order_by('-payment_datetime')
        
        # Calculate totals
        context['items_total'] = sum(item.total for item in context['payment_items'])
        context['total_discount'] = sum(item.discount_amount for item in context['payment_items'])
        
        # Payment summary
        context['payment_summary'] = {
            'subtotal': sum(item.subtotal for item in context['payment_items']),
            'total_discount': context['total_discount'],
            'total_amount': context['items_total'],
            'amount_paid': payment.amount_paid,
            'outstanding_balance': payment.outstanding_balance,
            'payment_progress': payment.payment_progress_percentage,
        }
        
        # Available services for adding items
        context['available_services'] = Service.active.all().order_by('name')
        
        # Available discounts
        context['available_discounts'] = Discount.objects.filter(is_active=True).order_by('name')
        
        return context


class PatientPaymentSummaryView(LoginRequiredMixin, DetailView):
    """Summary view of all payments for a specific patient"""
    model = Patient
    template_name = 'payment/patient_payment_summary.html'
    context_object_name = 'patient'
    
    def dispatch(self, request, *args, **kwargs):
        if not hasattr(request.user, 'has_permission') or not request.user.has_permission('billing'):
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('core:dashboard')
        return super().dispatch(request, *args, **kwargs)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        patient = self.object
        
        # Get all payments for this patient
        all_payments = Payment.objects.filter(
            patient=patient
        ).select_related(
            'appointment__service',
            'appointment__assigned_dentist'
        ).annotate(
            status_priority=models.Case(
                models.When(status='pending', then=models.Value(1)),
                models.When(status='partially_paid', then=models.Value(2)),
                models.When(status='completed', then=models.Value(3)),
                models.When(status='cancelled', then=models.Value(4)),
                default=models.Value(5),
                output_field=models.IntegerField()
            )
        ).order_by('status_priority', '-created_at')
        
        # Calculate overall financial summary
        total_amount_due = Decimal('0')
        total_amount_paid = Decimal('0')
        
        for payment in all_payments:
            total_amount_due += payment.total_amount
            total_amount_paid += payment.amount_paid
        
        outstanding_balance = total_amount_due - total_amount_paid
        
        # Categorize payments
        pending_payments = all_payments.filter(status='pending')
        partially_paid_payments = all_payments.filter(status='partially_paid')
        completed_payments = all_payments.filter(status='completed')
        
        # Get completed appointments without payments
        completed_appointments_without_payment = Appointment.objects.filter(
            patient=patient,
            status='completed'
        ).exclude(
            payments__isnull=False
        ).select_related('service', 'assigned_dentist').order_by('-appointment_date')
        
        # Check for overdue payments
        overdue_payments = all_payments.filter(
            status__in=['pending', 'partially_paid'],
            next_due_date__isnull=False,
            next_due_date__lt=date.today()
        )
        
        # Get next upcoming due date
        next_due_payment = all_payments.filter(
            status__in=['pending', 'partially_paid'],
            next_due_date__isnull=False,
            next_due_date__gte=date.today()
        ).order_by('next_due_date').first()
        
        # Calculate payment progress percentage
        payment_progress = 0
        if total_amount_due > 0:
            payment_progress = (total_amount_paid / total_amount_due) * 100
        
        context.update({
            'all_payments': all_payments,
            'total_amount_due': total_amount_due,
            'total_amount_paid': total_amount_paid,
            'outstanding_balance': outstanding_balance,
            'payment_progress': payment_progress,
            'pending_payments': pending_payments,
            'partially_paid_payments': partially_paid_payments,
            'completed_payments': completed_payments,
            'completed_appointments_without_payment': completed_appointments_without_payment,
            'overdue_payments': overdue_payments,
            'next_due_payment': next_due_payment,
            'has_outstanding': outstanding_balance > 0,
        })
        
        return context


class PaymentCreateView(LoginRequiredMixin, CreateView):
    """Enhanced payment creation with dynamic service items"""
    model = Payment
    form_class = PaymentForm
    template_name = 'payment/payment_form.html'
    
    def dispatch(self, request, *args, **kwargs):
        # Get appointment from URL parameter
        self.appointment = get_object_or_404(Appointment, pk=self.kwargs.get('appointment_pk'))

        if not hasattr(request.user, 'has_permission') or not request.user.has_permission('billing'):
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('core:dashboard')
        
        # Check if payment already exists for this appointment
        existing_payment = Payment.objects.filter(appointment=self.appointment).first()
        if existing_payment:
            messages.info(request, 'Payment record already exists for this appointment.')
            return redirect('appointments:payment_detail', pk=existing_payment.pk)
        
        return super().dispatch(request, *args, **kwargs)
    
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['appointment'] = self.appointment
        return kwargs
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['appointment'] = self.appointment
        
        # Add services and discounts data for JavaScript
        services_data = []
        for service in Service.active.all():
            services_data.append({
                'id': service.id,
                'name': service.name,
                'min_price': float(service.min_price or 0),
                'max_price': float(service.max_price or 999999),
            })
        
        discounts_data = []
        for discount in Discount.objects.filter(is_active=True):
            discounts_data.append({
                'id': discount.id,
                'name': discount.name,
                'is_percentage': discount.is_percentage,
                'amount': float(discount.amount),  # FIXED: Changed 'value' to 'amount'
            })
        
        context['services_json'] = json.dumps(services_data)
        context['discounts_json'] = json.dumps(discounts_data)
        
        return context
    
    def form_valid(self, form):
        form.instance.appointment = self.appointment
        form.instance.patient = self.appointment.patient
        
        # Check for admin override if needed
        admin_override_confirmed = self.request.POST.get('admin_override_confirmed')
        
        try:
            validated_items = form.cleaned_data['service_items_data']
            
            # Check if admin override is required but not confirmed
            requires_override = any(item.get('requires_admin_override', False) for item in validated_items)
            
            if requires_override and not admin_override_confirmed:
                messages.error(self.request, 'Admin override required for price violations.')
                return self.form_invalid(form)
            
            with transaction.atomic():
                # Save payment instance
                response = super().form_valid(form)
                payment = form.instance
                
                # Create payment items
                total_amount = Decimal('0')
                
                for item_data in validated_items:
                    payment_item = PaymentItem.objects.create(
                        payment=payment,
                        service=item_data['service'],
                        quantity=item_data['quantity'],
                        unit_price=item_data['unit_price'],
                        discount=item_data['discount'],
                        notes=item_data['notes']
                    )
                    total_amount += payment_item.total
                
                # Apply total discount if specified
                discount_application = form.cleaned_data.get('discount_application')
                if discount_application == 'total' and form.cleaned_data.get('total_discount'):
                    total_discount = form.cleaned_data['total_discount']
                    if total_discount.is_percentage:
                        discount_amount = total_amount * (total_discount.amount / 100)
                    else:
                        discount_amount = min(total_discount.amount, total_amount)
                    
                    if discount_amount > 0:
                        PaymentItem.objects.create(
                            payment=payment,
                            service=Service.active.all().first(),
                            quantity=1,
                            unit_price=-discount_amount,
                            notes=f'Total discount: {total_discount.name}'
                        )
                        total_amount -= discount_amount
                
                # Update payment total amount
                payment.total_amount = max(total_amount, Decimal('0'))
                payment.save()
                
                messages.success(self.request, f'Payment record created successfully for {self.appointment.patient.full_name}.')
                
            return response
                
        except Exception as e:
            messages.error(self.request, f'Error creating payment record: {str(e)}')
            return self.form_invalid(form)
    
    def get_success_url(self):
        return reverse_lazy('appointments:payment_detail', kwargs={'pk': self.object.pk})


@login_required
def verify_admin_password(request):
    """AJAX endpoint to verify admin password for price overrides"""
    if not hasattr(request.user, 'has_permission') or not request.user.has_permission('billing'):
        return JsonResponse({'error': 'Permission denied'}, status=403)
    
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    try:
        data = json.loads(request.body)
        password = data.get('password')
        
        if not password:
            return JsonResponse({'valid': False, 'error': 'Password is required'})
        
        # Check if user is admin and password is correct
        if not request.user.check_password(password):
            return JsonResponse({'valid': False, 'error': 'Invalid password'})
        
        # Check admin role
        is_admin = (
            getattr(request.user, 'is_superuser', False) or
            (hasattr(request.user, 'role') and request.user.role and 
             request.user.role.name == 'admin')
        )
        
        if not is_admin:
            return JsonResponse({'valid': False, 'error': 'Admin privileges required'})
        
        return JsonResponse({'valid': True})
        
    except Exception as e:
        return JsonResponse({'valid': False, 'error': 'Verification failed'})


@login_required
def add_payment_item(request, payment_pk):
    """Add service item to payment via AJAX"""
    if not hasattr(request.user, 'has_permission') or not request.user.has_permission('billing'):
        return JsonResponse({'error': 'Permission denied'}, status=403)
    
    payment = get_object_or_404(Payment, pk=payment_pk)
    
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            
            service = get_object_or_404(Service, pk=data['service_id'])
            
            # Validate unit price against service price range
            unit_price = Decimal(str(data['unit_price']))
            if service.min_price and unit_price < service.min_price:
                return JsonResponse({
                    'error': f'Price must be at least ₱{service.min_price}'
                }, status=400)
            
            if service.max_price and unit_price > service.max_price:
                return JsonResponse({
                    'error': f'Price cannot exceed ₱{service.max_price}'
                }, status=400)
            
            # Get discount if specified
            discount = None
            if data.get('discount_id'):
                discount = get_object_or_404(Discount, pk=data['discount_id'])
            
            with transaction.atomic():
                # Create payment item
                item = PaymentItem.objects.create(
                    payment=payment,
                    service=service,
                    quantity=int(data['quantity']),
                    unit_price=unit_price,
                    discount=discount,
                    notes=data.get('notes', '')
                )
                
                # Update payment total
                payment.total_amount = payment.calculate_total_from_items()
                payment.save()
                payment.update_status()
            
            # Add success message
            messages.success(request, f'Service item "{service.name}" added successfully.')
            
            return JsonResponse({
                'success': True,
                'item': {
                    'id': item.id,
                    'service_name': service.name,
                    'quantity': item.quantity,
                    'unit_price': float(item.unit_price),
                    'subtotal': float(item.subtotal),
                    'discount_amount': float(item.discount_amount),
                    'total': float(item.total),
                },
                'payment_total': float(payment.total_amount),
                'outstanding_balance': float(payment.outstanding_balance)
            })
            
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)
    
    return JsonResponse({'error': 'Method not allowed'}, status=405)


@login_required
def delete_payment_item(request, pk):
    """Delete payment item"""
    if not hasattr(request.user, 'has_permission') or not request.user.has_permission('billing'):
        return JsonResponse({'error': 'Permission denied'}, status=403)
    
    if request.method == 'POST':
        item = get_object_or_404(PaymentItem, pk=pk)
        payment = item.payment
        service_name = item.service.name
        
        with transaction.atomic():
            item.delete()
            # Recalculate payment total
            payment.total_amount = payment.calculate_total_from_items()
            payment.save()
            payment.update_status()
        
        # Add success message
        messages.success(request, f'Service item "{service_name}" removed successfully.')
        
        return JsonResponse({'success': True})
    
    return JsonResponse({'error': 'Method not allowed'}, status=405)


@login_required
def add_payment_transaction(request, payment_pk):
    """Add cash payment transaction"""
    if not hasattr(request.user, 'has_permission') or not request.user.has_permission('billing'):
        return JsonResponse({'error': 'Permission denied'}, status=403)
    
    payment = get_object_or_404(Payment, pk=payment_pk)
    
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            amount = Decimal(str(data['amount']))
            payment_date = datetime.strptime(data['payment_date'], '%Y-%m-%d').date()
            payment_type = data.get('payment_type', 'full')
            
            if amount <= 0:
                return JsonResponse({'error': 'Payment amount must be greater than 0'}, status=400)
            
            if amount > payment.outstanding_balance:
                return JsonResponse({'error': 'Payment amount cannot exceed outstanding balance'}, status=400)
            
            with transaction.atomic():
                # Handle installment setup
                if payment_type == 'installment' and payment.payment_type != 'installment':
                    installment_months = int(data.get('installment_months', 1))
                    payment.setup_installment(installment_months)
                
                # Create payment transaction with created_by field
                transaction_record = PaymentTransaction.objects.create(
                    payment=payment,
                    amount=amount,
                    payment_date=payment_date,
                    notes=data.get('notes', f'Cash payment - P{amount}'),
                    created_by=request.user  # Track who processed this payment
                )
                
                # Update payment amounts
                payment.amount_paid += amount
                
                # Update next due date for installments
                if payment.payment_type == 'installment' and not payment.is_fully_paid:
                    if payment.next_due_date and payment.next_due_date <= date.today():
                        payment.next_due_date = payment.next_due_date + timedelta(days=30)
                
                payment.save()
                payment.update_status()
            
            # Add success message
            messages.success(
                request, 
                f'Payment of ₱{amount:,.2f} recorded successfully. Receipt: {transaction_record.receipt_number}'
            )
            
            return JsonResponse({
                'success': True,
                'payment_status': payment.status,
                'amount_paid': float(payment.amount_paid),
                'outstanding_balance': float(payment.outstanding_balance),
                'receipt_number': transaction_record.receipt_number,
                'next_due_date': payment.next_due_date.strftime('%Y-%m-%d') if payment.next_due_date else None
            })
            
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)
    
    return JsonResponse({'error': 'Method not allowed'}, status=405)


@login_required
def payment_dashboard(request):
    """Payment dashboard with key metrics"""
    if not hasattr(request.user, 'has_permission') or not request.user.has_permission('billing'):
        messages.error(request, 'You do not have permission to access this page.')
        return redirect('core:dashboard')
    
    today = date.today()
    this_month = today.replace(day=1)
    
    # Key metrics
    metrics = {
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
        )['total'] or 0,
        
        'overdue_payments': Payment.objects.filter(
            next_due_date__lt=today,
            status__in=['pending', 'partially_paid']
        ).count(),
        
        'this_month_revenue': PaymentTransaction.objects.filter(
            payment_date__gte=this_month
        ).aggregate(Sum('amount'))['amount__sum'] or 0,
        
        'pending_payments': Payment.objects.filter(status='pending').count(),
        
        'completed_this_month': Payment.objects.filter(
            status='completed',
            updated_at__date__gte=this_month
        ).count(),
    }
    
    # Recent transactions
    recent_transactions = PaymentTransaction.objects.select_related(
        'payment__patient', 'created_by'
    ).order_by('-payment_datetime')[:10]
    
    # Overdue payments
    overdue_payments = Payment.objects.filter(
        next_due_date__lt=today,
        status__in=['pending', 'partially_paid']
    ).select_related('patient').order_by('next_due_date')[:10]
    
    context = {
        'metrics': metrics,
        'recent_transactions': recent_transactions,
        'overdue_payments': overdue_payments,
    }
    
    return render(request, 'payment/payment_dashboard.html', context)


@login_required
def receipt_pdf(request, transaction_pk):
    """Generate PDF receipt for a payment transaction"""
    if not hasattr(request.user, 'has_permission') or not request.user.has_permission('billing'):
        messages.error(request, 'You do not have permission to access this page.')
        return redirect('core:dashboard')
    
    transaction_obj = get_object_or_404(
        PaymentTransaction.objects.select_related(
            'payment__patient',
            'payment__appointment__service',
            'payment__appointment__assigned_dentist',
            'created_by'
        ),
        pk=transaction_pk
    )
    
    payment = transaction_obj.payment
    
    # Get all payment items
    payment_items = payment.items.all().select_related('service', 'discount')
    
    # Calculate payment summary
    subtotal = sum(item.subtotal for item in payment_items)
    total_discount = sum(item.discount_amount for item in payment_items)
    
    # Get all previous transactions (excluding current one, ordered by date)
    previous_transactions = payment.transactions.filter(
        payment_datetime__lt=transaction_obj.payment_datetime
    ).order_by('payment_datetime')
    
    # Calculate previous payments total
    previous_payments_total = sum(t.amount for t in previous_transactions)
    
    # Get clinic settings from SystemSetting model
    from core.models import SystemSetting
    
    clinic_name = SystemSetting.get_setting('clinic_name', 'KingJoy Dental Clinic')
    clinic_address = SystemSetting.get_setting('clinic_address', '54 Obanic St.\nQuezon City, Metro Manila')
    clinic_phone = SystemSetting.get_setting('clinic_phone', '+63 956 631 6581')
    clinic_email = SystemSetting.get_setting('clinic_email', 'papatmyfrend@gmail.com')
    
    context = {
        'transaction': transaction_obj,
        'payment': payment,
        'patient': payment.patient,
        'appointment': payment.appointment,
        'payment_items': payment_items,
        'subtotal': subtotal,
        'total_discount': total_discount,
        'previous_payments_total': previous_payments_total,
        'previous_transactions': previous_transactions,
        'clinic_name': clinic_name,
        'clinic_address': clinic_address,
        'clinic_phone': clinic_phone,
        'clinic_email': clinic_email,
    }
    
    try:
        # Render HTML template
        html_string = render_to_string('payment/receipt_pdf.html', context)
        
        # Create PDF
        response = HttpResponse(content_type='application/pdf')
        filename = f'Receipt_{transaction_obj.receipt_number}.pdf'
        response['Content-Disposition'] = f'inline; filename="{filename}"'
        
        # Generate PDF
        pisa_status = pisa.CreatePDF(
            html_string,
            dest=response,
        )
        
        # Check for errors
        if pisa_status.err:
            messages.error(request, 'Error generating PDF receipt. Please try again.')
            return redirect('appointments:payment_detail', pk=payment.pk)
        
        return response
        
    except Exception as e:
        messages.error(request, f'Error generating receipt: {str(e)}')
        return redirect('appointments:payment_detail', pk=payment.pk)