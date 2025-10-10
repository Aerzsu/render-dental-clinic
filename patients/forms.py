# patients/forms.py
from django import forms
from django.core.exceptions import ValidationError
from datetime import date
from .models import Patient


def clean_philippine_phone_number(phone, field_name="phone number"):
    """
    Utility function to clean and validate Philippine phone numbers.
    
    Args:
        phone: The phone number string to clean
        field_name: Name of the field for error messages
    
    Returns:
        Cleaned phone number string or empty string if invalid/empty
        
    Raises:
        ValidationError: If phone number format is invalid
    """
    if not phone:
        return ''
    
    # Strip whitespace and handle None values
    phone = phone.strip()
    if not phone:
        return ''
        
    # Remove spaces and dashes
    phone = phone.replace(' ', '').replace('-', '')
    
    # Convert local format to international
    if phone.startswith('09'):
        phone = '+63' + phone[1:]
    elif phone.startswith('9') and len(phone) == 10:
        phone = '+63' + phone
    
    # Validate format
    if not phone.startswith('+63') or len(phone) != 13:
        if not (phone.startswith('09') and len(phone) == 11):
            raise ValidationError(f'Please enter a valid Philippine {field_name} (e.g., +639123456789 or 09123456789)')
    
    return phone


class PatientForm(forms.ModelForm):
    """Form for creating and updating patient information"""
    
    class Meta:
        model = Patient
        fields = [
            'first_name', 'last_name', 'email', 'contact_number', 'address',
            'date_of_birth'
        ]
        widgets = {
            'first_name': forms.TextInput(attrs={
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
                'placeholder': 'Enter first name'
            }),
            'last_name': forms.TextInput(attrs={
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
                'placeholder': 'Enter last name'
            }),
            'email': forms.EmailInput(attrs={
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
                'placeholder': 'patient@example.com'
            }),
            'contact_number': forms.TextInput(attrs={
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
                'placeholder': '+639123456789 or 09123456789'
            }),
            'address': forms.Textarea(attrs={
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
                'rows': 3,
                'placeholder': 'Complete address including street, city, and postal code'
            }),
            'date_of_birth': forms.DateInput(attrs={
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
                'type': 'date',
                'max': date.today().strftime('%Y-%m-%d')
            }),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Set required fields
        self.fields['first_name'].required = True
        self.fields['last_name'].required = True
        self.fields['email'].required = True
        
        # Set field labels with required indicators
        self.fields['first_name'].label = 'First Name'
        self.fields['last_name'].label = 'Last Name'
        self.fields['email'].label = 'Email Address'
        self.fields['contact_number'].label = 'Contact Number'
        self.fields['address'].label = 'Address'
        self.fields['date_of_birth'].label = 'Date of Birth'
    
    # REMOVED: clean_email method that checked for uniqueness
    # Email duplicates are now allowed for family members sharing emails
    
    def clean_contact_number(self):
        """Clean and validate contact number using utility function"""
        contact_number = self.cleaned_data.get('contact_number')
        return clean_philippine_phone_number(contact_number, "phone number")
    
    def clean_date_of_birth(self):
        """Validate date of birth"""
        dob = self.cleaned_data.get('date_of_birth')
        if dob:
            if dob > date.today():
                raise ValidationError('Date of birth cannot be in the future.')
            
            # Check if too old (e.g., over 120 years)
            age = date.today().year - dob.year
            if age > 120:
                raise ValidationError('Please enter a valid date of birth.')
        
        return dob

    
    def clean(self):
        """Cross-field validation"""
        cleaned_data = super().clean()
        email = cleaned_data.get('email')
        contact_number = cleaned_data.get('contact_number')
        
        # Ensure at least one contact method is provided
        if not email and not contact_number:
            raise ValidationError('Please provide at least an email address or contact number.')
        
        return cleaned_data


class PatientSearchForm(forms.Form):
    """Form for searching patients"""
    SEARCH_TYPE_CHOICES = [
        ('all', 'All Fields'),
        ('name', 'Name Only'),
        ('email', 'Email Only'),
        ('phone', 'Phone Only'),
    ]
    
    query = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={
            'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
            'placeholder': 'Search patients...'
        }),
        label='Search Query'
    )
    
    search_type = forms.ChoiceField(
        choices=SEARCH_TYPE_CHOICES,
        initial='all',
        widget=forms.Select(attrs={
            'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500'
        }),
        label='Search In'
    )


class FindPatientForm(forms.Form):
    """Form for finding patient by email or phone for appointment booking"""
    
    identifier = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={
            'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
            'placeholder': 'Enter email address or phone number'
        }),
        label='Email or Phone Number',
        help_text='Enter the patient\'s email address or phone number to find their record'
    )
    
    def clean_identifier(self):
        """Clean and validate identifier"""
        identifier = self.cleaned_data.get('identifier')
        if not identifier:
            raise ValidationError('Please enter an email address or phone number.')
        
        # Strip whitespace and handle None values
        identifier = identifier.strip()
        if not identifier:
            raise ValidationError('Please enter an email address or phone number.')
        
        # Basic validation - check if it looks like email or phone
        if '@' in identifier:
            # Looks like email
            try:
                forms.EmailField().clean(identifier)
            except ValidationError:
                raise ValidationError('Please enter a valid email address.')
        else:
            # Assume it's a phone number - use utility function
            try:
                clean_philippine_phone_number(identifier, "phone number")
            except ValidationError:
                raise ValidationError('Please enter a valid phone number or email address.')
        
        return identifier