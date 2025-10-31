# services/models.py
from django.db import models
from django.core.validators import MinValueValidator
from django.core.exceptions import ValidationError
from decimal import Decimal


class ActiveServiceManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(is_archived=False)


class Service(models.Model):
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    duration_minutes = models.PositiveIntegerField(
        default=30,
        help_text="Duration of the service in minutes (must be in 30-minute increments)"
    )
    min_price = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        null=True, 
        blank=True,
        help_text="Minimum price for this service"
    )
    max_price = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        null=True, 
        blank=True,
        help_text="Maximum price for this service"
    )
    is_archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    objects = models.Manager()  # Default manager
    active = ActiveServiceManager()  # Custom manager for active services only

    class Meta:
        ordering = ['name']
    
    def __str__(self):
        return self.name
    
    def clean(self):
        """Model-level validation"""
        # Validate duration is multiple of 30
        if self.duration_minutes is not None:
            if self.duration_minutes <= 0:
                raise ValidationError({
                    'duration_minutes': 'Duration must be greater than 0 minutes.'
                })
            
            if self.duration_minutes % 30 != 0:
                raise ValidationError({
                    'duration_minutes': 'Duration must be in 30-minute increments (e.g., 30, 60, 90, 120 minutes).'
                })
        
        # Validate price range
        if self.min_price is not None and self.max_price is not None:
            if self.max_price < self.min_price:
                raise ValidationError({
                    'max_price': 'Maximum price cannot be less than minimum price.'
                })
    
    @property
    def price_range_display(self):
        """Display price range in user-friendly format"""
        if self.min_price == self.max_price:
            return f"₱{self.min_price:,.0f}"
        return f"₱{self.min_price:,.0f} - ₱{self.max_price:,.0f}"
    
    @property
    def starting_price_display(self):
        """Display starting price (for booking page)"""
        return f"₱{self.min_price:,.0f}"
    
    @property
    def duration_display(self):
        """Display duration in human-readable format"""
        hours = self.duration_minutes // 60
        minutes = self.duration_minutes % 60
        
        if hours > 0 and minutes > 0:
            return f"{hours}h {minutes}m"
        elif hours > 0:
            return f"{hours}h"
        else:
            return f"{minutes}m"
    
    @property
    def duration_hours(self):
        """Get duration in hours (as decimal)"""
        return self.duration_minutes / 60

class Discount(models.Model):
    name = models.CharField(max_length=100)
    amount = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    is_percentage = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['name']
    
    def __str__(self):
        return self.name
    
    def clean(self):
        if self.is_percentage and self.amount > 100:
            raise ValidationError('Percentage discount cannot exceed 100%.')
    
    @property
    def display_value(self):
        if self.is_percentage:
            return f"{self.amount}% off"
        return f"₱{self.amount:,.2f}"
    
    def calculate_discount(self, original_amount):
        """Calculate discount amount based on original amount"""
        if self.is_percentage:
            return original_amount * (self.amount / 100)
        return min(self.amount, original_amount)  # Don't exceed original amount
    
class ProductCategory(models.Model):
    """Product category for organizing supplies and materials"""
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    display_order = models.PositiveIntegerField(
        default=0,
        help_text="Order in which categories are displayed (lower numbers first)"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['display_order', 'name']
        verbose_name = 'Product Category'
        verbose_name_plural = 'Product Categories'
    
    def __str__(self):
        return self.name
    
    def clean(self):
        """Validate category name is unique (case-insensitive)"""
        if self.name:
            # Check for case-insensitive duplicates
            existing = ProductCategory.objects.filter(name__iexact=self.name)
            if self.pk:
                existing = existing.exclude(pk=self.pk)
            
            if existing.exists():
                raise ValidationError({
                    'name': f'A category with the name "{self.name}" already exists.'
                })
    
    def can_be_deleted(self):
        """Check if category can be deleted (no active products)"""
        return not self.products.filter(is_active=True).exists()
    
    def get_active_products_count(self):
        """Get count of active products in this category"""
        return self.products.filter(is_active=True).count()
    
    def get_total_products_count(self):
        """Get total count of products (including inactive)"""
        return self.products.count()


class Product(models.Model):
    """Product/Supply model for dental materials and consumables"""
    name = models.CharField(
        max_length=200,
        help_text="Product name including unit (e.g., 'Anesthesia 2mL', 'Cotton Gauze Pack of 10')"
    )
    description = models.TextField(blank=True)
    category = models.ForeignKey(
        ProductCategory, 
        on_delete=models.PROTECT,
        related_name='products',
        help_text="Product category"
    )
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('1.00'))],
        help_text="Unit price (minimum ₱1.00)"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Inactive products are hidden from selection"
    )
    
    # Audit fields
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        'users.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_products'
    )
    
    class Meta:
        ordering = ['category', 'name']
        indexes = [
            models.Index(fields=['category', 'is_active'], name='product_cat_active_idx'),
            models.Index(fields=['name'], name='product_name_idx'),
        ]
    
    def __str__(self):
        return f"{self.name} - ₱{self.price}"
    
    def clean(self):
        """Model-level validation"""
        if self.name:
            # Check for case-insensitive duplicate names
            existing = Product.objects.filter(name__iexact=self.name)
            if self.pk:
                existing = existing.exclude(pk=self.pk)
            
            if existing.exists():
                raise ValidationError({
                    'name': f'A product with the name "{self.name}" already exists. Please use a different name or include unit details (e.g., "Alcohol 250mL" vs "Alcohol 500mL").'
                })
        
        # Validate price
        if self.price and self.price < Decimal('1.00'):
            raise ValidationError({
                'price': 'Product price must be at least ₱1.00.'
            })
    
    @property
    def price_display(self):
        """Display price in user-friendly format"""
        return f"₱{self.price:,.2f}"
    
    @property
    def status_display(self):
        """Display status in user-friendly format"""
        return "Active" if self.is_active else "Inactive"

class ServicePreset(models.Model):
    """
    Template/preset for a service with predefined products
    Allows dentists to save common product combinations for faster documentation
    PRIVATE: Each dentist sees only their own presets
    """
    name = models.CharField(
        max_length=200,
        help_text="Preset name (e.g., 'Simple Extraction', 'Surgical Extraction')"
    )
    service = models.ForeignKey(
        Service,
        on_delete=models.CASCADE,
        related_name='presets',
        help_text="Service this preset applies to"
    )
    created_by = models.ForeignKey(
        'users.User',
        on_delete=models.CASCADE,
        related_name='service_presets',
        help_text="Dentist who owns this preset (private)"
    )
    description = models.TextField(
        blank=True,
        help_text="Optional description (e.g., 'For complicated cases requiring sutures')"
    )
    is_default = models.BooleanField(
        default=False,
        help_text="Auto-apply this preset when service is selected in treatment record"
    )
    
    # Audit
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-is_default', 'name']
        indexes = [
            models.Index(fields=['service', 'created_by'], name='preset_svc_user_idx'),
            models.Index(fields=['created_by'], name='preset_user_idx'),
        ]
        # Ensure unique default per service per user
        constraints = [
            models.UniqueConstraint(
                fields=['service', 'created_by'],
                condition=models.Q(is_default=True),
                name='unique_default_preset_per_service_per_user'
            )
        ]
    
    def __str__(self):
        return f"{self.name} - {self.service.name} ({self.created_by.full_name})"
    
    def clean(self):
        """Model-level validation"""
        # Skip validation if created_by is not set yet (will be validated in form)
        if not self.created_by_id:
            return
        
        # Check preset limit per service per user (max 5)
        if not self.pk:  # Only for new presets
            existing_count = ServicePreset.objects.filter(
                service=self.service,
                created_by_id=self.created_by_id
            ).count()
            
            if existing_count >= 5:
                raise ValidationError(
                    f'You already have 5 presets for {self.service.name}. '
                    f'Please delete an existing preset before creating a new one.'
                )
        
        # Validate name uniqueness per service per user
        existing = ServicePreset.objects.filter(
            service=self.service,
            created_by_id=self.created_by_id,
            name__iexact=self.name
        )
        if self.pk:
            existing = existing.exclude(pk=self.pk)
        
        if existing.exists():
            raise ValidationError({
                'name': f'You already have a preset named "{self.name}" for {self.service.name}.'
            })
    
    def save(self, *args, **kwargs):
        # If setting as default, unset other defaults for this service/user
        if self.is_default:
            ServicePreset.objects.filter(
                service=self.service,
                created_by=self.created_by,
                is_default=True
            ).exclude(pk=self.pk).update(is_default=False)
        
        super().save(*args, **kwargs)
    
    @property
    def products_count(self):
        """Get count of products in this preset"""
        return self.products.count()
    
    @property
    def products_summary(self):
        """Get brief summary of products (first 3)"""
        products = self.products.select_related('product')[:3]
        names = [f"{p.product.name} x{p.quantity}" for p in products]
        
        if self.products_count > 3:
            names.append(f"+{self.products_count - 3} more")
        
        return ", ".join(names) if names else "No products"
    
    def can_delete(self):
        """Check if preset can be deleted (always yes, no dependencies)"""
        return True
    
    def get_products_data(self):
        """Get products data in format suitable for frontend"""
        products_data = []
        for preset_product in self.products.select_related('product'):
            products_data.append({
                'product_id': preset_product.product.id,
                'product_name': preset_product.product.name,
                'quantity': preset_product.quantity,
                'notes': preset_product.notes
            })
        return products_data


class ServicePresetProduct(models.Model):
    """
    Products included in a service preset
    Junction table between ServicePreset and Product
    """
    preset = models.ForeignKey(
        ServicePreset,
        on_delete=models.CASCADE,
        related_name='products',
        help_text="Parent preset"
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        help_text="Product to include in preset"
    )
    quantity = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
        help_text="Default quantity"
    )
    notes = models.CharField(
        max_length=200,
        blank=True,
        help_text="Optional notes about this product in this preset"
    )
    order = models.PositiveIntegerField(
        default=0,
        help_text="Display order"
    )
    
    class Meta:
        ordering = ['order', 'product__name']
        unique_together = ['preset', 'product']
        indexes = [
            models.Index(fields=['preset'], name='preset_prod_preset_idx'),
        ]
    
    def __str__(self):
        return f"{self.product.name} x{self.quantity} ({self.preset.name})"
    
    def clean(self):
        """Model-level validation"""
        if self.quantity < 1:
            raise ValidationError('Quantity must be at least 1.')

