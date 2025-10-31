from django import forms
from core.models import SystemSetting


class SystemSettingsForm(forms.Form):
    """Single form for all system settings"""
    
    # Clinic Identity
    clinic_name = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={
            'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
            'placeholder': 'KingJoy Dental Clinic'
        }),
        help_text='Displayed in header and throughout the site'
    )
    
    clinic_tagline = forms.CharField(
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
            'placeholder': 'Quality Dental Care'
        }),
        help_text='Short description or slogan'
    )
    
    # Contact Information
    clinic_phone = forms.CharField(
        max_length=50,
        widget=forms.TextInput(attrs={
            'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
            'placeholder': '+63 956 631 6581'
        }),
        help_text='Primary contact number'
    )
    
    clinic_email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
            'placeholder': 'clinic@example.com'
        }),
        help_text='Primary contact email'
    )
    
    clinic_address = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
            'rows': 3,
            'placeholder': '54 Obanic St.\nQuezon City, Metro Manila'
        }),
        help_text='Full address (use Enter for line breaks)'
    )
    
    # Business Hours
    clinic_hours = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
            'rows': 3,
            'placeholder': 'Monday - Saturday: 10:00 AM - 6:00 PM\nSunday: Closed'
        }),
        help_text='Displayed on homepage and footer'
    )
    
    am_period_display = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={
            'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
            'placeholder': '8:00 AM - 12:00 PM'
        }),
        help_text='Time range shown for morning appointments'
    )
    
    pm_period_display = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={
            'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
            'placeholder': '1:00 PM - 6:00 PM'
        }),
        help_text='Time range shown for afternoon appointments'
    )
    
    # Map Integration
    google_maps_embed = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 font-mono text-sm',
            'rows': 4,
            'placeholder': 'https://www.google.com/maps/embed?pb=...'
        }),
    )
    

    # Auto-Approval Settings
    auto_approval_enabled = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={
            'class': 'h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300 rounded'
        }),
        help_text='Automatically approve eligible appointments without manual review'
    )
    
    auto_approve_require_existing = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={
            'class': 'h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300 rounded'
        }),
        help_text='Only auto-approve patients who have completed at least one appointment'
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Load current values from database
        for field_name in self.fields:
            if isinstance(self.fields[field_name], forms.BooleanField):
                current_value = SystemSetting.get_bool_setting(field_name, False)
            else:
                current_value = SystemSetting.get_setting(field_name, '')
            
            if current_value is not None and current_value != '':
                self.fields[field_name].initial = current_value
    
    def save(self, user=None):
        """Save all settings and return changes for audit log"""
        changes = {}
        
        for field_name, value in self.cleaned_data.items():
            # Handle boolean fields
            if isinstance(self.fields[field_name], forms.BooleanField):
                old_value = SystemSetting.get_bool_setting(field_name, False)
                new_value = bool(value)
                
                if old_value != new_value:
                    SystemSetting.set_setting(field_name, 'true' if new_value else 'false')
                    changes[field_name] = {
                        'old': 'Enabled' if old_value else 'Disabled',
                        'new': 'Enabled' if new_value else 'Disabled',
                        'label': self.fields[field_name].label
                    }
            else:
                # Handle text fields
                old_value = SystemSetting.get_setting(field_name, '')
                
                if old_value != value:
                    SystemSetting.set_setting(field_name, value)
                    changes[field_name] = {
                        'old': old_value or '(empty)',
                        'new': value or '(empty)',
                        'label': self.fields[field_name].label
                    }
        
        return changes