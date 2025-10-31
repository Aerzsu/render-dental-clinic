# appointments/templatetags/treatment_filters.py
from django import template

register = template.Library()


@register.filter(name='can_edit_treatment')
def can_edit_treatment(treatment_record, user):
    """
    Check if user can edit treatment record
    Usage: {{ appointment.treatment_record|can_edit_treatment:user }}
    Returns: True if user can edit, False otherwise
    """
    if not treatment_record:
        return False
    
    return treatment_record.can_edit(user)


@register.filter(name='can_view_treatment')
def can_view_treatment(treatment_record, user):
    """
    Check if user can view treatment record
    Usage: {{ appointment.treatment_record|can_view_treatment:user }}
    Returns: True if user can view, False otherwise
    """
    if not treatment_record:
        return False
    
    return treatment_record.can_view(user)