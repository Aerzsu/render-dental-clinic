# services/models.py
from django.db import models
from django.core.validators import MinValueValidator
from decimal import Decimal

class ActiveServiceManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(is_archived=False)

class Service(models.Model):
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    duration_minutes = models.PositiveIntegerField(
        default=30,
        help_text="Duration of the service in minutes"
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
        from django.core.exceptions import ValidationError
        if self.max_price < self.min_price:
            raise ValidationError('Max price cannot be less than min price.')
    
    @property
    def price_range_display(self):
        if self.min_price == self.max_price:
            return f"₱{self.min_price:,.0f}"
        return f"₱{self.min_price:,.0f} - ₱{self.max_price:,.0f}"
    
    @property
    def duration_display(self):
        hours = self.duration_minutes // 60
        minutes = self.duration_minutes % 60
        
        if hours > 0:
            return f"{hours}h {minutes}m" if minutes > 0 else f"{hours}h"
        return f"{minutes}m"

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
        from django.core.exceptions import ValidationError
        if self.is_percentage and self.amount > 100:
            raise ValidationError('Percentage discount cannot exceed 100%.')
    
    @property
    def display_value(self):
        if self.is_percentage:
            return f"{self.amount}%"
        return f"₱{self.amount:,.2f}"
    
    def calculate_discount(self, original_amount):
        """Calculate discount amount based on original amount"""
        if self.is_percentage:
            return original_amount * (self.amount / 100)
        return min(self.amount, original_amount)  # Don't exceed original amount