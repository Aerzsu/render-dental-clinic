from core.models import SystemSetting


def clinic_settings(request):
    """Make clinic settings available in all templates"""
    return {
        'CLINIC_NAME': SystemSetting.get_setting('clinic_name', 'KingJoy Dental Clinic'),
        'CLINIC_TAGLINE': SystemSetting.get_setting('clinic_tagline', 'Quality Dental Care'),
        'CLINIC_PHONE': SystemSetting.get_setting('clinic_phone', '+63 956 631 6581'),
        'CLINIC_EMAIL': SystemSetting.get_setting('clinic_email', 'papatmyfrend@gmail.com'),
        'CLINIC_ADDRESS': SystemSetting.get_setting('clinic_address', '54 Obanic St.\nQuezon City, Metro Manila'),
        'CLINIC_HOURS': SystemSetting.get_setting('clinic_hours', 'Monday - Saturday: 10:00 AM - 6:00 PM\nSunday: Closed'),
        'AM_PERIOD_DISPLAY': SystemSetting.get_setting('am_period_display', '8:00 AM - 12:00 PM'),
        'PM_PERIOD_DISPLAY': SystemSetting.get_setting('pm_period_display', '1:00 PM - 6:00 PM'),
        'GOOGLE_MAPS_EMBED': SystemSetting.get_setting('google_maps_embed', ''),
    }

def theme_mode(request):
    """Add current theme to template context."""
    return {
        'current_theme': request.session.get('theme', 'light')
    }