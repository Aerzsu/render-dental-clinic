# appointments/utils.py - Timeslot-based appointment system utilities
from datetime import time, timedelta, datetime, date
from django.db import transaction
from django.core.exceptions import ValidationError
from django.utils import timezone


class AppointmentConfig:
    """Helper class for appointment-related configuration"""
   
    @classmethod
    def get_buffer_minutes(cls):
        """Get appointment buffer time in minutes (deprecated for timeslot system)"""
        # No longer needed - timeslots are managed per configuration
        return 0
   
    @classmethod
    def get_minimum_booking_notice(cls):
        """Get minimum booking notice in hours"""
        try:
            from core.models import SystemSetting
            return SystemSetting.get_int_setting('minimum_booking_notice_hours', 24)
        except:
            return 24  # Default fallback


@transaction.atomic
def create_appointment_timeslot(patient, service, appointment_date, start_time, patient_type, reason=''):
    """
    Create appointment with timeslot validation
    
    Args:
        patient: Patient instance
        service: Service instance
        appointment_date: date object
        start_time: time object
        patient_type: str ('new' or 'existing')
        reason: str (optional)
    
    Returns:
        tuple: (appointment, created) where created is boolean
    
    Raises:
        ValidationError: If there are conflicts or validation errors
    """
    from .models import Appointment
    
    # Check timeslot availability
    can_book, message = Appointment.check_timeslot_availability(
        appointment_date, 
        start_time, 
        service.duration_minutes
    )
    
    if not can_book:
        raise ValidationError(message)
    
    # Create appointment
    appointment = Appointment.objects.create(
        patient=patient,
        service=service,
        appointment_date=appointment_date,
        start_time=start_time,
        patient_type=patient_type,
        reason=reason,
        status='pending'
    )
    
    return appointment, True


def get_available_timeslots_for_date(date_obj, service_duration_minutes=30):
    """
    Get available timeslots for a specific date and service duration
    
    Args:
        date_obj: date object
        service_duration_minutes: Duration in minutes (default 30)
    
    Returns:
        list: List of available start times (time objects)
    """
    from .models import TimeSlotConfiguration
    
    # Don't allow Sundays or past dates
    if date_obj.weekday() == 6 or date_obj < timezone.now().date():
        return []
    
    config = TimeSlotConfiguration.get_for_date(date_obj)
    
    if not config:
        return []
    
    return config.get_available_slots(
        service_duration_minutes,
        include_pending=True  # For public booking
    )


def get_timeslot_configuration_for_date(date_obj):
    """
    Get timeslot configuration for a specific date
    
    Args:
        date_obj: date object
    
    Returns:
        dict: Configuration details or None if not configured
    """
    from .models import TimeSlotConfiguration
    
    # Skip Sundays and past dates
    if date_obj.weekday() == 6 or date_obj < timezone.now().date():
        return None
    
    config = TimeSlotConfiguration.get_for_date(date_obj)
    
    if not config:
        return None
    
    return {
        'date': date_obj,
        'start_time': config.start_time,
        'end_time': config.end_time,
        'has_config': True
    }


def get_next_available_dates(days_ahead=30, service_duration_minutes=30):
    """
    Get list of dates with available timeslots in the next N days
    
    Args:
        days_ahead: int (default 30)
        service_duration_minutes: Duration to check for (default 30)
    
    Returns:
        list: List of date objects with available timeslots
    """
    from .models import TimeSlotConfiguration
    
    available_dates = []
    start_date = timezone.now().date() + timedelta(days=1)  # Start from tomorrow
    
    for i in range(days_ahead):
        check_date = start_date + timedelta(days=i)
        
        # Skip Sundays
        if check_date.weekday() == 6:
            continue
        
        config = TimeSlotConfiguration.get_for_date(check_date)
        if config:
            available_slots = config.get_available_slots(
                service_duration_minutes,
                include_pending=True
            )
            if available_slots:
                available_dates.append(check_date)
    
    return available_dates


def validate_appointment_date(appointment_date):
    """
    Validate if an appointment date is acceptable
    
    Args:
        appointment_date: date object
    
    Returns:
        tuple: (is_valid, error_message)
    """
    if not appointment_date:
        return False, "Appointment date is required"
    
    # Check if date is in the past
    if appointment_date <= timezone.now().date():
        return False, "Appointment date cannot be today or in the past"
    
    # Check if it's Sunday
    if appointment_date.weekday() == 6:
        return False, "No appointments available on Sundays"
    
    return True, "Date is valid"


def validate_appointment_time(appointment_date, start_time, duration_minutes):
    """
    Validate if an appointment time is acceptable
    
    Args:
        appointment_date: date object
        start_time: time object
        duration_minutes: int (service duration)
    
    Returns:
        tuple: (is_valid, error_message)
    """
    from .models import TimeSlotConfiguration
    
    if not start_time:
        return False, "Start time is required"
    
    # Check if configuration exists
    config = TimeSlotConfiguration.get_for_date(appointment_date)
    if not config:
        return False, f"No timeslots configured for {appointment_date.strftime('%B %d, %Y')}"
    
    # Check if timeslot is available
    is_available, message = config.is_timeslot_available(
        start_time,
        duration_minutes,
        include_pending=True
    )
    
    return is_available, message


def format_time_range(start_time, end_time):
    """
    Format time range for display
    
    Args:
        start_time: time object
        end_time: time object
    
    Returns:
        str: Formatted time range (e.g., "10:00 AM - 12:00 PM")
    """
    if isinstance(start_time, str):
        start_time = datetime.strptime(start_time, '%H:%M:%S').time()
    if isinstance(end_time, str):
        end_time = datetime.strptime(end_time, '%H:%M:%S').time()
    
    return f"{start_time.strftime('%I:%M %p')} - {end_time.strftime('%I:%M %p')}"


def calculate_end_time(start_time, duration_minutes):
    """
    Calculate end time given start time and duration
    
    Args:
        start_time: time object
        duration_minutes: int
    
    Returns:
        time object
    """
    start_dt = datetime.combine(date.today(), start_time)
    end_dt = start_dt + timedelta(minutes=duration_minutes)
    return end_dt.time()


def generate_timeslot_choices(start_time, end_time, slot_duration=30):
    """
    Generate list of timeslot choices for forms
    
    Args:
        start_time: time object (e.g., 10:00 AM)
        end_time: time object (e.g., 6:00 PM)
        slot_duration: int (minutes, default 30)
    
    Returns:
        list: List of tuples (time_value, time_display)
    """
    choices = []
    current_time = datetime.combine(date.today(), start_time)
    end_datetime = datetime.combine(date.today(), end_time)
    
    while current_time < end_datetime:
        time_value = current_time.time()
        time_display = current_time.strftime('%I:%M %p')
        choices.append((time_value.strftime('%H:%M:%S'), time_display))
        current_time += timedelta(minutes=slot_duration)
    
    return choices


def is_timeslot_available(appointment_date, start_time, duration_minutes, exclude_appointment_id=None):
    """
    Check if a specific timeslot is available
    
    Args:
        appointment_date: date object
        start_time: time object
        duration_minutes: int
        exclude_appointment_id: int (optional, for editing)
    
    Returns:
        tuple: (is_available: bool, message: str)
    """
    from .models import TimeSlotConfiguration
    
    config = TimeSlotConfiguration.get_for_date(appointment_date)
    
    if not config:
        return False, f"No timeslots configured for {appointment_date.strftime('%B %d, %Y')}"
    
    return config.is_timeslot_available(
        start_time,
        duration_minutes,
        exclude_appointment_id=exclude_appointment_id,
        include_pending=True
    )


def get_conflicting_appointments(appointment_date, start_time, duration_minutes, exclude_appointment_id=None):
    """
    Get appointments that conflict with the given timeslot
    
    Args:
        appointment_date: date object
        start_time: time object
        duration_minutes: int
        exclude_appointment_id: int (optional)
    
    Returns:
        QuerySet: Conflicting appointments
    """
    from .models import Appointment
    
    return Appointment.get_conflicting_appointments(
        appointment_date,
        start_time,
        duration_minutes,
        exclude_appointment_id=exclude_appointment_id
    )


def bulk_create_timeslot_configurations(start_date, end_date, start_time, end_time, created_by=None):
    """
    Bulk create timeslot configurations for a date range
    
    Args:
        start_date: date object
        end_date: date object
        start_time: time object
        end_time: time object
        created_by: User instance (optional)
    
    Returns:
        dict: {
            'created_count': int,
            'skipped_count': int,
            'skipped_sundays': int,
            'skipped_existing': int
        }
    """
    from .models import TimeSlotConfiguration
    
    created_count = 0
    skipped_existing = 0
    skipped_sundays = 0
    
    current_date = start_date
    
    with transaction.atomic():
        while current_date <= end_date:
            # Skip Sundays
            if current_date.weekday() == 6:
                skipped_sundays += 1
            # Skip if configuration already exists
            elif TimeSlotConfiguration.objects.filter(date=current_date).exists():
                skipped_existing += 1
            # Create new configuration
            else:
                TimeSlotConfiguration.objects.create(
                    date=current_date,
                    start_time=start_time,
                    end_time=end_time,
                    created_by=created_by
                )
                created_count += 1
            
            current_date += timedelta(days=1)
    
    return {
        'created_count': created_count,
        'skipped_count': skipped_existing + skipped_sundays,
        'skipped_sundays': skipped_sundays,
        'skipped_existing': skipped_existing
    }


def get_appointment_summary_for_date(date_obj):
    """
    Get appointment summary for a specific date
    
    Args:
        date_obj: date object
    
    Returns:
        dict: Summary with counts and lists
    """
    from .models import Appointment, TimeSlotConfiguration
    
    config = TimeSlotConfiguration.get_for_date(date_obj)
    
    if not config:
        return {
            'has_config': False,
            'total_appointments': 0,
            'pending': 0,
            'confirmed': 0,
            'completed': 0
        }
    
    appointments = Appointment.objects.filter(
        appointment_date=date_obj
    ).select_related('patient', 'service', 'assigned_dentist')
    
    return {
        'has_config': True,
        'config': config,
        'total_appointments': appointments.count(),
        'pending': appointments.filter(status='pending').count(),
        'confirmed': appointments.filter(status='confirmed').count(),
        'completed': appointments.filter(status='completed').count(),
        'appointments': appointments.order_by('start_time')
    }