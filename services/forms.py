# services/forms.py
from decimal import Decimal
from django import forms
from .models import Service, Discount, ProductCategory, Product

class ServiceForm(forms.ModelForm):
    """Form for creating and updating services with 30-minute duration increments"""
    
    class Meta:
        model = Service
        fields = ['name', 'description', 'min_price', 'max_price', 'duration_minutes']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500'
            }),
            'description': forms.Textarea(attrs={
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
                'rows': 4
            }),
            'min_price': forms.NumberInput(attrs={
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
                'step': '1',
                'min': '1'
            }),
            'max_price': forms.NumberInput(attrs={
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
                'step': '1',
                'min': '1'
            }),
            'duration_minutes': forms.NumberInput(attrs={
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
                'step': '30',
                'min': '30',
                'value': '30'
            }),
        }
        help_texts = {
            'duration_minutes': 'Duration in 30-minute increments (e.g., 30, 60, 90, 120 minutes)',
        }
    
    def clean_duration_minutes(self):
        """Validate that duration is in 30-minute increments"""
        duration = self.cleaned_data.get('duration_minutes')
        
        if duration is None:
            raise forms.ValidationError('Duration is required.')
        
        if duration < 30:
            raise forms.ValidationError('Duration must be at least 30 minutes.')
        
        if duration % 30 != 0:
            raise forms.ValidationError('Duration must be in 30-minute increments (e.g., 30, 60, 90, 120 minutes).')
        
        return duration
    
    def clean(self):
        """Additional validation for price range"""
        cleaned_data = super().clean()
        min_price = cleaned_data.get('min_price')
        max_price = cleaned_data.get('max_price')
        
        if min_price and max_price and max_price < min_price:
            raise forms.ValidationError('Maximum price cannot be less than minimum price.')
        
        return cleaned_data

class DiscountForm(forms.ModelForm):
    """Form for creating and updating discounts"""
    
    # Add the discount_type field for radio buttons
    discount_type = forms.ChoiceField(
        choices=[('false', 'Fixed Amount'), ('true', 'Percentage')],
        widget=forms.RadioSelect,
        required=False,  # We'll handle this in clean()
        initial='false'
    )
    
    class Meta:
        model = Discount
        fields = ['name', 'amount', 'is_percentage']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
                'placeholder': 'e.g., Senior Citizen Discount'
            }),
            'amount': forms.NumberInput(attrs={
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500', 
                'step': '1',
                'min': '1'
            }),
            # Hide the original checkbox since we're using radio buttons
            'is_percentage': forms.HiddenInput(),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Set initial discount_type based on is_percentage value
        if self.instance and self.instance.pk:
            self.fields['discount_type'].initial = 'true' if self.instance.is_percentage else 'false'
        
        # Make name field required with better validation
        self.fields['name'].required = True
        self.fields['amount'].required = True
    
    def clean_discount_type(self):
        """Validate discount_type field"""
        discount_type = self.cleaned_data.get('discount_type')
        if discount_type not in ['true', 'false']:
            raise forms.ValidationError('Please select a valid discount type.')
        return discount_type
    
    def clean_amount(self):
        """Validate amount field"""
        amount = self.cleaned_data.get('amount')
        if not amount or amount <= 0:
            raise forms.ValidationError('Discount amount must be greater than zero.')
        return amount
    
    def clean_name(self):
        """Validate name field"""
        name = self.cleaned_data.get('name', '').strip()
        if not name:
            raise forms.ValidationError('Discount name is required.')
        
        # Check for duplicate names (excluding current instance)
        existing_discount = Discount.objects.filter(name__iexact=name)
        if self.instance and self.instance.pk:
            existing_discount = existing_discount.exclude(pk=self.instance.pk)
        
        if existing_discount.exists():
            raise forms.ValidationError('A discount with this name already exists.')
        
        return name
    
    def clean(self):
        """Cross-field validation"""
        cleaned_data = super().clean()
        amount = cleaned_data.get('amount')
        discount_type = cleaned_data.get('discount_type')
        
        # Convert discount_type to boolean for is_percentage
        if discount_type == 'true':
            cleaned_data['is_percentage'] = True
            is_percentage = True
        else:
            cleaned_data['is_percentage'] = False
            is_percentage = False
        
        # Validate percentage constraints
        if is_percentage and amount and amount > 100:
            raise forms.ValidationError('Percentage discount cannot exceed 100%.')
        
        # Validate reasonable limits for fixed amounts
        if not is_percentage and amount and amount > 50000:
            raise forms.ValidationError('Fixed discount amount seems unusually high. Please verify.')
        
        return cleaned_data
    
    def save(self, commit=True):
        """Override save to ensure is_percentage is set correctly"""
        instance = super().save(commit=False)
        
        # Set is_percentage based on discount_type
        discount_type = self.cleaned_data.get('discount_type', 'false')
        instance.is_percentage = (discount_type == 'true')
        
        if commit:
            instance.save()
        return instance


class ProductCategoryForm(forms.ModelForm):
    """Form for creating and updating product categories"""
    
    class Meta:
        model = ProductCategory
        fields = ['name', 'description', 'display_order']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
                'placeholder': 'e.g., Medications, Consumables, Materials'
            }),
            'description': forms.Textarea(attrs={
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
                'rows': 3,
                'placeholder': 'Optional description of this category'
            }),
            'display_order': forms.NumberInput(attrs={
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
                'min': '0',
                'value': '0'
            }),
        }
        help_texts = {
            'display_order': 'Categories with lower numbers appear first in lists',
        }
    
    def clean_name(self):
        """Validate category name is unique (case-insensitive)"""
        name = self.cleaned_data.get('name', '').strip()
        if not name:
            raise forms.ValidationError('Category name is required.')
        
        # Check for case-insensitive duplicates
        existing = ProductCategory.objects.filter(name__iexact=name)
        if self.instance and self.instance.pk:
            existing = existing.exclude(pk=self.instance.pk)
        
        if existing.exists():
            raise forms.ValidationError(f'A category with the name "{name}" already exists.')
        
        return name


class ProductForm(forms.ModelForm):
    """Form for creating and updating products"""
    
    class Meta:
        model = Product
        fields = ['name', 'description', 'category', 'price']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
                'placeholder': 'e.g., Anesthesia 2mL, Cotton Gauze Pack of 10'
            }),
            'description': forms.Textarea(attrs={
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
                'rows': 3,
                'placeholder': 'Optional product description or notes'
            }),
            'category': forms.Select(attrs={
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500'
            }),
            'price': forms.NumberInput(attrs={
                'class': 'mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500',
                'step': '0.01',
                'min': '1.00',
                'placeholder': '0.00'
            }),
        }
        help_texts = {
            'name': 'Include unit details in the name (e.g., size, quantity, volume)',
            'price': 'Unit price in Philippine Peso (₱)',
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only show active categories
        self.fields['category'].queryset = ProductCategory.objects.all()
        self.fields['name'].required = True
        self.fields['category'].required = True
        self.fields['price'].required = True
    
    def clean_name(self):
        """Validate product name is unique (case-insensitive)"""
        name = self.cleaned_data.get('name', '').strip()
        if not name:
            raise forms.ValidationError('Product name is required.')
        
        # Check for case-insensitive duplicates
        existing = Product.objects.filter(name__iexact=name)
        if self.instance and self.instance.pk:
            existing = existing.exclude(pk=self.instance.pk)
        
        if existing.exists():
            raise forms.ValidationError(
                f'A product with the name "{name}" already exists. '
                'Please use a different name or include unit details '
                '(e.g., "Alcohol 250mL" vs "Alcohol 500mL").'
            )
        
        return name
    
    def clean_price(self):
        """Validate price is at least ₱1.00"""
        price = self.cleaned_data.get('price')
        if price and price < Decimal('1.00'):
            raise forms.ValidationError('Product price must be at least ₱1.00.')
        return price