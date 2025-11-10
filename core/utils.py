"""
Timezone utility functions for consistent date/time handling across the application.
"""
from django.utils import timezone


def get_manila_now():
    """
    Get current datetime in Manila timezone.
    
    Returns:
        datetime: Current datetime localized to Asia/Manila timezone
    """
    return timezone.localtime(timezone.now())


def get_manila_today():
    """
    Get today's date in Manila timezone.
    
    Returns:
        date: Today's date in Asia/Manila timezone
    """
    return timezone.localtime(timezone.now()).date()


def get_manila_date(dt):
    """
    Convert a datetime to Manila timezone and extract the date.
    
    Args:
        dt (datetime): A timezone-aware or naive datetime
        
    Returns:
        date: The date in Asia/Manila timezone
    """
    if dt is None:
        return None
    
    # Make timezone-aware if naive
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt)
    
    return timezone.localtime(dt).date()


# Usage examples:
# 
# In views:
#   today = get_manila_today()
#   now = get_manila_now()
# 
# In forms:
#   self.fields['date'].initial = get_manila_today()
# 
# In models/comparisons:
#   if payment_date > get_manila_today():
#       raise ValidationError("Date cannot be in the future")