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
    """
    Format value as currency with peso sign and no decimals.
    Usage: {{ payment.total_amount|format_currency }}
    Returns: "₱1,234" format
    """
    rounded = round_amount(value)
    return f"₱{rounded:,}"


@register.filter
def display_balance(value):
    """
    Display 'None' if balance is zero, otherwise format as currency.
    Usage: {{ payment.outstanding_balance|display_balance }}
    Returns: "None" if 0, otherwise "₱1,234"
    """
    rounded = round_amount(value)
    if rounded == 0:
        return "None"
    return f"₱{rounded:,}"


@register.filter
def payment_status_display(value):
    """
    Custom display for payment status - show 'Fully Paid' for completed.
    Usage: {{ payment.status|payment_status_display }}
    Returns: User-friendly status text
    """
    status_map = {
        'pending': 'Pending',
        'partially_paid': 'Partially Paid',
        'completed': 'Fully Paid',
        'cancelled': 'Cancelled',  # Keep for backward compatibility
    }
    return status_map.get(value, value.replace('_', ' ').title())