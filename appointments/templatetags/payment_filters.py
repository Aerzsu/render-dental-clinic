# appointments/templatetags/payment_filters.py
from django import template
from decimal import Decimal, InvalidOperation

register = template.Library()


@register.filter
def round_amount(value):
    """
    Round a decimal/float value to the nearest whole number.
    Usage: {{ payment.total_amount|round_amount }}
    Returns: Integer (no decimals)
    """
    if value is None:
        return 0
    
    try:
        # Convert to Decimal for precision
        decimal_value = Decimal(str(value))
        # Round to nearest whole number
        rounded = round(decimal_value)
        return int(rounded)
    except (ValueError, TypeError, InvalidOperation):
        return 0


@register.filter
def format_currency(value):
    """Format amount as Philippine Peso currency"""
    try:
        rounded = round(float(value))
        return f"₱{rounded:,}"
    except (ValueError, TypeError):
        return "₱0"


@register.filter
def display_balance(value):
    """Display balance with proper formatting"""
    try:
        rounded = round(float(value))
        if rounded == 0:
            return "₱0 (Paid in Full)"
        return f"₱{rounded:,}"
    except (ValueError, TypeError):
        return "₱0"


@register.filter
def payment_status_display(value):
    """Display user-friendly payment status"""
    status_map = {
        'pending': 'Pending',
        'partially_paid': 'Partially Paid',
        'completed': 'Completed',
        'cancelled': 'Cancelled',
    }
    return status_map.get(value, value.title())