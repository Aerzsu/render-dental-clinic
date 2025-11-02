# core/models.py
from django.db import models
from django.utils import timezone
from datetime import datetime


class SystemSetting(models.Model):
    """Simplified system settings - just key-value pairs"""
    key = models.CharField(max_length=100, unique=True)
    value = models.TextField()
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = 'System Setting'
        verbose_name_plural = 'System Settings'
        ordering = ['key']
    
    def __str__(self):
        return f"{self.key}: {self.value}"
    
    @classmethod
    def get_setting(cls, key, default=None):
        """Get a setting value by key"""
        try:
            setting = cls.objects.get(key=key, is_active=True)
            return setting.value
        except cls.DoesNotExist:
            return default
    
    @classmethod
    def get_int_setting(cls, key, default=0):
        """Get an integer setting value"""
        try:
            setting = cls.objects.get(key=key, is_active=True)
            return int(setting.value)
        except (cls.DoesNotExist, ValueError):
            return default
    
    @classmethod
    def get_bool_setting(cls, key, default=False):
        """Get a boolean setting value"""
        try:
            setting = cls.objects.get(key=key, is_active=True)
            return setting.value.lower() in ('true', '1', 'yes', 'on')
        except cls.DoesNotExist:
            return default
    
    @classmethod
    def get_time_setting(cls, key, default=None):
        """Get a time setting value"""
        try:
            setting = cls.objects.get(key=key, is_active=True)
            return datetime.strptime(setting.value, '%H:%M').time()
        except (cls.DoesNotExist, ValueError):
            return default
    
    @classmethod
    def set_setting(cls, key, value, description=''):
        """Set or update a setting"""
        setting, created = cls.objects.get_or_create(
            key=key,
            defaults={
                'value': str(value),
                'description': description,
                'is_active': True
            }
        )
        if not created:
            setting.value = str(value)
            setting.description = description
            setting.is_active = True
            setting.save()
        return setting
    
    @classmethod
    def initialize_auto_approval_settings(cls):
        """Initialize auto-approval settings with defaults"""
        defaults = {
            'auto_approval_enabled': ('false', 'Enable automatic approval for eligible appointments'),
            'auto_approve_require_existing': ('true', 'Require existing patients with completed appointments for auto-approval'),
        }
        
        for key, (value, description) in defaults.items():
            cls.objects.get_or_create(
                key=key,
                defaults={
                    'value': value,
                    'description': description,
                    'is_active': True
                }
            )


class AuditLog(models.Model):
    """Enhanced audit logging with detailed change tracking"""
    ACTION_CHOICES = [
        ('create', 'Create'),
        ('update', 'Update'),
        ('delete', 'Delete'),
        ('login', 'Login'),
        ('logout', 'Logout'),
        ('login_failed', 'Login Failed'),
        ('approve', 'Approve'),
        ('reject', 'Reject'),
        ('cancel', 'Cancel'),
        ('password_change', 'Password Change'),
        ('status_change', 'Status Change'),
    ]
    
    # User and action info
    user = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    
    # Model info
    model_name = models.CharField(max_length=50)
    object_id = models.PositiveIntegerField(null=True, blank=True)
    object_repr = models.CharField(max_length=200, blank=True)
    
    # Change details
    changes = models.JSONField(default=dict, blank=True)
    description = models.TextField(blank=True, help_text="Human-readable description of the change")
    
    # Request info
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)
    
    # Timestamp
    timestamp = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['user', 'timestamp']),
            models.Index(fields=['model_name', 'timestamp']),
            models.Index(fields=['action', 'timestamp']),
            models.Index(fields=['timestamp']),
        ]
        verbose_name = 'Audit Log'
        verbose_name_plural = 'Audit Logs'
    
    def __str__(self):
        user_str = self.user.username if self.user else 'Anonymous'
        return f"{user_str} {self.action} {self.model_name} at {self.timestamp}"
    
    @property
    def changed_fields(self):
        """Get list of changed field names"""
        if not self.changes:
            return []
        return list(self.changes.keys())
    
    @property
    def has_changes(self):
        """Check if there are any changes"""
        return bool(self.changes)
    
    @classmethod
    def log_action(cls, user, action, model_instance, changes=None, request=None, description=''):
        """
        Log an action with optional change details
        
        Args:
            user: User who performed the action (can be None for anonymous)
            action: Action type (create, update, delete, etc.)
            model_instance: The model instance that was changed
            changes: Dict of field changes {field_name: {'old': ..., 'new': ...}}
            request: HttpRequest object for IP/user agent
            description: Human-readable description
        """
        log_entry = cls(
            user=user,
            action=action,
            model_name=model_instance._meta.model_name,
            object_id=model_instance.pk,
            object_repr=str(model_instance)[:200],
            changes=changes or {},
            description=description
        )
        
        if request:
            log_entry.ip_address = cls.get_client_ip(request)
            log_entry.user_agent = request.META.get('HTTP_USER_AGENT', '')[:255]
        
        log_entry.save()
        return log_entry
    
    @classmethod
    def log_login(cls, user, request, success=True):
        """Log login attempts"""
        action = 'login' if success else 'login_failed'
        description = f"User {'logged in successfully' if success else 'failed to login'}"
        
        log_entry = cls(
            user=user if success else None,
            action=action,
            model_name='user',
            object_id=user.pk if user else None,
            object_repr=user.username if user else 'Unknown',
            description=description
        )
        
        if request:
            log_entry.ip_address = cls.get_client_ip(request)
            log_entry.user_agent = request.META.get('HTTP_USER_AGENT', '')[:255]
        
        log_entry.save()
        return log_entry
    
    @classmethod
    def log_logout(cls, user, request):
        """Log logout"""
        log_entry = cls(
            user=user,
            action='logout',
            model_name='user',
            object_id=user.pk,
            object_repr=user.username,
            description='User logged out'
        )
        
        if request:
            log_entry.ip_address = cls.get_client_ip(request)
            log_entry.user_agent = request.META.get('HTTP_USER_AGENT', '')[:255]
        
        log_entry.save()
        return log_entry
    
    @staticmethod
    def get_client_ip(request):
        """Get client IP address from request"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
    
    @staticmethod
    def format_field_value(value):
        """Format field value for display in logs"""
        if value is None:
            return 'None'
        elif isinstance(value, bool):
            return 'Yes' if value else 'No'
        elif isinstance(value, (list, tuple)):
            return ', '.join(str(v) for v in value)
        elif hasattr(value, 'strftime'):
            return value.strftime('%Y-%m-%d %H:%M:%S')
        else:
            return str(value)
    
    @staticmethod
    def get_field_changes(old_instance, new_instance, fields_to_track=None, fields_to_ignore=None):
        """
        Compare two model instances and return changes
        
        Args:
            old_instance: Previous state of the model
            new_instance: Current state of the model
            fields_to_track: List of field names to track (None = all fields)
            fields_to_ignore: List of field names to ignore
        
        Returns:
            Dict of changes: {field_name: {'old': old_value, 'new': new_value, 'label': field_label}}
        """
        if fields_to_ignore is None:
            fields_to_ignore = ['updated_at', 'created_at']
        
        changes = {}
        
        for field in new_instance._meta.fields:
            field_name = field.name
            
            # Skip ignored fields
            if field_name in fields_to_ignore:
                continue
            
            # Skip if not in tracking list (when specified)
            if fields_to_track and field_name not in fields_to_track:
                continue
            
            old_value = getattr(old_instance, field_name, None)
            new_value = getattr(new_instance, field_name, None)
            
            # Check if value changed
            if old_value != new_value:
                # Get verbose name for better display
                field_label = field.verbose_name.title()
                
                # Format values for display
                old_display = AuditLog.format_field_value(old_value)
                new_display = AuditLog.format_field_value(new_value)
                
                changes[field_name] = {
                    'old': old_display,
                    'new': new_display,
                    'label': field_label
                }
        
        return changes
    
# asd