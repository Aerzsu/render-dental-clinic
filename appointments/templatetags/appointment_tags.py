# appointments/templatetags/appointment_tags.py
from django import template
from appointments.models import Appointment

register = template.Library()

@register.simple_tag(takes_context=True)
def get_pending_appointments_count(context):
    """Get count of pending appointments - only for users who can accept them"""
    request = context.get('request')
    if not request or not request.user.is_authenticated:
        return 0
    
    user = request.user
    
    # Only show count to:
    # 1. Superusers
    # 2. Users who are active dentists (can accept appointments)
    if not (user.is_superuser or user.is_active_dentist):
        return 0
    
    return Appointment.objects.filter(status='pending').count()