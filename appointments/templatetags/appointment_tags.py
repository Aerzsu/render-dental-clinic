# appointments/templatetags/appointment_tags.py
from django import template
from appointments.models import Appointment

register = template.Library()

@register.simple_tag
def get_pending_appointments_count():
    """
    Get count of pending appointments.
    Safe for use in base templates.
    """
    try:
        count = Appointment.objects.filter(status='pending').count()
        return count
    except Exception:
        return 0