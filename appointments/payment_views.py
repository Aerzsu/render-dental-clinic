# appointments/payment_views.py - UPDATED with receipt functionality and proper messages
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
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

from .models import Appointment, Payment, PaymentItem, PaymentItemProduct, PaymentTransaction, TreatmentRecord
from patients.models import Patient
from .forms import PaymentForm, AdminOverrideForm
from services.models import Product, ProductCategory, Service, Discount


class PaymentListView(LoginRequiredMixin, ListView):
    """Payment list with filtering capabilities"""
    model = Payment
    template_name = 'payment/payment_list.html'
    context_object_name = 'payments'
    paginate_by = 10
    
    def dispatch(self, request, *args, **kwargs):
        if not hasattr(request.user, 'has_permission') or not request.user.has_permission('billing'):
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('core:dashboard')
        return super().dispatch(request, *args, **kwargs)
    
    def get_queryset(self):
        queryset = Payment.objects.select_related('patient', 'appointment__service').prefetch_related('items', 'items__products', 'transactions')
        
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
        ).order_by('-appointment_date')
        
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
    """Payment detail view with products breakdown"""
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
        
        # Get all payment items with their products
        payment_items = payment.items.all().select_related('service', 'discount').prefetch_related(
            'products__product__category'
        )
        
        context['payment_items'] = payment_items
        context['transactions'] = payment.transactions.all().select_related('created_by').order_by('-payment_datetime')
        
        # Calculate detailed breakdown
        services_subtotal = Decimal('0')
        products_subtotal = Decimal('0')
        total_discount = Decimal('0')
        
        for item in payment_items:
            # Skip negative adjustment items (total discounts)
            if item.price < 0:
                continue
            
            services_subtotal += item.price
            products_subtotal += item.products_total
            total_discount += item.discount_amount
        
        context['payment_summary'] = {
            'services_subtotal': services_subtotal,
            'products_subtotal': products_subtotal,
            'subtotal': services_subtotal + products_subtotal,
            'total_discount': total_discount,
            'total_amount': payment.total_amount,
            'amount_paid': payment.amount_paid,
            'outstanding_balance': payment.outstanding_balance,
            'payment_progress': payment.payment_progress_percentage,
        }
        
        # Available services and discounts for adding items
        context['available_services'] = Service.active.all().order_by('name')
        context['available_discounts'] = Discount.objects.filter(is_active=True).order_by('name')
        
        # Available products grouped by category
        products_by_category = {}
        for product in Product.objects.filter(is_active=True).select_related('category').order_by('category__display_order', 'category__name', 'name'):
            cat_name = product.category.name
            if cat_name not in products_by_category:
                products_by_category[cat_name] = []
            products_by_category[cat_name].append(product)
        
        context['products_by_category'] = products_by_category
        context['today'] = timezone.now().date()
        
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
    """Enhanced invoice creation with smart pre-fill from treatment record"""
    model = Payment
    form_class = PaymentForm
    template_name = 'payment/payment_form.html'
    
    def dispatch(self, request, *args, **kwargs):
        # Get appointment from URL parameter
        self.appointment = get_object_or_404(Appointment, pk=self.kwargs.get('appointment_pk'))

        if not hasattr(request.user, 'has_permission') or not request.user.has_permission('billing'):
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('core:dashboard')
        
        # Check if invoice already exists for this appointment
        existing_payment = Payment.objects.filter(appointment=self.appointment).first()
        if existing_payment:
            messages.info(request, 'Invoice already exists for this appointment.')
            return redirect('appointments:payment_detail', pk=existing_payment.pk)
        
        return super().dispatch(request, *args, **kwargs)
    
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['appointment'] = self.appointment
        return kwargs
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['appointment'] = self.appointment
        
        # Check if treatment record exists and has services
        treatment_record = None
        treatment_services = []
        treatment_products = []
        
        try:
            treatment_record = self.appointment.treatment_record
            # Get services from treatment record
            treatment_services_qs = treatment_record.services.all().select_related('service')
            
            for tr_service in treatment_services_qs:
                service_products = []
                # Get products for this service from treatment record
                for product_link in tr_service.products.all().select_related('product__category'):
                    service_products.append({
                        'id': product_link.product.id,
                        'name': product_link.product.name,
                        'category_name': product_link.product.category.name,
                        'quantity': product_link.quantity,
                        'unit_price': float(product_link.product.price),
                        'notes': product_link.notes or ''
                    })
                
                treatment_services.append({
                    'service_id': tr_service.service.id,
                    'service_name': tr_service.service.name,
                    'min_price': float(tr_service.service.min_price or 0),
                    'max_price': float(tr_service.service.max_price or 999999),
                    'default_price': float(tr_service.service.min_price or 0),
                    'products': service_products
                })
                
        except TreatmentRecord.DoesNotExist:
            pass
        
        # NEW: Smart pre-fill logic
        if treatment_services:
            # Use treatment record data (what was actually performed)
            initial_items = treatment_services
            context['data_source'] = 'treatment_record'
            context['data_source_message'] = 'Services and products pre-filled from treatment record (what was actually performed)'
        else:
            # Fallback to booked service
            initial_items = [{
                'service_id': self.appointment.service.id,
                'service_name': self.appointment.service.name,
                'min_price': float(self.appointment.service.min_price or 0),
                'max_price': float(self.appointment.service.max_price or 999999),
                'default_price': float(self.appointment.service.min_price or 0),
                'products': []
            }]
            context['data_source'] = 'appointment'
            context['data_source_message'] = 'Service pre-filled from appointment booking (update if actual service differed)'
        
        # Add services data
        services_data = []
        for service in Service.active.all():
            services_data.append({
                'id': service.id,
                'name': service.name,
                'min_price': float(service.min_price or 0),
                'max_price': float(service.max_price or 999999),
                'default_price': float(service.min_price or 0),
            })

        # Add discounts data for JavaScript
        discounts_data = []
        for discount in Discount.objects.filter(is_active=True):
            discounts_data.append({
                'id': discount.id,
                'name': discount.name,
                'is_percentage': discount.is_percentage,
                'amount': float(discount.amount),
            })
        
        # Add products data for JavaScript
        products_data = []
        for product in Product.objects.filter(is_active=True).select_related('category'):
            products_data.append({
                'id': product.id,
                'name': product.name,
                'category_id': product.category.id,
                'category_name': product.category.name,
                'price': float(product.price),
            })
        
        # Add categories data for JavaScript
        categories_data = []
        for category in ProductCategory.objects.all():
            categories_data.append({
                'id': category.id,
                'name': category.name,
            })
        
        context['services_json'] = json.dumps(services_data)
        context['discounts_json'] = json.dumps(discounts_data)
        context['products_json'] = json.dumps(products_data)
        context['categories_json'] = json.dumps(categories_data)
        context['initial_items_json'] = json.dumps(initial_items)  # NEW: Pre-filled items
        
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
                
                # Create payment items with products
                total_amount = Decimal('0')
                
                for item_data in validated_items:
                    # Create payment item
                    payment_item = PaymentItem.objects.create(
                        payment=payment,
                        service=item_data['service'],
                        price=item_data['price'],
                        discount=item_data['discount'],
                        notes=item_data['notes']
                    )
                    
                    # Create product records for this payment item
                    for product_data in item_data['products']:
                        PaymentItemProduct.objects.create(
                            payment_item=payment_item,
                            product=product_data['product'],
                            quantity=product_data['quantity'],
                            unit_price=product_data['unit_price'],
                            notes=product_data['notes']
                        )
                    
                    # Add to total (uses the updated property that includes products)
                    total_amount += payment_item.total
                
                # Apply total discount if specified
                discount_application = form.cleaned_data.get('discount_application')
                if discount_application == 'total' and form.cleaned_data.get('total_discount'):
                    total_discount = form.cleaned_data['total_discount']
                    
                    # Calculate discount on service base prices only (not products)
                    service_base_total = sum(item.price for item in payment.items.all())
                    
                    if total_discount.is_percentage:
                        discount_amount = service_base_total * (total_discount.amount / 100)
                    else:
                        discount_amount = min(total_discount.amount, service_base_total)
                    
                    if discount_amount > 0:
                        # Create a negative adjustment item for the discount
                        PaymentItem.objects.create(
                            payment=payment,
                            service=Service.active.all().first(),  # Use any service as placeholder
                            price=-discount_amount,
                            notes=f'Total discount: {total_discount.name}'
                        )
                        total_amount -= discount_amount
                
                # Update payment total amount
                payment.total_amount = max(total_amount, Decimal('0'))
                payment.save()
                
                messages.success(
                    self.request, 
                    f'Invoice created successfully for {self.appointment.patient.full_name}.'
                )
                
            return response
                
        except Exception as e:
            messages.error(self.request, f'Error creating invoice: {str(e)}')
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
@require_POST
def add_payment_item(request, payment_pk):
    """Add service item to payment with duplicate detection"""
    if not request.user.has_permission('billing'):
        return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)
    
    payment = get_object_or_404(Payment, pk=payment_pk)
    
    try:
        data = json.loads(request.body)
        service_id = data.get('service_id')
        price = Decimal(data.get('price', 0))
        discount_id = data.get('discount_id')
        notes = data.get('notes', '').strip()
        
        # Validate service
        try:
            service = Service.objects.get(pk=service_id)
        except Service.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Invalid service selected'})
        
        # ✅ NEW: Check for duplicate service
        existing_items = payment.items.filter(service=service, price__gte=0)
        if existing_items.exists():
            # Return special response indicating duplicate
            return JsonResponse({
                'success': False,
                'error': 'duplicate',
                'message': f'Patient already has {service.name} in this payment. Continue?',
                'service_name': service.name
            })
        
        # Validate price within range
        if service.min_price and price < service.min_price:
            return JsonResponse({
                'success': False, 
                'error': f'Price must be at least ₱{service.min_price:,.0f}'
            })
        
        if service.max_price and price > service.max_price:
            return JsonResponse({
                'success': False, 
                'error': f'Price cannot exceed ₱{service.max_price:,.0f}'
            })
        
        # Get discount if provided
        discount = None
        if discount_id:
            try:
                discount = Discount.objects.get(pk=discount_id, is_active=True)
            except Discount.DoesNotExist:
                pass
        
        with transaction.atomic():
            # Create payment item
            payment_item = PaymentItem.objects.create(
                payment=payment,
                service=service,
                price=price,
                discount=discount,
                notes=notes
            )
            
            # Recalculate payment total
            payment.total_amount = payment.calculate_total_from_items()
            payment.save(update_fields=['total_amount'])
            payment.update_status()
            
            messages.success(request, f'Added {service.name} to payment')
            return JsonResponse({'success': True})
            
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid data format'}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@login_required
@require_POST
def force_add_payment_item(request, payment_pk):
    """Force add service item even if duplicate (after user confirmation)"""
    if not request.user.has_permission('billing'):
        return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)
    
    payment = get_object_or_404(Payment, pk=payment_pk)
    
    try:
        data = json.loads(request.body)
        service_id = data.get('service_id')
        price = Decimal(data.get('price', 0))
        discount_id = data.get('discount_id')
        notes = data.get('notes', '').strip()
        
        # Validate service
        try:
            service = Service.objects.get(pk=service_id)
        except Service.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Invalid service selected'})
        
        # Validate price within range
        if service.min_price and price < service.min_price:
            return JsonResponse({
                'success': False, 
                'error': f'Price must be at least ₱{service.min_price:,.0f}'
            })
        
        if service.max_price and price > service.max_price:
            return JsonResponse({
                'success': False, 
                'error': f'Price cannot exceed ₱{service.max_price:,.0f}'
            })
        
        # Get discount if provided
        discount = None
        if discount_id:
            try:
                discount = Discount.objects.get(pk=discount_id, is_active=True)
            except Discount.DoesNotExist:
                pass
        
        with transaction.atomic():
            # Create payment item (skip duplicate check)
            payment_item = PaymentItem.objects.create(
                payment=payment,
                service=service,
                price=price,
                discount=discount,
                notes=notes
            )
            
            # Recalculate payment total
            payment.total_amount = payment.calculate_total_from_items()
            payment.save(update_fields=['total_amount'])
            payment.update_status()
            
            messages.success(request, f'Added {service.name} to payment')
            return JsonResponse({'success': True})
            
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid data format'}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

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
    """Add cash payment transaction with date validation"""
    if not hasattr(request.user, 'has_permission') or not request.user.has_permission('billing'):
        return JsonResponse({'error': 'Permission denied'}, status=403)
    
    payment = get_object_or_404(Payment, pk=payment_pk)
    
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            amount = Decimal(str(data['amount']))
            payment_date = datetime.strptime(data['payment_date'], '%Y-%m-%d').date()
            payment_type = data.get('payment_type', 'full')
            
            # Get today's date
            today = timezone.now().date()
            appointment_date = payment.appointment.appointment_date
            
            # Validate amount
            if amount <= 0:
                return JsonResponse({
                    'error': 'Payment amount must be greater than zero.'
                }, status=400)
            
            if amount > payment.outstanding_balance:
                return JsonResponse({
                    'error': f'Payment amount cannot exceed the outstanding balance of ₱{payment.outstanding_balance:,.2f}.'
                }, status=400)
            
            # NEW: Validate payment date is not before appointment date
            if payment_date < appointment_date:
                formatted_appointment_date = appointment_date.strftime('%B %d, %Y')
                return JsonResponse({
                    'error': f'Payment date cannot be before the appointment date ({formatted_appointment_date}).'
                }, status=400)
            
            # NEW: Validate payment date is not in the future
            if payment_date > today:
                return JsonResponse({
                    'error': 'Payment date cannot be in the future. Please select today or an earlier date.'
                }, status=400)
            
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
                    notes=data.get('notes', f'Cash payment - ₱{amount}'),
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
            
        except ValueError as e:
            return JsonResponse({
                'error': 'Invalid date format. Please use a valid date.'
            }, status=400)
        except Exception as e:
            return JsonResponse({
                'error': f'An error occurred: {str(e)}'
            }, status=400)
    
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
    
    # Get all payment items with products
    payment_items = payment.items.all().select_related('service', 'discount').prefetch_related(
        'products__product__category'
    )
    
    # Calculate payment summary (same as payment detail view)
    services_subtotal = Decimal('0')
    products_subtotal = Decimal('0')
    total_discount = Decimal('0')
    
    for item in payment_items:
        if item.price < 0:
            continue
        services_subtotal += item.price
        products_subtotal += item.products_total
        total_discount += item.discount_amount
    
    payment_summary = {
        'services_subtotal': services_subtotal,
        'products_subtotal': products_subtotal,
        'subtotal': services_subtotal + products_subtotal,
        'total_discount': total_discount,
    }
    
    # Get all previous transactions
    previous_transactions = payment.transactions.filter(
        payment_datetime__lt=transaction_obj.payment_datetime
    ).order_by('payment_datetime')
    
    previous_payments_total = sum(t.amount for t in previous_transactions)
    
    # Get clinic settings
    from core.models import SystemSetting
    
    clinic_name = SystemSetting.get_setting('clinic_name', 'KingJoy Dental Clinic')
    clinic_address = SystemSetting.get_setting('clinic_address', '54 Obanic St.\nQuezon City, Metro Manila')
    clinic_phone = SystemSetting.get_setting('clinic_phone', '+63 956 631 6581')
    clinic_email = SystemSetting.get_setting('clinic_email', 'contact@kingjoydental.com')
    
    context = {
        'transaction': transaction_obj,
        'payment': payment,
        'patient': payment.patient,
        'appointment': payment.appointment,
        'payment_items': payment_items,
        'payment_summary': payment_summary,  # ADD THIS
        'subtotal': payment_summary['subtotal'],  # Keep for backward compatibility
        'total_discount': total_discount,
        'previous_payments_total': previous_payments_total,
        'previous_transactions': previous_transactions,
        'clinic_name': clinic_name,
        'clinic_address': clinic_address,
        'clinic_phone': clinic_phone,
        'clinic_email': clinic_email,
    }
    
    try:
        html_string = render_to_string('payment/receipt_pdf.html', context)
        response = HttpResponse(content_type='application/pdf')
        filename = f'Receipt_{transaction_obj.receipt_number}.pdf'
        response['Content-Disposition'] = f'inline; filename="{filename}"'
        
        pisa_status = pisa.CreatePDF(html_string, dest=response)
        
        if pisa_status.err:
            messages.error(request, 'Error generating PDF receipt. Please try again.')
            return redirect('appointments:payment_detail', pk=payment.pk)
        
        return response
        
    except Exception as e:
        messages.error(request, f'Error generating receipt: {str(e)}')
        return redirect('appointments:payment_detail', pk=payment.pk)