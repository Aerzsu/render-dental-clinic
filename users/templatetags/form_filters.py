# users/templatetags/form_filters.py
from django import template

register = template.Library()

@register.filter
def get_field_label(form, field_name):
    """
    Get user-friendly label for a form field
    Used in error messages to show proper field names
    """
    if field_name == '__all__':
        return 'Form'
    
    # Try to get the field label from the form
    if hasattr(form, 'fields') and field_name in form.fields:
        return form.fields[field_name].label or field_name.replace('_', ' ').title()
    
    # Fallback: convert field name to readable format
    return field_name.replace('_', ' ').title()