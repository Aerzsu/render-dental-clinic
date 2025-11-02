# users/models.py
from django.contrib.auth.models import AbstractUser
from django.db import models

class Role(models.Model):
    ADMIN = 'admin'
    DENTIST = 'dentist'
    STAFF = 'staff'
   
    ROLE_CHOICES = [
        (ADMIN, 'Admin'),
        (DENTIST, 'Dentist'),
        (STAFF, 'Staff'),
    ]
   
    name = models.CharField(max_length=50, unique=True)
    display_name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    permissions = models.JSONField(default=dict, help_text="Module permissions")
    is_default = models.BooleanField(default=False)
    is_archived = models.BooleanField(default=False, help_text="Archived roles are hidden from user assignment")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
   
    class Meta:
        ordering = ['name']
   
    def __str__(self):
        return self.display_name
    
    def is_protected(self):
        """Only admin role is protected from editing"""
        return self.name == 'admin'
    
    def can_be_archived(self):
        """Admin role cannot be archived, and archived roles cannot be archived again"""
        return not self.is_protected() and not self.is_archived
    
    def can_be_restored(self):
        """Only archived roles can be restored"""
        return self.is_archived
    
    def save(self, *args, **kwargs):
        # Set default permissions for default roles only if permissions are empty
        if self.is_default and not self.permissions:
            if self.name == 'admin':
                self.permissions = {
                    'dashboard': True,
                    'appointments': True,
                    'patients': True,
                    'billing': True,
                    'reports': True,
                    'maintenance': True,
                }
            elif self.name == 'dentist':
                self.permissions = {
                    'dashboard': True,
                    'appointments': True,
                    'patients': True,
                    'billing': True,
                    'reports': False,
                    'maintenance': False,
                }
            elif self.name == 'staff':
                self.permissions = {
                    'dashboard': True,
                    'appointments': True,
                    'patients': True,
                    'billing': False,
                    'reports': False,
                    'maintenance': False,
                }
        super().save(*args, **kwargs)

class User(AbstractUser):

    role = models.ForeignKey(Role, on_delete=models.PROTECT, null=True, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    is_active_dentist = models.BooleanField(default=False, help_text="Can accept appointments")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
   
    def __str__(self):
        return f"{self.get_full_name()} ({self.username})"
   
    def has_permission(self, module_name):
        """Check if user has permission for a specific module"""
        if self.is_superuser:
            return True
        if not self.role or self.role.is_archived:  # Users with archived roles lose access
            return False
        return self.role.permissions.get(module_name, False)
   
    @property
    def full_name(self):
        return self.get_full_name() or self.username

# asd