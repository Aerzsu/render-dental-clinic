# appointments/payment_views.py - Updated with enhanced payment creation
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.urls import reverse_lazy
from django.views.generic import ListView, DetailView, CreateView, UpdateView
from django.db.models import Q, Sum, Case, When, DecimalField, F
from django.http import JsonResponse, HttpResponse
from django.db import transaction
from decimal import Decimal
from datetime import date, timedelta, datetime
import json

# PDF generation imports
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from io import BytesIO

from .models import Appointment, Payment, PaymentItem, PaymentTransaction
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
        if status:
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
        
        # Outstanding balance filter
        balance_filter = self.request.GET.get('balance')
        if balance_filter == 'has_balance':
            # Show only payments with outstanding balance
            queryset = queryset.extra(
                where=["total_amount > amount_paid"]
            )
        elif balance_filter == 'no_balance':
            # Show only fully paid
            queryset = queryset.extra(
                where=["total_amount <= amount_paid"]
            )
        
        # Overdue filter
        overdue = self.request.GET.get('overdue')
        if overdue == 'yes':
            today = date.today()
            queryset = queryset.filter(
                next_due_date__lt=today,
                status__in=['pending', 'partially_paid']
            )
        
        # Search by patient name
        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(
                Q(patient__first_name__icontains=search) |
                Q(patient__last_name__icontains=search)
            )
        
        return queryset.order_by('-created_at')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Current filters for form population
        context['filters'] = {
            'status': self.request.GET.get('status', ''),
            'amount_min': self.request.GET.get('amount_min', ''),
            'amount_max': self.request.GET.get('amount_max', ''),
            'date_from': self.request.GET.get('date_from', ''),
            'date_to': self.request.GET.get('date_to', ''),
            'balance': self.request.GET.get('balance', ''),
            'overdue': self.request.GET.get('overdue', ''),
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
        context['transactions'] = payment.transactions.all().order_by('-payment_datetime')
        
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
        context['available_services'] = Service.objects.filter(is_archived=False).order_by('name')
        
        # Available discounts
        context['available_discounts'] = Discount.objects.filter(is_active=True).order_by('name')
        
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
        for service in Service.objects.filter(is_archived=False):
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
                'is_percentage': discount.is_percentage,  # Boolean field
                'value': float(discount.amount),  # Using 'amount' field from model
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
                # This should not happen if frontend validation works properly
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
                    # FIX: Use is_percentage instead of discount_type, and amount instead of value
                    if total_discount.is_percentage:
                        discount_amount = total_amount * (total_discount.amount / 100)
                    else:
                        discount_amount = min(total_discount.amount, total_amount)
                    
                    if discount_amount > 0:
                        PaymentItem.objects.create(
                            payment=payment,
                            service=Service.objects.filter(is_archived=False).first(),  # Use any service as placeholder
                            quantity=1,
                            unit_price=-discount_amount,  # Negative amount for discount
                            notes=f'Total discount: {total_discount.name}'
                        )
                        total_amount -= discount_amount
                
                # Update payment total amount
                payment.total_amount = max(total_amount, Decimal('0'))
                payment.save()
                
                messages.success(self.request, f'Payment record created for {self.appointment.patient.full_name}')
                
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
        
        # Check admin role (adjust based on your user model)
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
    if not hasattr(request.user, 'has_permission') or not request.user.has_permission('billing'):
        return JsonResponse({'error': 'Permission denied'}, status=403)
    
    if request.method == 'POST':
        item = get_object_or_404(PaymentItem, pk=pk)
        payment = item.payment
        
        with transaction.atomic():
            item.delete()
            # Recalculate payment total
            payment.total_amount = payment.calculate_total_from_items()
            payment.save()
            payment.update_status()
        
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
                return JsonResponse({'error': 'Payment cannot exceed outstanding balance'}, status=400)
            
            with transaction.atomic():
                # Handle installment setup
                if payment_type == 'installment' and payment.payment_type != 'installment':
                    installment_months = int(data.get('installment_months', 1))
                    payment.setup_installment(installment_months)
                
                # Add payment
                payment.add_payment(amount, payment_date)
                
                # Get the latest transaction
                latest_transaction = payment.transactions.first()
            
            return JsonResponse({
                'success': True,
                'payment_status': payment.status,
                'amount_paid': float(payment.amount_paid),
                'outstanding_balance': float(payment.outstanding_balance),
                'receipt_number': latest_transaction.receipt_number if latest_transaction else None,
                'next_due_date': payment.next_due_date.strftime('%Y-%m-%d') if payment.next_due_date else None
            })
            
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)
    
    return JsonResponse({'error': 'Method not allowed'}, status=405)


@login_required
def generate_receipt_pdf(request, transaction_pk):
    """Generate PDF receipt for payment transaction"""
    if not hasattr(request.user, 'has_permission') or not request.user.has_permission('billing'):
        messages.error(request, 'You do not have permission to access this page.')
        return redirect('core:dashboard')
    
    transaction = get_object_or_404(PaymentTransaction, pk=transaction_pk)
    payment = transaction.payment
    
    # Create PDF
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=18)
    
    # Container for the 'Flowable' objects
    elements = []
    
    # Define styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=18,
        spaceAfter=30,
        alignment=1,  # Center alignment
    )
    
    header_style = ParagraphStyle(
        'CustomHeader',
        parent=styles['Heading2'],
        fontSize=14,
        spaceAfter=12,
    )
    
    # Clinic header
    elements.append(Paragraph("DENTAL CLINIC RECEIPT", title_style))
    elements.append(Spacer(1, 12))
    
    # Receipt details
    receipt_data = [
        ['Receipt Number:', transaction.receipt_number],
        ['Date:', transaction.payment_date.strftime('%B %d, %Y')],
        ['Time:', transaction.payment_datetime.strftime('%I:%M %p')],
        ['Patient:', payment.patient.full_name],
        ['Service Date:', payment.appointment.appointment_date.strftime('%B %d, %Y')],
    ]
    
    receipt_table = Table(receipt_data, colWidths=[2*inch, 3*inch])
    receipt_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    
    elements.append(receipt_table)
    elements.append(Spacer(1, 24))
    
    # Services performed
    elements.append(Paragraph("Services Performed", header_style))
    
    service_data = [['Service', 'Qty', 'Unit Price', 'Discount', 'Total']]
    for item in payment.items.all():
        service_data.append([
            item.service.name,
            str(item.quantity),
            f'₱{item.unit_price:,.2f}',
            f'₱{item.discount_amount:,.2f}' if item.discount_amount else '₱0.00',
            f'₱{item.total:,.2f}'
        ])
    
    service_table = Table(service_data, colWidths=[2.5*inch, 0.5*inch, 1*inch, 1*inch, 1*inch])
    service_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
    ]))
    
    elements.append(service_table)
    elements.append(Spacer(1, 24))
    
    # Payment summary
    elements.append(Paragraph("Payment Summary", header_style))
    
    summary_data = [
        ['Total Amount:', f'₱{payment.total_amount:,.2f}'],
        ['This Payment:', f'₱{transaction.amount:,.2f}'],
        ['Total Paid:', f'₱{payment.amount_paid:,.2f}'],
        ['Outstanding Balance:', f'₱{payment.outstanding_balance:,.2f}'],
    ]
    
    summary_table = Table(summary_data, colWidths=[2*inch, 2*inch])
    summary_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LINEBELOW', (0, -1), (-1, -1), 2, colors.black),
    ]))
    
    elements.append(summary_table)
    elements.append(Spacer(1, 24))
    
    # Payment method and notes
    elements.append(Paragraph("Payment Details", header_style))
    payment_details = [
        ['Payment Method:', 'Cash'],
        ['Notes:', transaction.notes or 'No additional notes'],
    ]
    
    if payment.next_due_date and payment.outstanding_balance > 0:
        payment_details.append(['Next Payment Due:', payment.next_due_date.strftime('%B %d, %Y')])
    
    details_table = Table(payment_details, colWidths=[2*inch, 3*inch])
    details_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    
    elements.append(details_table)
    elements.append(Spacer(1, 48))
    
    # Footer
    elements.append(Paragraph("Thank you for your payment!", styles['Normal']))
    elements.append(Spacer(1, 12))
    elements.append(Paragraph("Please keep this receipt for your records.", styles['Normal']))
    
    # Build PDF
    doc.build(elements)
    
    # Get the value of the BytesIO buffer and write it to the response
    pdf = buffer.getvalue()
    buffer.close()
    
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="receipt_{transaction.receipt_number}.pdf"'
    response.write(pdf)
    
    return response


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
        # Calculate outstanding balance using F expressions
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
        'payment__patient'
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