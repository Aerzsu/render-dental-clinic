# users/forms.py
from django import forms
from django.contrib.auth.forms import AuthenticationForm
from .models import User, Role

class CustomLoginForm(AuthenticationForm):
    """Custom login form with styled inputs"""
    username = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'mt-1 block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm placeholder-gray-400 focus:outline-none focus:ring-primary-500 focus:border-primary-500',
            'placeholder': 'Username'
        })
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'mt-1 block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm placeholder-gray-400 focus:outline-none focus:ring-primary-500 focus:border-primary-500',
            'placeholder': 'Password'
        })
    )

class UserForm(forms.ModelForm):
    """Form for creating and updating users"""
    password1 = forms.CharField(
        label='Password',
        widget=forms.PasswordInput(attrs={
            'class': 'mt-1 block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-primary-500 focus:border-primary-500'
        }),
        required=False,
        help_text="Leave blank to keep current password (for updates)"
    )
    password2 = forms.CharField(
        label='Confirm Password',
        widget=forms.PasswordInput(attrs={
            'class': 'mt-1 block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-primary-500 focus:border-primary-500'
        }),
        required=False
    )
    
    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email', 'phone', 'role', 'is_active_dentist', 'is_active']
        widgets = {
            'username': forms.TextInput(attrs={
                'class': 'mt-1 block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-primary-500 focus:border-primary-500'
            }),
            'first_name': forms.TextInput(attrs={
                'class': 'mt-1 block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-primary-500 focus:border-primary-500'
            }),
            'last_name': forms.TextInput(attrs={
                'class': 'mt-1 block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-primary-500 focus:border-primary-500'
            }),
            'email': forms.EmailInput(attrs={
                'class': 'mt-1 block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-primary-500 focus:border-primary-500'
            }),
            'phone': forms.TextInput(attrs={
                'class': 'mt-1 block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-primary-500 focus:border-primary-500',
                'placeholder': '+63 XXX XXX XXXX'
            }),
            'role': forms.Select(attrs={
                'class': 'mt-1 block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-primary-500 focus:border-primary-500'
            }),
            'is_active_dentist': forms.CheckboxInput(attrs={
                'class': 'rounded border-gray-300 text-primary-600 shadow-sm focus:border-primary-500 focus:ring-primary-500'
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'rounded border-gray-300 text-primary-600 shadow-sm focus:border-primary-500 focus:ring-primary-500'
            }),
        }
        labels = {
            'is_active_dentist': 'Allow to accept appointment requests',
            'is_active': 'Account is active',
        }
    
    def __init__(self, *args, **kwargs):
        self.is_update = kwargs.pop('is_update', False)
        self.request_user = kwargs.pop('request_user', None)
        super().__init__(*args, **kwargs)
        
        # Make password required for new users
        if not self.is_update:
            self.fields['password1'].required = True
            self.fields['password2'].required = True
            self.fields['password1'].help_text = "Password must be at least 8 characters long."
        
        # Filter out archived roles from the dropdown
        self.fields['role'].queryset = Role.objects.filter(is_archived=False).order_by('display_name')
        
        # Remove the empty option for new users
        if not self.is_update and not self.instance.pk:
            self.fields['role'].empty_label = None
            try:
                dentist_role = Role.objects.get(name='_dentist', is_archived=False)
                self.fields['role'].initial = dentist_role.pk
            except Role.DoesNotExist:
                pass
        
        # Only protect against removing the last admin
        if (self.is_update and self.instance and self.request_user and 
            self.instance == self.request_user and 
            self.request_user.role and self.request_user.role.name == '_admin'):
            
            admin_count = User.objects.filter(
                role__name='_admin',
                is_active=True
            ).exclude(pk=self.instance.pk).count()
            
            if admin_count == 0:
                self.fields['role'].disabled = True
                self.fields['is_active'].disabled = True
        
    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get('password1')
        password2 = cleaned_data.get('password2')
        
        # Password validation for new users or when password is being changed
        if password1 or password2:
            if password1 != password2:
                raise forms.ValidationError("Passwords don't match.")
            if len(password1) < 8:
                raise forms.ValidationError("Password must be at least 8 characters long.")
        
        return cleaned_data
    
    def save(self, commit=True):
        user = super().save(commit=False)
        password = self.cleaned_data.get('password1')
        
        if password:
            user.set_password(password)
        
        if commit:
            user.save()
        return user

class RoleForm(forms.ModelForm):
    """Form for creating and updating roles"""
    
    class Meta:
        model = Role
        fields = ['name', 'display_name', 'description']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'mt-1 block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-primary-500 focus:border-primary-500',
                'placeholder': 'e.g., custom_role'
            }),
            'display_name': forms.TextInput(attrs={
                'class': 'mt-1 block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-primary-500 focus:border-primary-500',
                'placeholder': 'e.g., Custom Role'
            }),
            'description': forms.Textarea(attrs={
                'class': 'mt-1 block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-primary-500 focus:border-primary-500',
                'rows': 3,
                'placeholder': 'Brief description of this role...'
            }),
        }
        help_texts = {
            'name': 'Lowercase, no spaces. Used internally by the system.',
            'display_name': 'Human-readable name shown in the interface.',
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Create permission checkboxes
        permission_choices = [
            ('dashboard', 'Dashboard Access'),
            ('appointments', 'Appointment Management'),
            ('patients', 'Patient Management'),
            ('billing', 'Billing & Services'),
            ('reports', 'Reports & Analytics'),
            ('maintenance', 'System Maintenance'),
        ]
        
        for perm_key, perm_label in permission_choices:
            field_name = f'perm_{perm_key}'
            initial_value = False
            
            if self.instance and self.instance.permissions:
                initial_value = self.instance.permissions.get(perm_key, False)
            
            self.fields[field_name] = forms.BooleanField(
                label=perm_label,
                required=False,
                initial=initial_value,
                widget=forms.CheckboxInput(attrs={
                    'class': 'rounded border-gray-300 text-primary-600 shadow-sm focus:border-primary-500 focus:ring-primary-500'
                })
            )
    
    def clean_name(self):
        name = self.cleaned_data['name'].lower().strip()
        
        # Only prevent new roles from using reserved names
        # Allow editing existing roles (including default ones)
        reserved_names = ['admin', 'dentist', 'staff']
        
        if name in reserved_names:
            # If this is an existing role with the same name, allow it (editing existing role)
            if self.instance and self.instance.pk and self.instance.name == name:
                return name
            # If this is a new role or changing name to reserved name, prevent it
            else:
                raise forms.ValidationError("This name is reserved for system roles.")
        
        return name
    
    def save(self, commit=True):
        role = super().save(commit=False)
        
        # Build permissions dict from checkboxes
        permissions = {}
        permission_keys = ['dashboard', 'appointments', 'patients', 'billing', 'reports', 'maintenance']
        
        for perm_key in permission_keys:
            field_name = f'perm_{perm_key}'
            permissions[perm_key] = self.cleaned_data.get(field_name, False)
        
        role.permissions = permissions
        
        if commit:
            role.save()
        return role