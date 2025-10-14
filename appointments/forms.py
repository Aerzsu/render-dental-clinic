# appointments/forms.py - Cleaned for AM/PM slot system
from decimal import Decimal
import json
from django import forms
from django.forms import modelformset_factory, inlineformset_factory
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import date, timedelta
from django.db.models import Q
from .models import Appointment, DailySlots, Payment, PaymentItem, PaymentTransaction
from patients.models import Patient
from services.models import Service, Discount
from users.models import User
import re
from django.core.validators import validate_email

class AppointmentForm(forms.ModelForm):
    """Form for creating/editing appointments in AM/PM system"""
    
    class Meta:
        model = Appointment
        fields = [
            'patient', 'service', 'appointment_date', 'period', 
            'patient_type', 'reason', 'staff_notes', 'status', 'assigned_dentist'
        ]
        widgets = {
            'appointment_date': forms.DateInput(attrs={
                'type': 'date',
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
                'min': timezone.now().date().isoformat()
            }),
            'period': forms.Select(attrs={
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500'
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
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500'
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
        
        # Add empty labels
        self.fields['service'].empty_label = "Select a service..."
        self.fields['assigned_dentist'].empty_label = "Select a dentist (optional)..."
        
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
        if appointment_date <= timezone.now().date():
            raise ValidationError('Please select a future date for the appointment.')
        
        # Check if it's not a Sunday
        if appointment_date.weekday() == 6:
            raise ValidationError('Appointments cannot be scheduled on Sundays.')
        
        return appointment_date
    
    def clean(self):
        cleaned_data = super().clean()
        appointment_date = cleaned_data.get('appointment_date')
        period = cleaned_data.get('period')
        
        # Set default status for new appointments
        if self.is_creating and self.user and self.user.has_permission('appointments'):
            cleaned_data['status'] = 'confirmed'
        
        if appointment_date and period:
            # Check slot availability (excluding current appointment if updating)
            exclude_id = self.instance.id if self.instance.id else None
            
            can_book, message = Appointment.can_book_appointment(
                appointment_date=appointment_date,
                period=period,
                exclude_appointment_id=exclude_id
            )
            
            if not can_book:
                raise ValidationError(f'This time slot is not available. {message}')
        
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


class DailySlotsForm(forms.ModelForm):
    """Form for managing daily AM/PM slot allocations"""
    
    class Meta:
        model = DailySlots
        fields = ['date', 'am_slots', 'pm_slots', 'notes']
        widgets = {
            'date': forms.DateInput(attrs={
                'type': 'date',
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500'
            }),
            'am_slots': forms.NumberInput(attrs={
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
                'min': '0',
                'max': '20'
            }),
            'pm_slots': forms.NumberInput(attrs={
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
                'min': '0',
                'max': '20'
            }),
            'notes': forms.Textarea(attrs={
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
                'rows': 2,
                'placeholder': 'Optional notes for this date...'
            })
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Set minimum date to today
        today = timezone.now().date()
        self.fields['date'].widget.attrs['min'] = today.strftime('%Y-%m-%d')
    
    def clean_date(self):
        date_value = self.cleaned_data.get('date')
        
        if not date_value:
            return date_value
        
        # Check if it's a Sunday
        if date_value.weekday() == 6:  # Sunday
            am_slots = self.cleaned_data.get('am_slots', 0)
            pm_slots = self.cleaned_data.get('pm_slots', 0)
            
            if am_slots > 0 or pm_slots > 0:
                raise ValidationError(
                    'Sundays are not available for appointments. Set both AM and PM slots to 0, or choose a different date.'
                )
        
        return date_value
    
    def clean(self):
        cleaned_data = super().clean()
        am_slots = cleaned_data.get('am_slots', 0)
        pm_slots = cleaned_data.get('pm_slots', 0)
        
        # Ensure at least one slot is set (unless it's Sunday)
        if am_slots == 0 and pm_slots == 0:
            date_value = cleaned_data.get('date')
            if date_value and date_value.weekday() != 6:
                raise ValidationError('Please set at least one slot (AM or PM).')
        
        return cleaned_data


class PublicBookingForm(forms.Form):
    """Public booking form for AM/PM slot system"""
    
    PATIENT_TYPE_CHOICES = [
        ('new', 'New Patient'),
        ('existing', 'Existing Patient')
    ]
    
    # Patient type selection
    patient_type = forms.ChoiceField(
        choices=PATIENT_TYPE_CHOICES,
        widget=forms.RadioSelect(attrs={
            'class': 'focus:ring-primary-500 h-4 w-4 text-primary-600 border-gray-300'
        })
    )
    
    # Existing patient identification
    patient_identifier = forms.CharField(
        max_length=200,
        required=False,
        label='Email or Phone Number',
        help_text='Enter your email address or contact number',
        widget=forms.TextInput(attrs={
            'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
            'placeholder': 'patient@example.com or +639123456789'
        })
    )
    
    # New patient fields
    first_name = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500'
        })
    )
    last_name = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500'
        })
    )
    email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={
            'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500'
        })
    )
    contact_number = forms.CharField(
        max_length=20,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
            'placeholder': '+639123456789'
        })
    )
    address = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
            'rows': 3
        })
    )
    
    # Appointment fields
    service = forms.ModelChoiceField(
        queryset=Service.objects.none(),  # Will be set in __init__
        widget=forms.Select(attrs={
            'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500'
        })
    )
    
    appointment_date = forms.DateField(
        widget=forms.DateInput(attrs={
            'type': 'date',
            'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500'
        })
    )
    
    period = forms.ChoiceField(
        choices=Appointment.PERIOD_CHOICES,
        widget=forms.RadioSelect(attrs={
            'class': 'focus:ring-primary-500 h-4 w-4 text-primary-600 border-gray-300'
        }),
        help_text='Morning (AM): 8:00 AM - 12:00 PM | Afternoon (PM): 1:00 PM - 6:00 PM'
    )
    
    reason = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
            'rows': 3,
            'placeholder': 'Optional: Please describe your symptoms or reason for visit'
        })
    )
    
    # Terms agreement
    agreed_to_terms = forms.BooleanField(
        required=True,
        widget=forms.CheckboxInput(attrs={
            'class': 'focus:ring-primary-500 h-4 w-4 text-primary-600 border-gray-300 rounded'
        }),
        label='I agree to the terms and conditions'
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Set active service queryset
        self.fields['service'].queryset = Service.active.all().order_by('name')
        
        # Set minimum date to tomorrow
        tomorrow = (timezone.now() + timedelta(days=1)).date()
        self.fields['appointment_date'].widget.attrs['min'] = tomorrow.strftime('%Y-%m-%d')
    
    def clean_first_name(self):
        first_name = self.cleaned_data.get('first_name', '').strip()
        if first_name:
            name_pattern = re.compile(r"^[a-zA-Z\s\-\']+$")
            if not name_pattern.match(first_name):
                raise ValidationError('First name should only contain letters, spaces, hyphens, and apostrophes.')
        return first_name
    
    def clean_last_name(self):
        last_name = self.cleaned_data.get('last_name', '').strip()
        if last_name:
            name_pattern = re.compile(r"^[a-zA-Z\s\-\']+$")
            if not name_pattern.match(last_name):
                raise ValidationError('Last name should only contain letters, spaces, hyphens, and apostrophes.')
        return last_name
    
    def clean_email(self):
        email = self.cleaned_data.get('email', '').strip()
        if email:
            try:
                validate_email(email)
            except ValidationError:
                raise ValidationError('Please enter a valid email address.')
        return email
    
    def clean_contact_number(self):
        contact_number = self.cleaned_data.get('contact_number', '').strip()
        if not contact_number:
            return ''
        
        # Philippine mobile number pattern
        phone_pattern = re.compile(r'^(\+63|0)?9\d{9}$')
        clean_contact = contact_number.replace(' ', '').replace('-', '')
        if not phone_pattern.match(clean_contact):
            raise ValidationError('Please enter a valid Philippine mobile number (e.g., +639123456789).')
        
        return clean_contact
    
    def clean_appointment_date(self):
        appointment_date = self.cleaned_data.get('appointment_date')
        
        if not appointment_date:
            return appointment_date
        
        # Don't allow past dates
        if appointment_date <= timezone.now().date():
            raise ValidationError('Appointment date must be in the future.')
        
        # Don't allow Sundays
        if appointment_date.weekday() == 6:
            raise ValidationError('Appointments are not available on Sundays.')
        
        return appointment_date
    
    def clean(self):
        cleaned_data = super().clean()
        patient_type = cleaned_data.get('patient_type')
        
        # Validate patient data based on type
        if patient_type == 'existing':
            patient_identifier = cleaned_data.get('patient_identifier', '').strip()
            if not patient_identifier:
                raise ValidationError('Please provide your email or phone number to find your record.')
            
            # Try to find the patient
            patient = self._find_existing_patient(patient_identifier)
            if not patient:
                raise ValidationError(f'No patient record found with "{patient_identifier}". Please check your information or register as a new patient.')
            
            cleaned_data['patient'] = patient
        
        elif patient_type == 'new':
            # Validate new patient fields - email is required
            required_fields = ['first_name', 'last_name', 'email']
            for field in required_fields:
                value = cleaned_data.get(field, '').strip() if cleaned_data.get(field) else ''
                if not value:
                    field_label = self.fields[field].label or field.replace('_', ' ').title()
                    raise ValidationError(f'{field_label} is required for new patients.')
            
            # Check if patient already exists
            email = cleaned_data.get('email', '').strip()
            contact_number = cleaned_data.get('contact_number', '').strip()
            
            existing_query = Q()
            if email:
                existing_query |= Q(email__iexact=email, is_active=True)
            if contact_number:
                existing_query |= Q(contact_number=contact_number, is_active=True)
            
            if existing_query:
                existing_patient = Patient.objects.filter(existing_query).first()
                if existing_patient:
                    if existing_patient.email and email and existing_patient.email.lower() == email.lower():
                        raise ValidationError(f'A patient with email "{email}" already exists. Please use "Existing Patient" option.')
                    elif existing_patient.contact_number and contact_number and existing_patient.contact_number == contact_number:
                        raise ValidationError(f'A patient with contact number "{contact_number}" already exists. Please use "Existing Patient" option.')
        
        # Validate appointment availability
        appointment_date = cleaned_data.get('appointment_date')
        period = cleaned_data.get('period')
        
        if appointment_date and period:
            can_book, message = Appointment.can_book_appointment(appointment_date, period)
            if not can_book:
                raise ValidationError(f'Cannot book appointment: {message}')
        
        return cleaned_data
    
    def _find_existing_patient(self, identifier):
        """Find existing patient by email or contact number"""
        query = Q(is_active=True)
        
        if '@' in identifier:
            query &= Q(email__iexact=identifier)
        else:
            clean_identifier = identifier.replace(' ', '').replace('-', '').replace('+', '')
            query &= (
                Q(contact_number=identifier) | 
                Q(contact_number=clean_identifier) |
                (Q(contact_number__endswith=clean_identifier[-10:]) if len(clean_identifier) >= 10 else Q())
            )
        
        return Patient.objects.filter(query).first()
    
    def save(self):
        """Create appointment from form data"""
        cleaned_data = self.cleaned_data
        patient_type = cleaned_data['patient_type']
        
        # Handle patient creation/assignment
        if patient_type == 'new':
            patient = Patient.objects.create(
                first_name=cleaned_data['first_name'].strip(),
                last_name=cleaned_data['last_name'].strip(),
                email=cleaned_data.get('email', '').strip(),
                contact_number=cleaned_data.get('contact_number', '').strip(),
                address=cleaned_data.get('address', '').strip(),
            )
            appointment_patient_type = 'new'
        else:
            patient = cleaned_data['patient']
            appointment_patient_type = 'returning'
        
        # Create appointment
        appointment = Appointment.objects.create(
            patient=patient,
            service=cleaned_data['service'],
            appointment_date=cleaned_data['appointment_date'],
            period=cleaned_data['period'],
            patient_type=appointment_patient_type,
            reason=cleaned_data.get('reason', '').strip(),
            status='pending'
        )
        
        return appointment

class AppointmentNotesForm(forms.ModelForm):
    """Form for editing clinical notes of an appointment"""

    class Meta:
        model = Appointment
        fields = ['symptoms', 'procedures', 'diagnosis']
        widgets = {
            'symptoms': forms.Textarea(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent',
                'rows': 3,
                'placeholder': 'Enter patient symptoms and complaints...'
            }),
            'procedures': forms.Textarea(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent',
                'rows': 3,
                'placeholder': 'Enter procedures performed...'
            }),
            'diagnosis': forms.Textarea(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent',
                'rows': 3,
                'placeholder': 'Enter diagnosis and treatment notes...'
            }),
        }
        labels = {
            'symptoms': 'Symptoms & Complaints',
            'procedures': 'Procedures Performed',
            'diagnosis': 'Diagnosis & Treatment Notes',
        }

class AppointmentNoteFieldForm(forms.Form):
    """Form for editing individual clinical note fields via AJAX"""
    field_name = forms.ChoiceField(choices=[
        ('symptoms', 'Symptoms'),
        ('procedures', 'Procedures'),
        ('diagnosis', 'Diagnosis'),
    ])
    field_value = forms.CharField(widget=forms.Textarea(attrs={
        'rows': 3,
        'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent'
    }), required=False)


# PAYMENT FORMS
class PaymentForm(forms.ModelForm):
    """Enhanced form for creating/editing payments with dynamic service items"""
    
    # Dynamic service items data (will be handled via JavaScript)
    service_items_data = forms.CharField(
        widget=forms.HiddenInput(),
        required=False,
        help_text="JSON data for service items"
    )
    
    # Discount application choice
    DISCOUNT_APPLICATION_CHOICES = [
        ('per_item', 'Apply to Individual Services'),
        ('total', 'Apply to Total Bill'),
    ]
    
    discount_application = forms.ChoiceField(
        choices=DISCOUNT_APPLICATION_CHOICES,
        initial='per_item',
        widget=forms.RadioSelect(attrs={
            'class': 'focus:ring-primary-500 h-4 w-4 text-primary-600 border-gray-300'
        }),
        required=False
    )
    
    # Total discount (when applying to total bill)
    total_discount = forms.ModelChoiceField(
        queryset=Discount.objects.none(),
        required=False,
        empty_label='No discount',
        widget=forms.Select(attrs={
            'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500'
        })
    )
    
    class Meta:
        model = Payment
        fields = ['payment_type', 'installment_months', 'next_due_date', 'notes']
        widgets = {
            # FIX: Add RadioSelect widget for payment_type
            'payment_type': forms.RadioSelect(attrs={
                'class': 'focus:ring-primary-500 h-4 w-4 text-primary-600 border-gray-300'
            }),
            'installment_months': forms.NumberInput(attrs={
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
                'min': 1,
                'max': 24
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
    
    def __init__(self, *args, **kwargs):
        self.appointment = kwargs.pop('appointment', None)
        super().__init__(*args, **kwargs)
        
        # Set default next due date to 30 days from now
        if not self.instance.pk:
            self.fields['next_due_date'].initial = date.today() + timedelta(days=30)
        
        # Set up discount queryset
        self.fields['total_discount'].queryset = Discount.objects.filter(is_active=True).order_by('name')
        
        # FORMAT DISCOUNT LABELS - Add this new code block
        discount_choices = [('', 'No discount')]
        for discount in Discount.objects.filter(is_active=True).order_by('name'):
            if discount.is_percentage:
                label = f"{discount.name} - {discount.amount}% off"
            else:
                # Round the amount to remove decimals
                label = f"{discount.name} - ₱{int(round(discount.amount))} off"
            discount_choices.append((discount.id, label))
        
        self.fields['total_discount'].choices = discount_choices
        # END OF NEW CODE BLOCK
        
        # Initialize service items data with appointment service
        if self.appointment and not self.instance.pk:
            initial_service_data = {
                'service_id': self.appointment.service.id,
                'service_name': self.appointment.service.name,
                'quantity': 1,
                'unit_price': '',
                'discount_id': '',
                'notes': '',
                'min_price': float(self.appointment.service.min_price or 0),
                'max_price': float(self.appointment.service.max_price or 999999),
            }
            self.fields['service_items_data'].initial = json.dumps([initial_service_data])
    
    def clean_service_items_data(self):
        service_items_json = self.cleaned_data.get('service_items_data')
        
        if not service_items_json:
            raise ValidationError('At least one service item is required.')
        
        try:
            service_items = json.loads(service_items_json)
        except (json.JSONDecodeError, TypeError):
            raise ValidationError('Invalid service items data.')
        
        if not service_items or len(service_items) == 0:
            raise ValidationError('At least one service item is required.')
        
        # Validate each service item
        validated_items = []
        for i, item in enumerate(service_items):
            # Validate required fields
            if not item.get('service_id'):
                raise ValidationError(f'Service is required for item {i+1}.')
            
            if not item.get('quantity') or int(item.get('quantity', 0)) <= 0:
                raise ValidationError(f'Valid quantity is required for item {i+1}.')
            
            if not item.get('unit_price'):
                raise ValidationError(f'Unit price is required for item {i+1}.')
            
            # Validate service exists
            try:
                service = Service.objects.get(id=item['service_id'], is_archived=False)
            except Service.DoesNotExist:
                raise ValidationError(f'Invalid service for item {i+1}.')
            
            # Validate unit price
            try:
                unit_price = Decimal(str(item['unit_price']))
            except (ValueError, TypeError):
                raise ValidationError(f'Invalid unit price for item {i+1}.')
            
            # Check price range (unless admin override is requested)
            min_price = getattr(service, 'min_price', None) or 0
            max_price = getattr(service, 'max_price', None) or 999999
            
            if unit_price < min_price or unit_price > max_price:
                # Flag for admin override check
                item['requires_admin_override'] = True
                item['price_violation'] = f'Price ₱{unit_price} is outside allowed range ₱{min_price} - ₱{max_price}'
            
            # Validate discount if specified
            discount = None
            if item.get('discount_id'):
                try:
                    discount = Discount.objects.get(id=item['discount_id'], is_active=True)
                except Discount.DoesNotExist:
                    raise ValidationError(f'Invalid discount for item {i+1}.')
            
            validated_items.append({
                'service': service,
                'quantity': int(item['quantity']),
                'unit_price': unit_price,
                'discount': discount,
                'notes': item.get('notes', ''),
                'requires_admin_override': item.get('requires_admin_override', False),
                'price_violation': item.get('price_violation', ''),
            })
        
        return validated_items
    
    def clean(self):
        cleaned_data = super().clean()
        payment_type = cleaned_data.get('payment_type')
        installment_months = cleaned_data.get('installment_months')
        
        # Validate installment settings
        if payment_type == 'installment':
            if not installment_months or installment_months <= 0:
                raise ValidationError('Please specify the number of installment months.')
            if installment_months > 24:
                raise ValidationError('Maximum installment period is 24 months.')
        
        return cleaned_data


class PaymentItemForm(forms.ModelForm):
    """Form for editing individual payment items (used in detail view)"""
    
    class Meta:
        model = PaymentItem
        fields = ['service', 'quantity', 'unit_price', 'discount', 'notes']
        widgets = {
            'service': forms.Select(attrs={
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
                'onchange': 'updateServicePrice(this)'
            }),
            'quantity': forms.NumberInput(attrs={
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
                'min': 1
            }),
            'unit_price': forms.NumberInput(attrs={
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
                'step': '0.01',
                'min': '0.01'
            }),
            'discount': forms.Select(attrs={
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500'
            }),
            'notes': forms.TextInput(attrs={
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500'
            }),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Filter active services and discounts
        self.fields['service'].queryset = Service.objects.filter(is_archived=False).order_by('name')
        self.fields['discount'].queryset = Discount.objects.filter(is_active=True).order_by('name')
        
        # FORMAT DISCOUNT LABELS - Add this
        discount_choices = [('', 'No discount')]
        for discount in Discount.objects.filter(is_active=True).order_by('name'):
            if discount.is_percentage:
                label = f"{discount.name} - {discount.amount}% off"
            else:
                label = f"{discount.name} - ₱{int(round(discount.amount))} off"
            discount_choices.append((discount.id, label))
        
        self.fields['discount'].choices = discount_choices
    
    def clean_unit_price(self):
        unit_price = self.cleaned_data.get('unit_price')
        service = self.cleaned_data.get('service')
        
        if service and unit_price:
            # Check against service price range if available
            if service.min_price and unit_price < service.min_price:
                raise ValidationError(
                    f'Price cannot be below ₱{service.min_price} for {service.name}'
                )
            
            if service.max_price and unit_price > service.max_price:
                raise ValidationError(
                    f'Price cannot exceed ₱{service.max_price} for {service.name}'
                )
        
        return unit_price


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
        
        # Set default payment date to today
        self.fields['payment_date'].initial = date.today()
        
        if self.payment:
            # Set maximum amount to outstanding balance
            self.fields['amount'].widget.attrs['max'] = str(self.payment.outstanding_balance)
            
            # If payment is already set up for installments, hide installment months
            if self.payment.payment_type == 'installment':
                self.fields['installment_months'].widget = forms.HiddenInput()
    
    def clean_amount(self):
        amount = self.cleaned_data.get('amount')
        
        if self.payment and amount:
            if amount > self.payment.outstanding_balance:
                raise ValidationError(
                    f'Payment amount cannot exceed outstanding balance of ₱{self.payment.outstanding_balance}'
                )
            
            if amount <= 0:
                raise ValidationError('Payment amount must be greater than zero.')
        
        return amount
    
    def clean_payment_date(self):
        payment_date = self.cleaned_data.get('payment_date')
        
        if payment_date and payment_date > date.today():
            raise ValidationError('Payment date cannot be in the future.')
        
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