# patients/forms.py
from django import forms
from django.core.exceptions import ValidationError
from datetime import date
import re
from .models import Patient


def clean_name(name, field_name="name"):
    """
    Utility function to clean and validate names.
    
    Args:
        name: The name string to clean
        field_name: Name of the field for error messages
    
    Returns:
        Cleaned name string
        
    Raises:
        ValidationError: If name format is invalid
    """
    if not name:
        raise ValidationError(f'Please enter a {field_name}.')
    
    # Strip whitespace and remove extra spaces
    name = ' '.join(name.split())
    
    # Check length
    if len(name) < 2:
        raise ValidationError(f'{field_name.capitalize()} must be at least 2 characters long.')
    
    if len(name) > 50:
        raise ValidationError(f'{field_name.capitalize()} must not exceed 50 characters.')
    
    # Validate characters - allow letters (including accented), spaces, hyphens, and apostrophes
    # \p{L} would be ideal but not supported in re, so using a comprehensive character class
    pattern = r'^[a-zA-ZÀ-ÿ\s\'\-]+$'
    if not re.match(pattern, name):
        raise ValidationError(
            f'{field_name.capitalize()} can only contain letters, spaces, hyphens, and apostrophes.'
        )
    
    # Additional check: name cannot be only spaces/special characters
    if not any(c.isalpha() for c in name):
        raise ValidationError(f'{field_name.capitalize()} must contain at least one letter.')
    
    return name


def clean_philippine_phone_number(phone, field_name="phone number"):
    """
    Utility function to clean and validate Philippine phone numbers.
    
    Args:
        phone: The phone number string to clean
        field_name: Name of the field for error messages
    
    Returns:
        Cleaned phone number string in +639XXXXXXXXX format or empty string if invalid/empty
        
    Raises:
        ValidationError: If phone number format is invalid
    """
    if not phone:
        return ''
    
    # Strip all whitespace, spaces, and dashes
    phone = phone.strip().replace(' ', '').replace('-', '')
    
    if not phone:
        return ''
    
    # Reject numbers starting with 0 but not 09
    if phone.startswith('0') and not phone.startswith('09'):
        raise ValidationError('Please enter a valid phone number.')
    
    # Convert various formats to international format
    if phone.startswith('09'):
        # 09XXXXXXXXX -> +639XXXXXXXXX
        phone = '+63' + phone[1:]
    elif phone.startswith('639'):
        # 639XXXXXXXXX -> +639XXXXXXXXX
        phone = '+' + phone
    elif phone.startswith('9') and len(phone) == 10:
        # 9XXXXXXXXX -> +639XXXXXXXXX
        phone = '+63' + phone
    
    # Validate final format: must be +639XXXXXXXXX (exactly 13 characters)
    if not phone.startswith('+63') or len(phone) != 13:
        raise ValidationError('Please enter a valid phone number.')
    
    # Ensure all characters after +63 are digits
    if not phone[3:].isdigit():
        raise ValidationError('Please enter a valid phone number.')
    
    # Ensure it starts with 9 after +63
    if not phone.startswith('+639'):
        raise ValidationError('Please enter a valid phone number.')
    
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
    
    def clean_first_name(self):
        """Clean and validate first name"""
        first_name = self.cleaned_data.get('first_name')
        return clean_name(first_name, "first name")
    
    def clean_last_name(self):
        """Clean and validate last name"""
        last_name = self.cleaned_data.get('last_name')
        return clean_name(last_name, "last name")
    
    def clean_contact_number(self):
        """Clean and validate contact number using utility function"""
        contact_number = self.cleaned_data.get('contact_number')
        return clean_philippine_phone_number(contact_number, "phone number")
    
    def clean_date_of_birth(self):
        """Validate date of birth"""
        dob = self.cleaned_data.get('date_of_birth')
        if dob:
            # Check if date is in the future
            if dob > date.today():
                raise ValidationError('Date of birth cannot be in the future.')
            
            # Check if person is 120 years or older
            age = date.today().year - dob.year
            # Adjust if birthday hasn't occurred this year yet
            if (date.today().month, date.today().day) < (dob.month, dob.day):
                age -= 1
            
            if age >= 120:
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
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
            'placeholder': 'Search patients...'
        }),
        label='Search Query'
    )
    
    search_type = forms.ChoiceField(
        choices=SEARCH_TYPE_CHOICES,
        initial='all',
        required=False,
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