# appointments/models.py - Timeslot-based appointment system
from django.db import models, transaction
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import datetime, date, timedelta, time
from decimal import Decimal
from django.core.validators import MinValueValidator


class TimeSlotConfiguration(models.Model):
    """
    Daily timeslot configuration model
    Stores the operating hours for each date (e.g., 10:00 AM - 6:00 PM)
    Individual 30-minute slots are calculated dynamically based on appointments
    """
    date = models.DateField(unique=True)
    start_time = models.TimeField(help_text="Start time for appointments (e.g., 10:00 AM)")
    end_time = models.TimeField(help_text="End time for appointments (e.g., 6:00 PM)")
    
    # Optional notes for special days
    notes = models.TextField(blank=True, help_text="Optional notes for this date")
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True, 
                                   related_name='created_timeslot_configs')
    
    class Meta:
        ordering = ['date']
        verbose_name = 'Time Slot Configuration'
        verbose_name_plural = 'Time Slot Configurations'
        indexes = [
            models.Index(fields=['date'], name='timeslot_config_date_idx'),
        ]
    
    def __str__(self):
        return f"{self.date} - {self.start_time.strftime('%I:%M %p')} to {self.end_time.strftime('%I:%M %p')}"
    
    def clean(self):
        """Model-level validation"""
        # Validate date is not in the past (except for today)
        if self.date and self.date < timezone.now().date():
            raise ValidationError('Cannot create timeslot configuration for past dates.')
        
        # Don't allow Sunday slots
        if self.date and self.date.weekday() == 6:  # Sunday
            raise ValidationError('No appointments available on Sundays.')
        
        # Validate start_time is before end_time
        if self.start_time and self.end_time and self.start_time >= self.end_time:
            raise ValidationError('Start time must be before end time.')
        
        # Validate minimum duration (at least 30 minutes)
        if self.start_time and self.end_time:
            start_dt = datetime.combine(date.today(), self.start_time)
            end_dt = datetime.combine(date.today(), self.end_time)
            duration_minutes = (end_dt - start_dt).total_seconds() / 60
            
            if duration_minutes < 30:
                raise ValidationError('Time slot configuration must span at least 30 minutes.')
    
    def get_all_timeslots(self):
        """
        Generate all possible 30-minute timeslots for this configuration
        Returns list of (start_time, end_time) tuples
        """
        slots = []
        current_time = datetime.combine(date.today(), self.start_time)
        end_datetime = datetime.combine(date.today(), self.end_time)
        
        while current_time < end_datetime:
            slot_start = current_time.time()
            slot_end = (current_time + timedelta(minutes=30)).time()
            
            # Only include slot if it ends at or before end_time
            if slot_end <= self.end_time:
                slots.append((slot_start, slot_end))
            
            current_time += timedelta(minutes=30)
        
        return slots
    
    def get_available_slots(self, service_duration_minutes, include_pending=True):
        """
        Get available starting timeslots for a service with given duration
        
        Args:
            service_duration_minutes: Duration of the service in minutes
            include_pending: Whether to count pending appointments as blocking slots
                           - True for public booking (prevent overbooking)
                           - False for admin backend (show real availability)
        
        Returns:
            List of available start times that can accommodate the service duration
        """
        if service_duration_minutes % 30 != 0:
            raise ValueError("Service duration must be a multiple of 30 minutes")
        
        slots_needed = service_duration_minutes // 30
        all_slots = self.get_all_timeslots()
        available_starts = []
        
        # Determine which statuses block slots
        if include_pending:
            blocking_statuses = Appointment.BLOCKING_STATUSES
        else:
            blocking_statuses = ['confirmed', 'completed']
        
        # Get all appointments for this date with blocking statuses
        appointments = Appointment.objects.filter(
            appointment_date=self.date,
            status__in=blocking_statuses
        ).select_related('service')
        
        # Build set of occupied slot indices
        occupied_slots = set()
        for appointment in appointments:
            appt_start_time = appointment.start_time
            appt_duration = appointment.service.duration_minutes
            appt_slots_needed = appt_duration // 30
            
            # Find which slots this appointment occupies
            for i, (slot_start, slot_end) in enumerate(all_slots):
                if slot_start >= appt_start_time:
                    appt_start_dt = datetime.combine(date.today(), appt_start_time)
                    slot_start_dt = datetime.combine(date.today(), slot_start)
                    
                    # Check if this slot falls within appointment duration
                    if slot_start_dt < appt_start_dt + timedelta(minutes=appt_duration):
                        occupied_slots.add(i)
        
        # Check each possible starting slot
        for i in range(len(all_slots) - slots_needed + 1):
            # Check if all needed consecutive slots are available
            slots_available = all(
                j not in occupied_slots 
                for j in range(i, i + slots_needed)
            )
            
            if slots_available:
                # Verify the slot end time doesn't exceed end_time
                slot_start_time = all_slots[i][0]
                slot_start_dt = datetime.combine(date.today(), slot_start_time)
                slot_end_dt = slot_start_dt + timedelta(minutes=service_duration_minutes)
                
                if slot_end_dt.time() <= self.end_time:
                    available_starts.append(slot_start_time)
        
        return available_starts
    
    def is_timeslot_available(self, start_time, duration_minutes, exclude_appointment_id=None, include_pending=True):
        """
        Check if a specific timeslot is available for booking
        
        Args:
            start_time: Starting time for the appointment
            duration_minutes: Duration of the service in minutes
            exclude_appointment_id: Appointment ID to exclude (for editing)
            include_pending: Whether to count pending appointments as blocking
        
        Returns:
            Tuple of (is_available: bool, message: str)
        """
        # Validate start_time is within configured range
        if start_time < self.start_time or start_time >= self.end_time:
            return False, f"Start time must be between {self.start_time.strftime('%I:%M %p')} and {self.end_time.strftime('%I:%M %p')}"
        
        # Calculate end time
        start_dt = datetime.combine(date.today(), start_time)
        end_dt = start_dt + timedelta(minutes=duration_minutes)
        end_time = end_dt.time()
        
        # Validate end_time doesn't exceed configured end_time
        if end_time > self.end_time:
            hours_needed = duration_minutes / 60
            return False, f"This service requires {hours_needed} hour{'s' if hours_needed != 1 else ''}, but extends beyond closing time. Please select an earlier time slot."
        
        # Check for conflicting appointments
        blocking_statuses = Appointment.BLOCKING_STATUSES if include_pending else ['confirmed', 'completed']
        
        conflicting_appointments = Appointment.objects.filter(
            appointment_date=self.date,
            status__in=blocking_statuses
        ).select_related('service')
        
        if exclude_appointment_id:
            conflicting_appointments = conflicting_appointments.exclude(id=exclude_appointment_id)
        
        for appointment in conflicting_appointments:
            appt_start = datetime.combine(date.today(), appointment.start_time)
            appt_end = appt_start + timedelta(minutes=appointment.service.duration_minutes)
            
            # Check for overlap
            if not (end_dt <= appt_start or start_dt >= appt_end):
                return False, f"This timeslot conflicts with an existing appointment at {appointment.start_time.strftime('%I:%M %p')}"
        
        return True, "Timeslot is available"
    
    def get_pending_count(self):
        """Get count of pending appointments for this date"""
        return Appointment.objects.filter(
            appointment_date=self.date,
            status='pending'
        ).count()
    
    @classmethod
    def get_for_date(cls, date_obj):
        """
        Get timeslot configuration for a specific date
        Returns None if not configured
        """
        try:
            return cls.objects.get(date=date_obj)
        except cls.DoesNotExist:
            return None
    
    @classmethod
    def get_availability_for_range(cls, start_date, end_date, service_duration_minutes=30, include_pending=True):
        """
        Get availability data for a date range
        
        Args:
            start_date: Start date of range
            end_date: End date of range
            service_duration_minutes: Duration to check availability for (default 30)
            include_pending: Whether to count pending appointments
        
        Returns:
            Dictionary with date as key and availability data as value
        """
        availability = {}
        
        # Get existing configurations
        configs = cls.objects.filter(
            date__gte=start_date,
            date__lte=end_date
        )
        
        configs_dict = {config.date: config for config in configs}
        
        # Check each date in range
        current_date = start_date
        while current_date <= end_date:
            # Skip Sundays and past dates
            if current_date.weekday() != 6 and current_date >= timezone.now().date():
                if current_date in configs_dict:
                    config = configs_dict[current_date]
                    available_slots = config.get_available_slots(service_duration_minutes, include_pending)
                    
                    availability[current_date] = {
                        'has_config': True,
                        'start_time': config.start_time.strftime('%I:%M %p'),
                        'end_time': config.end_time.strftime('%I:%M %p'),
                        'available_slots': [t.strftime('%I:%M %p') for t in available_slots],
                        'total_slots': len(config.get_all_timeslots()),
                        'available_count': len(available_slots)
                    }
                    
                    # For admin backend, include pending count
                    if not include_pending:
                        availability[current_date]['pending_count'] = config.get_pending_count()
                else:
                    # No configuration exists
                    availability[current_date] = {
                        'has_config': False,
                        'available_count': 0,
                        'available_slots': []
                    }
            
            current_date += timedelta(days=1)
        
        return availability


class Appointment(models.Model):
    """
    Timeslot-based appointment model
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
        ('existing', 'Existing Patient'),
    ]
    
    # Define blocking statuses as a class attribute
    BLOCKING_STATUSES = ['pending', 'confirmed', 'completed']
    NON_BLOCKING_STATUSES = ['rejected', 'cancelled', 'did_not_arrive']
    
    # Core appointment data
    patient = models.ForeignKey('patients.Patient', on_delete=models.CASCADE, 
                               related_name='appointments', null=True, blank=True,
                               help_text="Linked patient record (set after approval)")
    service = models.ForeignKey('services.Service', on_delete=models.PROTECT)
    
    # Date and time
    appointment_date = models.DateField(help_text="Date of appointment")
    start_time = models.TimeField(help_text="Start time of appointment (e.g., 10:00 AM)")
    
    # Dentist assignment (set when approved)
    assigned_dentist = models.ForeignKey('users.User', on_delete=models.PROTECT, null=True, blank=True, 
                                       related_name='assigned_appointments', 
                                       help_text="Dentist assigned when appointment is confirmed")
    
    # Status and patient info
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    patient_type = models.CharField(max_length=10, choices=PATIENT_TYPE_CHOICES, default='existing')
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
    
    # Clinical Notes (REMOVE THESE, USE CLINICAL_NOTES FIELD IN TREATMENTRECORD MODEL INSTEAD)
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
            models.Index(fields=['appointment_date', 'start_time'], name='appt_date_time_idx'),
            models.Index(fields=['requested_at'], name='appt_requested_idx'),
            models.Index(fields=['temp_email'], name='appt_temp_email_idx'),
            models.Index(fields=['temp_contact_number'], name='appt_temp_contact_idx'),
        ]
    
    def __str__(self):
        end_time = self.get_end_time()
        if self.patient:
            return f"{self.patient.full_name} - {self.appointment_date} {self.start_time.strftime('%I:%M %p')}-{end_time.strftime('%I:%M %p')}"
        else:
            return f"{self.temp_first_name} {self.temp_last_name} - {self.appointment_date} {self.start_time.strftime('%I:%M %p')}-{end_time.strftime('%I:%M %p')} (Pending)"
    
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
    
    def get_end_time(self):
        """Calculate and return the end time based on service duration"""
        start_dt = datetime.combine(date.today(), self.start_time)
        end_dt = start_dt + timedelta(minutes=self.service.duration_minutes)
        return end_dt.time()
    
    @property
    def end_time(self):
        """Property alias for get_end_time()"""
        return self.get_end_time()
    
    @property
    def time_display(self):
        """Display time in readable format (e.g., '10:00 AM - 12:00 PM')"""
        end_time = self.get_end_time()
        return f"{self.start_time.strftime('%I:%M %p')} - {end_time.strftime('%I:%M %p')}"
    
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
            if not self.patient:
                patient = self.create_patient_from_temp_data()
                # Disable audit log for this patient creation
                patient._skip_audit_log = True
                patient.save()
                self.patient = patient
            
            # Update appointment status
            self.status = 'confirmed'
            self.confirmed_at = timezone.now()
            self.confirmed_by = approved_by_user
            
            if assigned_dentist:
                self.assigned_dentist = assigned_dentist
            
            # Disable automatic audit log for this save
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
        naive_dt = datetime.combine(self.appointment_date, self.start_time)
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
        
        # Validate date-restricted statuses
        if self.status in ['completed', 'did_not_arrive']:
            if not self.is_past_or_today:
                status_display = dict(self.STATUS_CHOICES).get(self.status, self.status)
                raise ValidationError(
                    f'Cannot mark appointment as "{status_display}" for future dates. '
                    f'The appointment is scheduled for {self.appointment_date.strftime("%B %d, %Y")}.'
                )
        
        # Validate timeslot availability (only for new appointments or when changing date/time)
        if self.appointment_date and self.start_time and self.service_id:
            config = TimeSlotConfiguration.get_for_date(self.appointment_date)
            
            if not config:
                raise ValidationError(f'No timeslot configuration exists for {self.appointment_date}. Please create timeslots first.')
            
            # For new appointments or when date/time changes, check availability
            if not self.pk or self.has_changed('appointment_date', 'start_time'):
                is_available, message = config.is_timeslot_available(
                    self.start_time,
                    self.service.duration_minutes,
                    exclude_appointment_id=self.pk,
                    include_pending=True
                )
                
                if not is_available:
                    raise ValidationError(message)
    
    def has_changed(self, *fields):
        """Check if specified fields have changed since last save"""
        if not self.pk:
            return True
        
        old_instance = Appointment.objects.get(pk=self.pk)
        for field in fields:
            if getattr(self, field) != getattr(old_instance, field):
                return True
        return False
    
    @classmethod
    def check_timeslot_availability(cls, appointment_date, start_time, duration_minutes, exclude_appointment_id=None):
        """
        Check if a timeslot is available for booking
        
        Returns:
            Tuple of (is_available: bool, message: str)
        """
        config = TimeSlotConfiguration.get_for_date(appointment_date)
        
        if not config:
            return False, f"No timeslots configured for {appointment_date.strftime('%B %d, %Y')}"
        
        return config.is_timeslot_available(
            start_time,
            duration_minutes,
            exclude_appointment_id=exclude_appointment_id,
            include_pending=True  # For public booking
        )
    
    @classmethod
    def get_conflicting_appointments(cls, appointment_date, start_time, duration_minutes, exclude_appointment_id=None):
        """Get appointments that would conflict with the given date/time/duration"""
        start_dt = datetime.combine(date.today(), start_time)
        end_dt = start_dt + timedelta(minutes=duration_minutes)
        
        conflicts = cls.objects.filter(
            appointment_date=appointment_date,
            status__in=cls.BLOCKING_STATUSES
        ).select_related('service')
        
        if exclude_appointment_id:
            conflicts = conflicts.exclude(id=exclude_appointment_id)
        
        # Filter for time overlaps
        conflicting = []
        for appointment in conflicts:
            appt_start = datetime.combine(date.today(), appointment.start_time)
            appt_end = appt_start + timedelta(minutes=appointment.service.duration_minutes)
            
            # Check for overlap
            if not (end_dt <= appt_start or start_dt >= appt_end):
                conflicting.append(appointment)
        
        return conflicting


# Payment models remain unchanged
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
            self.next_due_date = None
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
            PaymentTransaction.objects.create(
                payment=self,
                amount=amount,
                payment_date=payment_date or date.today(),
                notes=f"Cash payment - P{amount}"
            )
            
            self.amount_paid += amount
            
            if self.payment_type == 'installment' and not self.is_fully_paid:
                if self.next_due_date and self.next_due_date <= date.today():
                    self.next_due_date = self.next_due_date + timedelta(days=30)
            
            self.save()
            self.update_status()
    
    def clean(self):
        if self.amount_paid > self.total_amount:
            raise ValidationError("Amount paid cannot exceed total amount")
        
        if self.payment_type == 'installment':
            if not self.installment_months or self.installment_months <= 0:
                raise ValidationError("Installment months must be specified for installment payments")


class PaymentItem(models.Model):
    """Payment item model for dental services"""
    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name='items')
    service = models.ForeignKey('services.Service', on_delete=models.PROTECT)
    price = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        help_text="Service base fee (must be within service price range)"
    )
    discount = models.ForeignKey('services.Discount', on_delete=models.SET_NULL, null=True, blank=True)
    notes = models.TextField(blank=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['payment'], name='payment_item_payment_idx'),
            models.Index(fields=['service'], name='payment_item_service_idx'),
        ]
    
    def __str__(self):
        return f"{self.service.name} - ₱{self.price}"
    
    @property
    def products_total(self):
        """Calculate total cost of all products used for this service"""
        return sum(item.subtotal for item in self.products.all())
    
    @property
    def subtotal(self):
        """Service base price + products (before discount)"""
        return self.price + self.products_total
    
    @property
    def discount_amount(self):
        """Calculate discount amount - ONLY applies to service base price"""
        if not self.discount:
            return Decimal('0')
        
        # Discount only applies to service base price, NOT products
        discount_on_service = self.discount.calculate_discount(self.price)
        return discount_on_service
    
    @property
    def total(self):
        """Calculate total after discount (service with discount + products without discount)"""
        service_after_discount = self.price - self.discount_amount
        return service_after_discount + self.products_total
    
    def clean(self):
        """Validate price against service price range"""
        if self.service and hasattr(self.service, 'min_price') and hasattr(self.service, 'max_price'):
            if self.service.min_price and self.price < self.service.min_price:
                raise ValidationError(
                    f"Price ₱{self.price} is below minimum price ₱{self.service.min_price} for {self.service.name}"
                )
            if self.service.max_price and self.price > self.service.max_price:
                raise ValidationError(
                    f"Price ₱{self.price} is above maximum price ₱{self.service.max_price} for {self.service.name}"
                )

class PaymentItemProduct(models.Model):
    """
    Junction table tracking products used for each payment service item
    Provides transparency on why service prices differ
    """
    payment_item = models.ForeignKey(
        PaymentItem,
        on_delete=models.CASCADE,
        related_name='products'
    )
    product = models.ForeignKey(
        'services.Product',
        on_delete=models.PROTECT,
        help_text="Product/supply used"
    )
    quantity = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
        help_text="Quantity used"
    )
    unit_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Price per unit at time of use (snapshot for historical accuracy)"
    )
    notes = models.CharField(
        max_length=200,
        blank=True,
        help_text="Optional notes (e.g., 'Extra anesthesia - patient anxiety')"
    )
    
    # Audit
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['product__name']
        indexes = [
            models.Index(fields=['payment_item'], name='pmt_item_prod_pmt_idx'),
            models.Index(fields=['product'], name='pmt_item_prod_prod_idx'),
        ]
    
    def __str__(self):
        return f"{self.product.name} x{self.quantity} @ ₱{self.unit_price}"
    
    @property
    def subtotal(self):
        """Calculate subtotal for this product line (quantity × unit_price)"""
        return self.quantity * self.unit_price
    
    @property
    def subtotal_display(self):
        """Display subtotal in user-friendly format"""
        return f"₱{self.subtotal:,.2f}"
    
    def clean(self):
        """Model-level validation"""
        if self.quantity < 1:
            raise ValidationError('Quantity must be at least 1.')
        
        if self.unit_price and self.unit_price < Decimal('0.01'):
            raise ValidationError('Unit price must be at least ₱0.01.')

class PaymentTransaction(models.Model):
    """Track individual payment transactions for audit trail"""
    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name='transactions')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_date = models.DateField()
    payment_datetime = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)
    
    # Receipt tracking
    receipt_number = models.CharField(max_length=50, blank=True, unique=True)
    
    # Track who processed this payment
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
            today = date.today()
            date_str = today.strftime('%Y%m%d')
            
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

class TreatmentRecord(models.Model):
    """
    Draft treatment documentation created during/after appointment
    Captures what was actually performed to pre-populate payment creation
    Only editable by assigned dentist
    """
    appointment = models.OneToOneField(
        Appointment,
        on_delete=models.CASCADE,
        related_name='treatment_record',
        help_text="Related appointment"
    )
    
    # Services actually performed (can differ from booked service)
    services_performed = models.ManyToManyField(
        'services.Service',
        through='TreatmentRecordService',
        related_name='treatment_records',
        help_text="Services actually performed during appointment"
    )
    
    # Clinical documentation
    clinical_notes = models.TextField(
        blank=True,
        help_text="Clinical observations, diagnosis, procedures performed"
    )
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        'users.User',
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_treatment_records'
    )
    last_modified_by = models.ForeignKey(
        'users.User',
        on_delete=models.SET_NULL,
        null=True,
        related_name='modified_treatment_records'
    )
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['appointment'], name='treatment_rec_appt_idx'),
        ]
    
    def __str__(self):
        return f"Treatment Record - {self.appointment.patient_name} - {self.appointment.appointment_date}"
    
    def can_edit(self, user):
        """Check if user can edit this treatment record"""
        # Only assigned dentist or admin can edit
        if user.is_superuser:
            return True
        return self.appointment.assigned_dentist == user
    
    def get_services_with_products(self):
        """Get all services with their products for easy iteration"""
        services_data = []
        for service_record in self.service_records.all().prefetch_related('products__product'):
            services_data.append({
                'service': service_record.service,
                'notes': service_record.notes,
                'products': service_record.products.all()
            })
        return services_data


class TreatmentRecordService(models.Model):
    """
    Junction table for services performed in treatment record
    Allows notes per service
    """
    treatment_record = models.ForeignKey(
        TreatmentRecord,
        on_delete=models.CASCADE,
        related_name='service_records'
    )
    service = models.ForeignKey(
        'services.Service',
        on_delete=models.PROTECT
    )
    notes = models.TextField(
        blank=True,
        help_text="Notes specific to this service"
    )
    order = models.PositiveIntegerField(
        default=0,
        help_text="Display order"
    )
    
    class Meta:
        ordering = ['order', 'id']
        unique_together = ['treatment_record', 'service']
    
    def __str__(self):
        return f"{self.service.name} - {self.treatment_record.appointment.patient_name}"


class TreatmentRecordProduct(models.Model):
    """
    Products/supplies used for each service in treatment record
    """
    treatment_service = models.ForeignKey(
        TreatmentRecordService,
        on_delete=models.CASCADE,
        related_name='products'
    )
    product = models.ForeignKey(
        'services.Product',
        on_delete=models.PROTECT
    )
    quantity = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1)]
    )
    notes = models.CharField(
        max_length=200,
        blank=True,
        help_text="Notes about product usage"
    )
    
    class Meta:
        ordering = ['product__name']
    
    def __str__(self):
        return f"{self.product.name} x{self.quantity}"


class TreatmentRecordAuditLog(models.Model):
    """
    Audit trail for treatment record changes
    """
    treatment_record = models.ForeignKey(
        TreatmentRecord,
        on_delete=models.CASCADE,
        related_name='audit_logs'
    )
    modified_by = models.ForeignKey(
        'users.User',
        on_delete=models.SET_NULL,
        null=True
    )
    modified_at = models.DateTimeField(auto_now_add=True)
    changes = models.JSONField(
        help_text="JSON object describing what changed"
    )
    action = models.CharField(
        max_length=50,
        choices=[
            ('created', 'Created'),
            ('updated', 'Updated'),
            ('deleted', 'Deleted'),
        ]
    )
    
    class Meta:
        ordering = ['-modified_at']
        indexes = [
            models.Index(fields=['treatment_record'], name='treat_audit_rec_idx'),
        ]
    
    def __str__(self):
        return f"{self.action.title()} by {self.modified_by} at {self.modified_at}"