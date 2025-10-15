# appointments/models.py - Complete model with AM/PM slot system
from django.db import models, transaction
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import datetime, date, timedelta, time
from decimal import Decimal


class DailySlots(models.Model):
    """
    Simple daily slot allocation model for AM/PM appointments
    Stores available AM/PM slots for each date (shared pool across all dentists)
    """
    date = models.DateField(unique=True)
    am_slots = models.PositiveIntegerField(default=6, help_text="Available morning slots (AM)")
    pm_slots = models.PositiveIntegerField(default=8, help_text="Available afternoon slots (PM)")
    
    # Optional notes for special days
    notes = models.TextField(blank=True, help_text="Optional notes for this date")
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='created_daily_slots')
    
    class Meta:
        ordering = ['date']
        verbose_name = 'Daily Slot'
        verbose_name_plural = 'Daily Slots'
        indexes = [
            models.Index(fields=['date'], name='daily_slots_date_idx'),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(am_slots__gte=0), 
                name='daily_slots_non_negative_am'
            ),
            models.CheckConstraint(
                check=models.Q(pm_slots__gte=0), 
                name='daily_slots_non_negative_pm'
            ),
        ]
    
    def __str__(self):
        return f"{self.date} - AM: {self.am_slots}, PM: {self.pm_slots}"
    
    @property
    def total_slots(self):
        """Total available slots for the day"""
        return self.am_slots + self.pm_slots
    
    def get_available_am_slots(self, include_pending=True):
        """
        Get available AM slots with context-aware counting
        
        Args:
            include_pending (bool): Whether to count pending appointments as blocking slots
                                  - True for public booking (prevent overbooking)
                                  - False for admin backend (show real availability for decision making)
        """
        if include_pending:
            # For public booking - count pending appointments to prevent overbooking
            blocking_statuses = ['pending', 'confirmed', 'completed']
        else:   
            # For admin backend - only count confirmed/completed appointments
            blocking_statuses = ['confirmed', 'completed']
        
        booked_am = Appointment.objects.filter(
            appointment_date=self.date,
            period='AM',
            status__in=blocking_statuses
        ).count()
        return max(0, self.am_slots - booked_am)
    
    def get_available_pm_slots(self, include_pending=True):
        """
        Get available PM slots with context-aware counting
        
        Args:
            include_pending (bool): Whether to count pending appointments as blocking slots
        """
        if include_pending:
            # For public booking - count pending appointments to prevent overbooking
            blocking_statuses = ['pending', 'confirmed', 'completed']
        else:
            # For admin backend - only count confirmed/completed appointments
            blocking_statuses = ['confirmed', 'completed']
        
        booked_pm = Appointment.objects.filter(
            appointment_date=self.date,
            period='PM',
            status__in=blocking_statuses
        ).count()
        return max(0, self.pm_slots - booked_pm)
    
    def has_available_slots(self, period, include_pending=True):
        """Check if period has available slots"""
        if period == 'AM':
            return self.get_available_am_slots(include_pending=include_pending) > 0
        elif period == 'PM':
            return self.get_available_pm_slots(include_pending=include_pending) > 0
        return False
    
    def get_pending_counts(self):
        """Get separate counts of pending appointments for admin display"""
        pending_am = Appointment.objects.filter(
            appointment_date=self.date,
            period='AM',
            status='pending'
        ).count()
        
        pending_pm = Appointment.objects.filter(
            appointment_date=self.date,
            period='PM',
            status='pending'
        ).count()
        
        return {'am_pending': pending_am, 'pm_pending': pending_pm}
    
    def clean(self):
        # Validate date is not in the past (except for today)
        if self.date and self.date < timezone.now().date():
            raise ValidationError('Cannot create slots for past dates.')
        
        # Don't allow Sunday slots unless explicitly set to 0
        if self.date and self.date.weekday() == 6:  # Sunday
            if self.am_slots > 0 or self.pm_slots > 0:
                raise ValidationError('Sunday slots should be set to 0 (no appointments on Sundays).')
    
    # Keep this method ONLY for explicit admin creation, never call it from API
    @classmethod
    def get_or_create_for_date(cls, date_obj, created_by=None):
        """
        Get existing or create default slots for a date.
        
        WARNING: Only use this in admin views/management commands!
        Do NOT use in public-facing APIs to avoid auto-creation.
        
        Args:
            date_obj: The date to get or create slots for
            created_by: The user creating the slots
            
        Returns:
            Tuple of (daily_slots_instance, was_created)
        """
        try:
            return cls.objects.get(date=date_obj), False
        except cls.DoesNotExist:
            # Validate before creating
            if date_obj.weekday() == 6:  # Sunday
                return None, False
            if date_obj < timezone.now().date():
                return None, False
            
            # Get default values from system settings
            from core.models import SystemSetting
            default_am = SystemSetting.get_int_setting('default_am_slots', 6)
            default_pm = SystemSetting.get_int_setting('default_pm_slots', 8)
            
            # Create with default slots
            daily_slots = cls.objects.create(
                date=date_obj,
                am_slots=default_am,
                pm_slots=default_pm,
                created_by=created_by
            )
            return daily_slots, True
    
    @classmethod
    def get_availability_for_range(cls, start_date, end_date, include_pending=True):
        """
        Get availability data for a date range WITHOUT creating slots.
        
        This is the fixed version that only checks existing slots.
        For dates without slots, returns unavailable (0 slots).
        """
        availability = {}
        
        # Get existing slots
        existing_slots = cls.objects.filter(
            date__gte=start_date,
            date__lte=end_date
        )
        
        slots_dict = {slot.date: slot for slot in existing_slots}
        
        # Check each date in range
        current_date = start_date
        while current_date <= end_date:
            # Skip Sundays and past dates
            if current_date.weekday() != 6 and current_date >= timezone.now().date():
                if current_date in slots_dict:
                    # Slot exists - use actual data
                    slot = slots_dict[current_date]
                    availability[current_date] = {
                        'am_available': slot.get_available_am_slots(include_pending=include_pending),
                        'pm_available': slot.get_available_pm_slots(include_pending=include_pending),
                        'am_total': slot.am_slots,
                        'pm_total': slot.pm_slots
                    }
                    
                    # For admin backend, also include pending counts
                    if not include_pending:
                        pending_counts = slot.get_pending_counts()
                        availability[current_date].update(pending_counts)
                else:
                    # NO SLOT EXISTS - return unavailable (0 slots), don't create
                    availability[current_date] = {
                        'am_available': 0,
                        'pm_available': 0,
                        'am_total': 0,
                        'pm_total': 0
                    }
            
            current_date += timedelta(days=1)
        
        return availability


class Appointment(models.Model):
    """
    AM/PM slot-based appointment model with temporary patient data for pending requests
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
        ('did_not_arrive', 'Did Not Arrive'),
        ('completed', 'Completed'),
    ]
    
    PATIENT_TYPE_CHOICES = [
        ('new', 'New Patient'),
        ('returning', 'Returning Patient'),
    ]
    
    PERIOD_CHOICES = [
        ('AM', 'Morning'),
        ('PM', 'Afternoon'),
    ]
    
    # Define blocking statuses as a class attribute
    BLOCKING_STATUSES = ['pending', 'confirmed', 'completed']
    NON_BLOCKING_STATUSES = ['rejected', 'cancelled', 'did_not_arrive']
    
    # Core appointment data
    patient = models.ForeignKey('patients.Patient', on_delete=models.CASCADE, 
                               related_name='appointments', null=True, blank=True,
                               help_text="Linked patient record (set after approval)")
    service = models.ForeignKey('services.Service', on_delete=models.PROTECT)
    
    # Date and period (AM/PM) system
    appointment_date = models.DateField(help_text="Date of appointment")
    period = models.CharField(max_length=2, choices=PERIOD_CHOICES, help_text="Morning or Afternoon")
    
    # Dentist assignment (set when approved)
    assigned_dentist = models.ForeignKey('users.User', on_delete=models.PROTECT, null=True, blank=True, 
                                       related_name='assigned_appointments', 
                                       help_text="Dentist assigned when appointment is confirmed")
    
    # Status and patient info
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    patient_type = models.CharField(max_length=10, choices=PATIENT_TYPE_CHOICES, default='returning')
    reason = models.TextField(blank=True)
    
    # Temporary patient data for pending appointments
    temp_first_name = models.CharField(max_length=100, blank=True, help_text="Temporary storage for pending requests")
    temp_last_name = models.CharField(max_length=100, blank=True, help_text="Temporary storage for pending requests")
    temp_email = models.EmailField(blank=True, help_text="Temporary storage for pending requests")
    temp_contact_number = models.CharField(max_length=20, blank=True, help_text="Temporary storage for pending requests")
    temp_address = models.TextField(blank=True, help_text="Temporary storage for pending requests")
    
    # Booking and approval tracking
    requested_at = models.DateTimeField(auto_now_add=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    confirmed_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True, 
                                   related_name='confirmed_appointments')
    
    # Clinical Notes
    symptoms = models.TextField(blank=True, help_text="Patient symptoms and complaints")
    procedures = models.TextField(blank=True, help_text="Procedures performed during appointment")
    diagnosis = models.TextField(blank=True, help_text="Diagnosis and treatment notes")

    # Notes
    staff_notes = models.TextField(blank=True)

    # Audit
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-requested_at']
        indexes = [
            models.Index(fields=['status'], name='appt_status_idx'),
            models.Index(fields=['patient'], name='appt_patient_idx'),
            models.Index(fields=['assigned_dentist'], name='appt_assigned_dentist_idx'),
            models.Index(fields=['appointment_date', 'period'], name='appt_date_period_idx'),
            models.Index(fields=['requested_at'], name='appt_requested_idx'),
            models.Index(fields=['temp_email'], name='appt_temp_email_idx'),
            models.Index(fields=['temp_contact_number'], name='appt_temp_contact_idx'),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(period__in=['AM', 'PM']), 
                name='appointment_valid_period'
            ),
        ]
    
    def __str__(self):
        if self.patient:
            return f"{self.patient.full_name} - {self.appointment_date} {self.period}"
        else:
            return f"{self.temp_first_name} {self.temp_last_name} - {self.appointment_date} {self.period} (Pending)"
    
    @property
    def patient_name(self):
        """Get patient name whether from linked patient or temp data"""
        if self.patient:
            return self.patient.full_name
        else:
            return f"{self.temp_first_name} {self.temp_last_name}".strip()
    
    @property
    def patient_email(self):
        """Get patient email whether from linked patient or temp data"""
        if self.patient:
            return self.patient.email
        else:
            return self.temp_email
    
    @property
    def patient_phone(self):
        """Get patient phone whether from linked patient or temp data"""
        if self.patient:
            return self.patient.contact_number
        else:
            return self.temp_contact_number
    
    @property
    def is_past_or_today(self):
        """Check if appointment date is today or in the past (Asia/Manila timezone)"""
        today = timezone.now().date()
        return self.appointment_date <= today
    
    def create_patient_from_temp_data(self):
        """
        Create NEW patient from temp data - NEVER updates existing patients
        For use with NEW patient bookings only
        """
        from patients.models import Patient
        
        # Simple validation - ensure temp data exists
        if not self.temp_first_name or not self.temp_last_name or not self.temp_email:
            raise ValueError("Temporary patient data is required to create new patient")
        
        # Always create a new patient record
        patient = Patient.objects.create(
            first_name=self.temp_first_name,
            last_name=self.temp_last_name,
            email=self.temp_email,
            contact_number=self.temp_contact_number,
            address=self.temp_address,
        )
        
        return patient

    def approve(self, approved_by_user, assigned_dentist=None):
        """
        Approve/Confirm the appointment, create patient record if needed, and assign a dentist
        """
        from django.db import transaction
        
        with transaction.atomic():
            # Only create patient if not already linked (NEW patient bookings)
            # For EXISTING patient bookings (OTP-verified), self.patient is already set
            if not self.patient:
                patient = self.create_patient_from_temp_data()
                # Disable audit log for this patient creation (we'll log the approval instead)
                patient._skip_audit_log = True
                patient.save()
                self.patient = patient
            
            # Update appointment status
            self.status = 'confirmed'
            self.confirmed_at = timezone.now()
            self.confirmed_by = approved_by_user
            
            if assigned_dentist:
                self.assigned_dentist = assigned_dentist
            
            # Disable automatic audit log for this save (manual log will be created in view)
            self._skip_audit_log = True
            self.save()
            
            # Clear temp data after successful approval
            self.clear_temp_data()
    
    def clear_temp_data(self):
        """Clear temporary patient data fields"""
        self.temp_first_name = ''
        self.temp_last_name = ''
        self.temp_email = ''
        self.temp_contact_number = ''
        self.temp_address = ''
        self.save(update_fields=['temp_first_name', 'temp_last_name', 'temp_email', 'temp_contact_number', 'temp_address'])
    
    @property
    def appointment_datetime(self):
        """Returns timezone-aware datetime for appointment"""
        if self.period == 'AM':
            naive_dt = datetime.combine(self.appointment_date, time(8, 0))
        else:
            naive_dt = datetime.combine(self.appointment_date, time(13, 0))
        
        return timezone.make_aware(naive_dt) if timezone.is_naive(naive_dt) else naive_dt
    
    @property
    def is_today(self):
        return self.appointment_date == timezone.now().date()
    
    @property
    def is_upcoming(self):
        return self.appointment_date > timezone.now().date()
    
    @property
    def can_be_cancelled(self):
        """Can be cancelled if at least 24 hours before appointment"""
        if self.status in ['cancelled', 'completed', 'did_not_arrive']:
            return False
        
        return self.appointment_date > timezone.now().date() + timedelta(days=1)
    
    @property
    def blocks_time_slot(self):
        """Whether this appointment blocks its time slot"""
        return self.status in self.BLOCKING_STATUSES
    
    def reject(self):
        """Reject the appointment"""
        self.status = 'rejected'
        self.save()
    
    def cancel(self):
        """Cancel the appointment"""
        self.status = 'cancelled'
        self.save()
    
    def complete(self):
        """Mark appointment as completed"""
        self.status = 'completed'
        self.save()
    
    def clean(self):
        """Model-level validation"""
        # Validate appointment date is not in the past
        if self.appointment_date and self.appointment_date < timezone.now().date():
            raise ValidationError('Appointment date cannot be in the past.')
        
        # Validate no Sundays
        if self.appointment_date and self.appointment_date.weekday() == 6:
            raise ValidationError('No appointments available on Sundays.')
        
        # Validate that either patient is linked OR temp data is provided
        if not self.patient and not (self.temp_first_name and self.temp_last_name and self.temp_email):
            raise ValidationError('Either patient must be linked or temporary patient data must be provided.')
        
        # NEW: Validate date-restricted statuses
        if self.status in ['completed', 'did_not_arrive']:
            if not self.is_past_or_today:
                status_display = dict(self.STATUS_CHOICES).get(self.status, self.status)
                raise ValidationError(
                    f'Cannot mark appointment as "{status_display}" for future dates. '
                    f'The appointment is scheduled for {self.appointment_date.strftime("%B %d, %Y")}.'
                )
    
    @classmethod
    def check_slot_availability(cls, appointment_date, period):
        """Check if slots are available for a specific date and period"""
        daily_slots, _ = DailySlots.get_or_create_for_date(appointment_date)
        
        if not daily_slots:
            return False, "No slots available for this date"
        
        if period == 'AM':
            available = daily_slots.get_available_am_slots()
            total = daily_slots.am_slots
        elif period == 'PM':
            available = daily_slots.get_available_pm_slots()
            total = daily_slots.pm_slots
        else:
            return False, "Invalid period"
        
        if available <= 0:
            return False, f"No {period} slots available ({total} total slots)"
        
        return True, f"{available} {period} slots available"
    
    @classmethod
    def get_conflicting_appointments(cls, appointment_date, period, exclude_appointment_id=None):
        """Get appointments that would conflict with the given date/period"""
        conflicts = cls.objects.filter(
            appointment_date=appointment_date,
            period=period,
            status__in=cls.BLOCKING_STATUSES
        )
        
        if exclude_appointment_id:
            conflicts = conflicts.exclude(id=exclude_appointment_id)
        
        return conflicts
    
    @classmethod
    def can_book_appointment(cls, appointment_date, period, exclude_appointment_id=None, include_pending=True):
        """
        Check if an appointment can be booked with context-aware slot checking
        
        Args:
            include_pending (bool): Whether to count pending appointments as blocking
                                  - True for public booking validation
                                  - False for admin operations
        """
        # Get or create daily slots
        daily_slots, created = DailySlots.get_or_create_for_date(appointment_date)
        
        if not daily_slots:
            return False, "Date not available for booking (Sundays not allowed)"
        
        # Check availability with context-aware counting
        if period == 'AM':
            available_slots = daily_slots.get_available_am_slots(include_pending=include_pending)
            if exclude_appointment_id:
                # Check if the excluded appointment is currently blocking a slot
                existing = cls.objects.filter(
                    id=exclude_appointment_id,
                    appointment_date=appointment_date,
                    period='AM',
                    status__in=(['pending', 'confirmed', 'completed'] if include_pending else ['confirmed', 'completed'])
                ).exists()
                if existing:
                    available_slots += 1
                    
        elif period == 'PM':
            available_slots = daily_slots.get_available_pm_slots(include_pending=include_pending)
            if exclude_appointment_id:
                existing = cls.objects.filter(
                    id=exclude_appointment_id,
                    appointment_date=appointment_date,
                    period='PM',
                    status__in=(['pending', 'confirmed', 'completed'] if include_pending else ['confirmed', 'completed'])
                ).exists()
                if existing:
                    available_slots += 1
        else:
            return False, "Invalid period specified. Use 'AM' or 'PM'"
        
        if available_slots <= 0:
            return False, f"No {period} slots available for {appointment_date}"
        
        return True, f"{available_slots} {period} slots available for {appointment_date}"


class Payment(models.Model):
    """Enhanced Payment model for cash-only dental clinic billing"""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('partially_paid', 'Partially Paid'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]
    
    PAYMENT_TYPE_CHOICES = [
        ('full', 'Full Payment'),
        ('installment', 'Installment'),
    ]
    
    # Core payment data
    patient = models.ForeignKey('patients.Patient', on_delete=models.CASCADE, related_name='payments')
    appointment = models.ForeignKey(Appointment, on_delete=models.CASCADE, related_name='payments')
    
    # Payment details
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0, 
                                     help_text="Total bill amount")
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0,
                                    help_text="Total amount paid so far")
    payment_type = models.CharField(max_length=20, choices=PAYMENT_TYPE_CHOICES, default='full')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    # Installment details
    installment_months = models.PositiveIntegerField(null=True, blank=True, 
                                                   help_text="Number of months for installment")
    monthly_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0,
                                       help_text="Monthly installment amount")
    next_due_date = models.DateField(null=True, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Notes
    notes = models.TextField(blank=True, help_text="Optional notes about payment")
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status'], name='payment_status_idx'),
            models.Index(fields=['patient'], name='payment_patient_idx'),
            models.Index(fields=['next_due_date'], name='payment_due_date_idx'),
            models.Index(fields=['created_at'], name='payment_created_idx'),
        ]
    
    def __str__(self):
        return f"Payment #{self.id} - {self.patient.full_name} - ₱{self.amount_paid}/{self.total_amount}"
    
    @property
    def outstanding_balance(self):
        """Calculate remaining balance"""
        return max(Decimal('0'), self.total_amount - self.amount_paid)
    
    @property
    def payment_progress_percentage(self):
        """Calculate payment progress as percentage"""
        if self.total_amount == 0:
            return 0
        return min(100, (self.amount_paid / self.total_amount) * 100)
    
    @property
    def is_fully_paid(self):
        """Check if payment is fully paid"""
        return self.outstanding_balance == 0
    
    @property
    def is_overdue(self):
        """Check if payment is overdue"""
        if not self.next_due_date:
            return False
        return self.next_due_date < date.today() and not self.is_fully_paid
    
    def calculate_total_from_items(self):
        """Calculate total amount from payment items"""
        total = Decimal('0')
        for item in self.items.all():
            total += item.total
        return total
    
    def update_status(self):
        """Update payment status based on amount paid"""
        if self.amount_paid == 0:
            self.status = 'pending'
        elif self.is_fully_paid:
            self.status = 'completed'
            self.next_due_date = None  # Clear due date when completed
        else:
            self.status = 'partially_paid'
        
        self.save(update_fields=['status', 'next_due_date'])
    
    def setup_installment(self, months):
        """Setup installment payment plan"""
        if months <= 0:
            raise ValidationError("Installment months must be greater than 0")
        
        self.payment_type = 'installment'
        self.installment_months = months
        self.monthly_amount = self.outstanding_balance / months
        
        # Set next due date to next month if not already set
        if not self.next_due_date:
            self.next_due_date = date.today() + timedelta(days=30)
        
        self.save()
    
    def add_payment(self, amount, payment_date=None):
        """Add a payment and update status"""
        if amount <= 0:
            raise ValidationError("Payment amount must be greater than 0")
        
        if amount > self.outstanding_balance:
            raise ValidationError("Payment amount cannot exceed outstanding balance")
        
        with transaction.atomic():
            # Create payment transaction record
            PaymentTransaction.objects.create(
                payment=self,
                amount=amount,
                payment_date=payment_date or date.today(),
                notes=f"Cash payment - P{amount}"
            )
            
            # Update total paid amount
            self.amount_paid += amount
            
            # Update next due date for installments
            if self.payment_type == 'installment' and not self.is_fully_paid:
                if self.next_due_date and self.next_due_date <= date.today():
                    # Move to next month
                    self.next_due_date = self.next_due_date + timedelta(days=30)
            
            self.save()
            self.update_status()
    
    def clean(self):
        # Validate amounts
        if self.amount_paid > self.total_amount:
            raise ValidationError("Amount paid cannot exceed total amount")
        
        # Validate installment settings
        if self.payment_type == 'installment':
            if not self.installment_months or self.installment_months <= 0:
                raise ValidationError("Installment months must be specified for installment payments")


class PaymentItem(models.Model):
    """Enhanced Payment item model with price validation"""
    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name='items')
    service = models.ForeignKey('services.Service', on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2,
                                   help_text="Price per unit (must be within service price range)")
    discount = models.ForeignKey('services.Discount', on_delete=models.SET_NULL, null=True, blank=True)
    notes = models.TextField(blank=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['payment'], name='payment_item_payment_idx'),
            models.Index(fields=['service'], name='payment_item_service_idx'),
        ]
    
    def __str__(self):
        return f"{self.service.name} x{self.quantity} - ₱{self.unit_price}"
    
    @property
    def subtotal(self):
        """Calculate subtotal before discount"""
        return self.unit_price * self.quantity
    
    @property
    def discount_amount(self):
        """Calculate discount amount"""
        if not self.discount:
            return Decimal('0')
        return self.discount.calculate_discount(self.subtotal)
    
    @property
    def total(self):
        """Calculate total after discount"""
        return self.subtotal - self.discount_amount
    
    def clean(self):
        """Validate unit price against service price range"""
        if self.service and hasattr(self.service, 'min_price') and hasattr(self.service, 'max_price'):
            if self.unit_price < self.service.min_price:
                raise ValidationError(
                    f"Price ₱{self.unit_price} is below minimum price ₱{self.service.min_price} for {self.service.name}"
                )
            if self.unit_price > self.service.max_price:
                raise ValidationError(
                    f"Price ₱{self.unit_price} is above maximum price ₱{self.service.max_price} for {self.service.name}"
                )


class PaymentTransaction(models.Model):
    """Track individual payment transactions for audit trail"""
    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name='transactions')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_date = models.DateField()
    payment_datetime = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)
    
    # Receipt tracking
    receipt_number = models.CharField(max_length=50, blank=True, unique=True)
    
    # NEW FIELD - Track who processed this payment
    created_by = models.ForeignKey(
        'users.User', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='processed_payments',
        help_text="Staff member who processed this payment"
    )
    
    class Meta:
        ordering = ['-payment_datetime']
        indexes = [
            models.Index(fields=['payment'], name='payment_transac_payment_idx'),
            models.Index(fields=['payment_date'], name='payment_transac_date_idx'),
            models.Index(fields=['receipt_number'], name='payment_transac_receipt_idx'),
        ]
    
    def __str__(self):
        return f"₱{self.amount} - {self.payment_date} - {self.payment.patient.full_name}"
    
    def save(self, *args, **kwargs):
        if not self.receipt_number:
            # Generate receipt number: RCP-YYYYMMDD-XXXX
            today = date.today()
            date_str = today.strftime('%Y%m%d')
            
            # Get next sequence number for today
            last_receipt = PaymentTransaction.objects.filter(
                receipt_number__startswith=f'RCP-{date_str}-'
            ).order_by('-receipt_number').first()
            
            if last_receipt:
                last_seq = int(last_receipt.receipt_number.split('-')[-1])
                next_seq = last_seq + 1
            else:
                next_seq = 1
            
            self.receipt_number = f'RCP-{date_str}-{next_seq:04d}'
        
        super().save(*args, **kwargs)