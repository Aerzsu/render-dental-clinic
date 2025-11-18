# appointments/forms.py - Timeslot-based appointment system
from decimal import Decimal, InvalidOperation
import json
from django import forms
from django.forms import modelformset_factory, inlineformset_factory
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import date, datetime, time, timedelta
from django.db import transaction
from django.db.models import Q
from .models import Appointment, TimeSlotConfiguration, Payment, PaymentItem, PaymentTransaction, TreatmentRecordAuditLog, TreatmentRecordProduct, TreatmentRecordService, TreatmentRecord
from patients.models import Patient
from services.models import Product, Service, Discount
from users.models import User
import re
from django.core.validators import validate_email


class AppointmentForm(forms.ModelForm):
    """Form for creating/editing appointments in timeslot system"""
    
    # Add time field for selecting start time
    start_time = forms.TimeField(
        widget=forms.Select(attrs={
            'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500'
        }),
        help_text='Select appointment start time'
    )
    
    class Meta:
        model = Appointment
        fields = [
            'patient', 'service', 'appointment_date', 'start_time',
            'patient_type', 'reason', 'staff_notes', 'status', 'assigned_dentist'
        ]
        widgets = {
            'appointment_date': forms.DateInput(attrs={
                'type': 'date',
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
                'min': timezone.now().date().isoformat()
            }),
            'service': forms.Select(attrs={
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500'
            }),
            'patient_type': forms.Select(attrs={
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500'
            }),
            'reason': forms.Textarea(attrs={
                'rows': 3,
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
                'placeholder': 'Optional: Patient\'s reason for visit'
            }),
            'staff_notes': forms.Textarea(attrs={
                'rows': 3,
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
                'placeholder': 'Internal staff notes (not visible to patient)'
            }),
            'status': forms.Select(attrs={
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500'
            }),
            'assigned_dentist': forms.Select(attrs={
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
                'data-tooltip': 'assigned-dentist-tooltip'  # ✅ Add tooltip reference
            }),
        }
    
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        self.is_creating = kwargs.get('instance') is None or kwargs['instance'].pk is None
        super().__init__(*args, **kwargs)
        
        # Patient field is not rendered in template (using autocomplete instead)
        self.fields['patient'].widget = forms.HiddenInput()
        self.fields['patient'].required = True
        
        # Filter active patients
        self.fields['patient'].queryset = Patient.objects.filter(is_active=True).order_by('last_name', 'first_name')
        
        # Filter active services
        self.fields['service'].queryset = Service.active.all().order_by('name')
        
        # Filter active dentists
        self.fields['assigned_dentist'].queryset = User.objects.filter(is_active_dentist=True).order_by('first_name', 'last_name')
        self.fields['assigned_dentist'].required = False
        
        # ✅ UPDATED: Dynamic help text based on user type
        if self.is_creating:
            if self.user and self.user.is_active_dentist:
                self.fields['assigned_dentist'].help_text = (
                    'Pre-selected as you. Change if booking for another dentist, or clear to leave unassigned.'
                )
            else:
                self.fields['assigned_dentist'].help_text = (
                    'Optional. Leave blank to assign during check-in.'
                )
        else:
            self.fields['assigned_dentist'].help_text = (
                'Change the assigned dentist if needed.'
            )
        
        # Add empty labels
        self.fields['service'].empty_label = "Select a service..."
        self.fields['assigned_dentist'].empty_label = "-- Leave unassigned --"
        
        # Initialize time choices (will be populated via JavaScript based on date/service)
        self.fields['start_time'].widget.choices = [('', 'Select a date first...')]
        
        # If editing existing appointment, set the start_time field
        if self.instance and self.instance.pk:
            self.fields['start_time'].initial = self.instance.start_time
        
        # Handle status field based on context
        if self.is_creating:
            # For new appointments, don't show status field - it will default to 'confirmed'
            self.fields['status'].required = False
            self.fields['status'].widget = forms.HiddenInput()
        else:
            # For editing, status field is shown
            self.fields['status'].required = True
        
        # Adjust field requirements based on user permissions
        if not self.user or not self.user.has_permission('appointments'):
            # Hide staff-only fields for non-staff users
            if 'staff_notes' in self.fields:
                del self.fields['staff_notes']
            if 'status' in self.fields:
                del self.fields['status']
            if 'assigned_dentist' in self.fields:
                del self.fields['assigned_dentist']
    
    def clean_patient(self):
        patient = self.cleaned_data.get('patient')
        if not patient:
            raise ValidationError('Please select a patient from the list.')
        if not patient.is_active:
            raise ValidationError('The selected patient record is not active.')
        return patient
    
    def clean_appointment_date(self):
        appointment_date = self.cleaned_data.get('appointment_date')
        
        if not appointment_date:
            raise ValidationError('Please select an appointment date.')
        
        # Check if date is in the future
        if appointment_date < timezone.now().date():
            raise ValidationError('Appointment date cannot be in the past.')
        # Check if it's not a Sunday
        if appointment_date.weekday() == 6:
            raise ValidationError('Appointments cannot be scheduled on Sundays.')
        
        return appointment_date
    
    def clean_start_time(self):
        start_time = self.cleaned_data.get('start_time')
        
        if not start_time:
            raise ValidationError('Please select a start time.')
        
        return start_time
    
    def clean(self):
        cleaned_data = super().clean()
        appointment_date = cleaned_data.get('appointment_date')
        start_time = cleaned_data.get('start_time')
        service = cleaned_data.get('service')
        patient = cleaned_data.get('patient')
        status = cleaned_data.get('status')
        
        # Set default status for new appointments
        if self.is_creating and self.user and self.user.has_permission('appointments'):
            cleaned_data['status'] = 'confirmed'
        
        # Validate completed/did_not_arrive status for future dates
        if status in ['completed', 'did_not_arrive'] and appointment_date:
            from core.utils import get_manila_today
            today = get_manila_today()
            if appointment_date > today:
                status_display = dict(self.fields['status'].choices).get(status, status)
                raise ValidationError(
                    f'Cannot mark appointment as "{status_display}" for future dates. '
                    f'The appointment is scheduled for {appointment_date.strftime("%B %d, %Y")}.'
                )
        
        if appointment_date and start_time and service:
            # Check if timeslot configuration exists
            config = TimeSlotConfiguration.get_for_date(appointment_date)
            if not config:
                raise ValidationError(
                    f'No timeslots are configured for {appointment_date.strftime("%B %d, %Y")}. '
                    'Please contact the clinic to set up timeslots for this date.'
                )
            
            # Check timeslot availability (excluding current appointment if updating)
            exclude_id = self.instance.id if self.instance.id else None
            
            is_available, message = config.is_timeslot_available(
                start_time,
                service.duration_minutes,
                exclude_appointment_id=exclude_id,
                include_pending=True
            )
            
            if not is_available:
                raise ValidationError(message)
        
        # Check for double-booking (same patient, same date)
        if patient and appointment_date:
            # Build query to find conflicting appointments
            conflicting_appointments = Appointment.objects.filter(
                patient=patient,
                appointment_date=appointment_date,
                status__in=Appointment.BLOCKING_STATUSES  # pending, confirmed, completed
            )
            
            # Exclude current appointment if editing
            if self.instance.id:
                conflicting_appointments = conflicting_appointments.exclude(id=self.instance.id)
            
            if conflicting_appointments.exists():
                existing = conflicting_appointments.first()
                formatted_date = appointment_date.strftime('%B %d, %Y')
                raise ValidationError(
                    f'This patient already has an appointment on {formatted_date} '
                    f'at {existing.start_time.strftime("%I:%M %p")} for {existing.service.name}. '
                    f'Please choose a different date or time.'
                )
        
        return cleaned_data
    
    def save(self, commit=True):
        instance = super().save(commit=False)
        
        # Set default status for new appointments if not already set
        if self.is_creating and not instance.status:
            if self.user and self.user.has_permission('appointments'):
                instance.status = 'confirmed'
            else:
                instance.status = 'pending'
        
        if commit:
            instance.save()
        
        return instance

class TimeSlotConfigurationForm(forms.ModelForm):
    """Form for managing daily timeslot configurations"""
    
    class Meta:
        model = TimeSlotConfiguration
        fields = ['date', 'start_time', 'end_time', 'notes']
        widgets = {
            'date': forms.DateInput(attrs={
                'type': 'date',
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500'
            }),
            'start_time': forms.TimeInput(attrs={
                'type': 'time',
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
                'step': '1800'  # 30-minute increments
            }),
            'end_time': forms.TimeInput(attrs={
                'type': 'time',
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
                'step': '1800'  # 30-minute increments
            }),
            'notes': forms.Textarea(attrs={
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
                'rows': 2,
                'placeholder': 'Optional notes for this date...'
            })
        }
        help_texts = {
            'start_time': 'Clinic opening time (e.g., 10:00 AM)',
            'end_time': 'Clinic closing time (e.g., 6:00 PM)',
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Set minimum date to today
        today = timezone.now().date()
        self.fields['date'].widget.attrs['min'] = today.strftime('%Y-%m-%d')
        
        # Add help text
        self.fields['start_time'].help_text = 'Time slots will be created in 30-minute increments from this time'
        self.fields['end_time'].help_text = 'Last appointment slot will start before this time'
    
    def clean_date(self):
        date_value = self.cleaned_data.get('date')
        
        if not date_value:
            return date_value
        
        # Check if it's a Sunday
        if date_value.weekday() == 6:  # Sunday
            raise ValidationError(
                'Sundays are not available for appointments. Please choose a different date.'
            )
        
        # For new configurations, check if date already has configuration
        if not self.instance.pk:
            if TimeSlotConfiguration.objects.filter(date=date_value).exists():
                raise ValidationError(
                    f'Time slot configuration already exists for {date_value.strftime("%B %d, %Y")}. '
                    'Please edit the existing configuration instead.'
                )
        
        return date_value
    
    def clean_start_time(self):
        start_time = self.cleaned_data.get('start_time')
        
        if not start_time:
            return start_time
        
        # Validate time is in 30-minute increments
        if start_time.minute not in [0, 30]:
            raise ValidationError('Start time must be in 30-minute increments (e.g., 10:00, 10:30)')
        
        return start_time
    
    def clean_end_time(self):
        end_time = self.cleaned_data.get('end_time')
        
        if not end_time:
            return end_time
        
        # Validate time is in 30-minute increments
        if end_time.minute not in [0, 30]:
            raise ValidationError('End time must be in 30-minute increments (e.g., 18:00, 18:30)')
        
        return end_time
    
    def clean(self):
        cleaned_data = super().clean()
        start_time = cleaned_data.get('start_time')
        end_time = cleaned_data.get('end_time')
        
        if start_time and end_time:
            # Ensure start is before end
            if start_time >= end_time:
                raise ValidationError('Start time must be before end time.')
            
            # Calculate duration
            start_dt = datetime.combine(date.today(), start_time)
            end_dt = datetime.combine(date.today(), end_time)
            duration_minutes = (end_dt - start_dt).total_seconds() / 60
            
            # Ensure minimum 30 minutes
            if duration_minutes < 30:
                raise ValidationError('Time slot configuration must span at least 30 minutes.')
        
        return cleaned_data


class BulkTimeSlotConfigurationForm(forms.Form):
    """Form for bulk creating timeslot configurations across a date range"""
    
    start_date = forms.DateField(
        widget=forms.DateInput(attrs={
            'type': 'date',
            'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500'
        }),
        help_text='First date to create timeslots for'
    )
    
    end_date = forms.DateField(
        widget=forms.DateInput(attrs={
            'type': 'date',
            'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500'
        }),
        help_text='Last date to create timeslots for'
    )
    
    start_time = forms.TimeField(
        widget=forms.TimeInput(attrs={
            'type': 'time',
            'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
            'step': '1800'
        }),
        help_text='Clinic opening time (e.g., 10:00 AM)'
    )
    
    end_time = forms.TimeField(
        widget=forms.TimeInput(attrs={
            'type': 'time',
            'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
            'step': '1800'
        }),
        help_text='Clinic closing time (e.g., 6:00 PM)'
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Set minimum date to today
        today = timezone.now().date()
        self.fields['start_date'].widget.attrs['min'] = today.strftime('%Y-%m-%d')
        self.fields['end_date'].widget.attrs['min'] = today.strftime('%Y-%m-%d')
    
    def clean_start_date(self):
        start_date = self.cleaned_data.get('start_date')
        
        if start_date and start_date < timezone.now().date():
            raise ValidationError('Start date cannot be in the past.')
        
        return start_date
    
    def clean_start_time(self):
        start_time = self.cleaned_data.get('start_time')
        
        if start_time and start_time.minute not in [0, 30]:
            raise ValidationError('Start time must be in 30-minute increments (e.g., 10:00, 10:30)')
        
        return start_time
    
    def clean_end_time(self):
        end_time = self.cleaned_data.get('end_time')
        
        if end_time and end_time.minute not in [0, 30]:
            raise ValidationError('End time must be in 30-minute increments (e.g., 18:00, 18:30)')
        
        return end_time
    
    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')
        start_time = cleaned_data.get('start_time')
        end_time = cleaned_data.get('end_time')
        
        # Validate date range
        if start_date and end_date:
            if start_date > end_date:
                raise ValidationError('Start date must be before or equal to end date.')
            
            # Limit range to prevent excessive creation
            days_diff = (end_date - start_date).days
            if days_diff > 90:
                raise ValidationError('Date range cannot exceed 90 days.')
        
        # Validate time range
        if start_time and end_time:
            if start_time >= end_time:
                raise ValidationError('Start time must be before end time.')
            
            start_dt = datetime.combine(date.today(), start_time)
            end_dt = datetime.combine(date.today(), end_time)
            duration_minutes = (end_dt - start_dt).total_seconds() / 60
            
            if duration_minutes < 30:
                raise ValidationError('Time slot configuration must span at least 30 minutes.')
        
        return cleaned_data

class PaymentForm(forms.ModelForm):
    """
    Enhanced payment form with product tracking
    Handles dynamic service items with products
    """
    
    # Hidden field to store JSON data for service items with products
    service_items_data = forms.CharField(
        widget=forms.HiddenInput(),
        required=False,
        help_text="JSON data for service items and their products"
    )
    
    # Discount application choice
    DISCOUNT_CHOICES = [
        ('per_item', 'Apply to Individual Services'),
        ('total', 'Apply to Total Bill'),
    ]
    discount_application = forms.ChoiceField(
        choices=DISCOUNT_CHOICES,
        widget=forms.RadioSelect,
        initial='per_item',
        required=True
    )
    
    # Total discount (when discount_application = 'total')
    total_discount = forms.ModelChoiceField(
        queryset=Discount.objects.filter(is_active=True),
        required=False,
        empty_label="No discount"
    )
    
    class Meta:
        model = Payment
        fields = [
            'payment_type',
            'installment_months',
            'next_due_date',
            'notes'
        ]
        widgets = {
            'payment_type': forms.RadioSelect(choices=Payment.PAYMENT_TYPE_CHOICES),
            'installment_months': forms.NumberInput(attrs={
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
                'min': '1',
                'max': '12'
            }),
            'next_due_date': forms.DateInput(attrs={
                'type': 'date',
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500'
            }),
            'notes': forms.Textarea(attrs={
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
                'rows': 3
            }),
        }
        labels = {
        'notes': 'Pricing Notes (Optional)',
    }
    
    def __init__(self, *args, **kwargs):
        self.appointment = kwargs.pop('appointment', None)
        super().__init__(*args, **kwargs)
        
        # Pre-populate with appointment service
        if self.appointment and not self.data:
            initial_items = [{
                'service_id': self.appointment.service.id,
                'service_name': self.appointment.service.name,
                'price': float(self.appointment.service.min_price or 0),
                'min_price': float(self.appointment.service.min_price or 0),
                'max_price': float(self.appointment.service.max_price or 999999),
                'discount_id': '',
                'notes': '',
                'products': []  # Empty products array
            }]
            self.initial['service_items_data'] = json.dumps(initial_items)
    
    def clean_service_items_data(self):
        """Validate and parse service items JSON data"""
        data = self.cleaned_data.get('service_items_data', '[]')
        
        try:
            items = json.loads(data) if data else []
        except json.JSONDecodeError:
            raise forms.ValidationError('Invalid service items data format.')
        
        if not items:
            raise forms.ValidationError('At least one service must be added to the payment.')
        
        validated_items = []
        
        for idx, item in enumerate(items):
            # Validate service
            try:
                service = Service.objects.get(pk=item.get('service_id'))
            except Service.DoesNotExist:
                raise forms.ValidationError(f'Invalid service selected for item #{idx + 1}.')
            
            # Validate price
            try:
                price = Decimal(str(item.get('price', 0)))
            except (ValueError, TypeError, InvalidOperation):
                raise forms.ValidationError(f'Invalid price for {service.name}.')
            
            if price < Decimal('0'):
                raise forms.ValidationError(f'Price cannot be negative for {service.name}.')
            
            # Check price range
            requires_override = False
            if service.min_price and price < service.min_price:
                requires_override = True
            if service.max_price and price > service.max_price:
                requires_override = True
            
            # Validate discount
            discount = None
            if item.get('discount_id'):
                try:
                    discount = Discount.objects.get(pk=item.get('discount_id'), is_active=True)
                except Discount.DoesNotExist:
                    raise forms.ValidationError(f'Invalid discount for {service.name}.')
            
            # Validate products
            validated_products = []
            for prod_idx, product_data in enumerate(item.get('products', [])):
                try:
                    product = Product.objects.get(pk=product_data.get('product_id'), is_active=True)
                except Product.DoesNotExist:
                    raise forms.ValidationError(f'Invalid product #{prod_idx + 1} for {service.name}.')
                
                try:
                    quantity = int(product_data.get('quantity', 1))
                    if quantity < 1:
                        raise ValueError
                except (ValueError, TypeError):
                    raise forms.ValidationError(f'Invalid quantity for {product.name}.')
                
                validated_products.append({
                    'product': product,
                    'quantity': quantity,
                    'unit_price': product.price,  # Snapshot current price
                    'notes': product_data.get('notes', '').strip()
                })
            
            validated_items.append({
                'service': service,
                'price': price,
                'discount': discount,
                'notes': item.get('notes', '').strip(),
                'products': validated_products,
                'requires_admin_override': requires_override
            })
        
        return validated_items
    
    def clean(self):
        """Cross-field validation"""
        cleaned_data = super().clean()
        
        payment_type = cleaned_data.get('payment_type')
        installment_months = cleaned_data.get('installment_months')
        next_due_date = cleaned_data.get('next_due_date')
        
        # Validate installment requirements
        if payment_type == 'installment':
            if not installment_months or installment_months < 1:
                raise forms.ValidationError('Number of months is required for installment payments.')
            
            if not next_due_date:
                raise forms.ValidationError('First payment due date is required for installment payments.')
        
        # Validate due date is in the future
        if next_due_date and next_due_date < date.today():
            raise forms.ValidationError('Payment due date must be in the future.')
        
        return cleaned_data


class PaymentItemForm(forms.ModelForm):
    """Form for editing individual payment items (used in detail view)"""
    
    class Meta:
        model = PaymentItem
        fields = ['service', 'price', 'discount', 'notes']
        widgets = {
            'service': forms.Select(attrs={
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
                'onchange': 'updateServicePrice(this)'
            }),
            'price': forms.NumberInput(attrs={
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
                'step': '1',
                'min': '1'
            }),
            'discount': forms.Select(attrs={
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500'
            }),
            'notes': forms.TextInput(attrs={
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500'
            }),
        }
        labels = {
            'price': 'Service Fee',
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Filter active services and discounts
        self.fields['service'].queryset = Service.objects.filter(is_archived=False).order_by('name')
        self.fields['discount'].queryset = Discount.objects.filter(is_active=True).order_by('name')
        
        # FORMAT DISCOUNT LABELS
        discount_choices = [('', 'No discount')]
        for discount in Discount.objects.filter(is_active=True).order_by('name'):
            if discount.is_percentage:
                label = f"{discount.name} - {discount.amount}% off"
            else:
                label = f"{discount.name} - ₱{int(round(discount.amount))} off"
            discount_choices.append((discount.id, label))
        
        self.fields['discount'].choices = discount_choices
    
    def clean_price(self):
        price = self.cleaned_data.get('price')
        service = self.cleaned_data.get('service')
        
        if service and price:
            # Check against service price range if available
            if service.min_price and price < service.min_price:
                raise ValidationError(
                    f'Price cannot be below ₱{service.min_price} for {service.name}'
                )
            
            if service.max_price and price > service.max_price:
                raise ValidationError(
                    f'Price cannot exceed ₱{service.max_price} for {service.name}'
                )
        
        return price


class PaymentTransactionForm(forms.ModelForm):
    """Form for adding payment transactions"""
    
    payment_type_choice = forms.ChoiceField(
        choices=[('full', 'Full Payment'), ('partial', 'Partial Payment')],
        widget=forms.RadioSelect(attrs={
            'class': 'focus:ring-primary-500 h-4 w-4 text-primary-600 border-gray-300'
        }),
        initial='partial'
    )
    
    installment_months = forms.IntegerField(
        required=False,
        min_value=1,
        max_value=24,
        widget=forms.NumberInput(attrs={
            'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
            'min': 1,
            'max': 24
        }),
        help_text='Required only for first installment payment'
    )
    
    class Meta:
        model = PaymentTransaction
        fields = ['amount', 'payment_date', 'notes']
        widgets = {
            'amount': forms.NumberInput(attrs={
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
                'step': '0.01',
                'min': '0.01'
            }),
            'payment_date': forms.DateInput(attrs={
                'type': 'date',
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500'
            }),
            'notes': forms.Textarea(attrs={
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
                'rows': 2,
                'placeholder': 'Optional notes about this payment...'
            }),
        }
    
    def __init__(self, *args, **kwargs):
        self.payment = kwargs.pop('payment', None)
        super().__init__(*args, **kwargs)
        
        # 🔧 FIX: Set default payment date to today in Manila timezone
        manila_now = timezone.localtime(timezone.now())
        self.fields['payment_date'].initial = manila_now.date()
        
        if self.payment:
            # Set maximum amount to outstanding balance
            self.fields['amount'].widget.attrs['max'] = str(self.payment.outstanding_balance)
            
            # Set min date to appointment date
            self.fields['payment_date'].widget.attrs['min'] = str(self.payment.appointment.appointment_date)
            
            # Set max date to today (Manila time)
            self.fields['payment_date'].widget.attrs['max'] = str(manila_now.date())
            
            # If payment is already set up for installments, hide installment months
            if self.payment.payment_type == 'installment':
                self.fields['installment_months'].widget = forms.HiddenInput()
    
    def clean_amount(self):
        amount = self.cleaned_data.get('amount')
        
        if self.payment and amount:
            if amount > self.payment.outstanding_balance:
                raise ValidationError(
                    f'Payment amount cannot exceed outstanding balance of ₱{self.payment.outstanding_balance:,.2f}'
                )
            
            if amount <= 0:
                raise ValidationError('Payment amount must be greater than zero.')
        
        return amount
    
    def clean_payment_date(self):
        payment_date = self.cleaned_data.get('payment_date')
        
        if not payment_date:
            return payment_date
        
        # Use Manila timezone for today's date
        manila_now = timezone.localtime(timezone.now())
        today = manila_now.date()
        
        # Validate payment date is not in the future
        if payment_date > today:
            raise ValidationError('Payment date cannot be in the future. Please select today or an earlier date.')
        
        # Validate payment date is not before appointment date
        if self.payment and payment_date < self.payment.appointment.appointment_date:
            formatted_date = self.payment.appointment.appointment_date.strftime('%B %d, %Y')
            raise ValidationError(
                f'Payment date cannot be before the appointment date ({formatted_date}).'
            )
        
        return payment_date


class AdminOverrideForm(forms.Form):
    """Form for admin password confirmation for price overrides"""
    
    admin_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
            'placeholder': 'Enter admin password to override price restrictions'
        }),
        help_text='Admin password required to set prices outside the allowed range'
    )
    
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
    
    def clean_admin_password(self):
        password = self.cleaned_data.get('admin_password')
        
        if not self.user:
            raise ValidationError('User context required for validation.')
        
        # Check if user is admin and password is correct
        if not self.user.check_password(password):
            raise ValidationError('Invalid admin password.')
        
        if not getattr(self.user, 'is_admin', False) and self.user.role.name.lower() != 'admin':
            raise ValidationError('Admin privileges required for price override.')
        
        return password


class PaymentFilterForm(forms.Form):
    """Form for filtering payments in list view"""
    
    STATUS_CHOICES = [('', 'All Statuses')] + Payment.STATUS_CHOICES
    BALANCE_CHOICES = [
        ('', 'All Balances'),
        ('has_balance', 'Has Outstanding Balance'),
        ('no_balance', 'Fully Paid'),
    ]
    OVERDUE_CHOICES = [
        ('', 'All'),
        ('yes', 'Overdue Only'),
    ]
    
    status = forms.ChoiceField(
        choices=STATUS_CHOICES,
        required=False,
        widget=forms.Select(attrs={
            'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500'
        })
    )
    
    amount_min = forms.DecimalField(
        required=False,
        min_value=0,
        decimal_places=2,
        widget=forms.NumberInput(attrs={
            'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
            'placeholder': 'Min amount',
            'step': '0.01'
        })
    )
    
    amount_max = forms.DecimalField(
        required=False,
        min_value=0,
        decimal_places=2,
        widget=forms.NumberInput(attrs={
            'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
            'placeholder': 'Max amount',
            'step': '0.01'
        })
    )
    
    date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'type': 'date',
            'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500'
        })
    )
    
    date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'type': 'date',
            'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500'
        })
    )
    
    balance = forms.ChoiceField(
        choices=BALANCE_CHOICES,
        required=False,
        widget=forms.Select(attrs={
            'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500'
        })
    )
    
    overdue = forms.ChoiceField(
        choices=OVERDUE_CHOICES,
        required=False,
        widget=forms.Select(attrs={
            'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500'
        })
    )
    
    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
            'placeholder': 'Search patient name...'
        })
    )
    
    def clean(self):
        cleaned_data = super().clean()
        amount_min = cleaned_data.get('amount_min')
        amount_max = cleaned_data.get('amount_max')
        date_from = cleaned_data.get('date_from')
        date_to = cleaned_data.get('date_to')
        
        # Validate amount range
        if amount_min and amount_max and amount_min > amount_max:
            raise ValidationError('Minimum amount cannot be greater than maximum amount.')
        
        # Validate date range
        if date_from and date_to and date_from > date_to:
            raise ValidationError('Start date cannot be after end date.')
        
        return cleaned_data
    
class TreatmentRecordForm(forms.ModelForm):
    """Form for documenting treatment during/after appointment"""
    
    # Hidden field to store JSON data for services with products
    services_data = forms.CharField(
        widget=forms.HiddenInput(),
        required=False,
        help_text="JSON data for services and their products"
    )
    
    class Meta:
        model = TreatmentRecord
        fields = ['clinical_notes']
        widgets = {
            'clinical_notes': forms.Textarea(attrs={
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
                'rows': 4,
                'placeholder': 'Document symptoms, diagnosis, procedures performed, and observations...'
            }),
        }
    
    def __init__(self, *args, **kwargs):
        self.appointment = kwargs.pop('appointment', None)
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        # If editing existing record, populate services_data
        if self.instance and self.instance.pk:
            services_list = []
            for service_record in self.instance.service_records.all().prefetch_related('products__product'):
                products_list = []
                for prod in service_record.products.all():
                    products_list.append({
                        'product_id': prod.product.id,
                        'product_name': prod.product.name,
                        'quantity': prod.quantity,
                        'notes': prod.notes
                    })
                
                services_list.append({
                    'service_id': service_record.service.id,
                    'service_name': service_record.service.name,
                    'notes': service_record.notes,
                    'products': products_list
                })
            
            self.initial['services_data'] = json.dumps(services_list)
    
    def clean_services_data(self):
        """Validate and parse services JSON data"""
        data = self.cleaned_data.get('services_data', '[]')
        
        try:
            services = json.loads(data) if data else []
        except json.JSONDecodeError:
            raise forms.ValidationError('Invalid services data format.')
        
        if not services:
            raise forms.ValidationError('At least one service must be documented.')
        
        validated_services = []
        
        for idx, service_data in enumerate(services):
            # Validate service
            try:
                service = Service.objects.get(pk=service_data.get('service_id'))
            except Service.DoesNotExist:
                raise forms.ValidationError(f'Invalid service selected for item #{idx + 1}.')
            
            # Validate products
            validated_products = []
            for prod_idx, product_data in enumerate(service_data.get('products', [])):
                try:
                    product = Product.objects.get(pk=product_data.get('product_id'), is_active=True)
                except Product.DoesNotExist:
                    raise forms.ValidationError(f'Invalid product #{prod_idx + 1} for {service.name}.')
                
                try:
                    quantity = int(product_data.get('quantity', 1))
                    if quantity < 1:
                        raise ValueError
                except (ValueError, TypeError):
                    raise forms.ValidationError(f'Invalid quantity for {product.name}.')
                
                validated_products.append({
                    'product': product,
                    'quantity': quantity,
                    'notes': product_data.get('notes', '').strip()
                })
            
            validated_services.append({
                'service': service,
                'notes': service_data.get('notes', '').strip(),
                'products': validated_products
            })
        
        return validated_services
    
    def save(self, commit=True):
        """Save treatment record with services and products"""
        instance = super().save(commit=False)
        
        if not instance.pk:
            instance.appointment = self.appointment
            instance.created_by = self.user
        
        instance.last_modified_by = self.user
        
        if commit:
            with transaction.atomic():
                # Track changes for audit
                old_data = None
                if instance.pk:
                    old_data = {
                        'clinical_notes': TreatmentRecord.objects.get(pk=instance.pk).clinical_notes,
                        'services': list(instance.service_records.values_list('service_id', flat=True))
                    }
                
                instance.save()
                
                # Clear existing services and products
                instance.service_records.all().delete()
                
                # Create new services and products
                validated_services = self.cleaned_data['services_data']
                for order, service_data in enumerate(validated_services):
                    service_record = TreatmentRecordService.objects.create(
                        treatment_record=instance,
                        service=service_data['service'],
                        notes=service_data['notes'],
                        order=order
                    )
                    
                    for product_data in service_data['products']:
                        TreatmentRecordProduct.objects.create(
                            treatment_service=service_record,
                            product=product_data['product'],
                            quantity=product_data['quantity'],
                            notes=product_data['notes']
                        )
                
                # Create audit log
                TreatmentRecordAuditLog.objects.create(
                    treatment_record=instance,
                    modified_by=self.user,
                    action='updated' if old_data else 'created',
                    changes={
                        'old': old_data,
                        'new': {
                            'clinical_notes': instance.clinical_notes,
                            'services': [s['service'].id for s in validated_services]
                        }
                    }
                )
        
        return instance
    
