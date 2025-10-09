# core/signals.py
import sys
from django.db.models.signals import post_save, pre_save, post_delete
from django.dispatch import receiver
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.db import transaction
from .models import AuditLog
from .middleware import get_current_user


# Track original state before save
_original_instances = {}


@receiver(pre_save)
def store_original_instance(sender, instance, **kwargs):
    """Store original instance before save for comparison"""
    # Skip AuditLog itself to prevent infinite loops
    if sender.__name__ == 'AuditLog':
        return
    
    # Only track if instance already exists (for updates)
    if instance.pk:
        try:
            original = sender.objects.get(pk=instance.pk)
            _original_instances[f"{sender.__name__}_{instance.pk}"] = original
        except sender.DoesNotExist:
            pass


@receiver(post_save)
def log_model_save(sender, instance, created, **kwargs):
    """Automatically log create and update actions"""
    
    # CRITICAL: Skip during migrations and tests
    if 'migrate' in sys.argv or 'test' in sys.argv:
        return
    
    # Skip if explicitly disabled
    if hasattr(instance, '_skip_audit_log') and instance._skip_audit_log:
        return
    
    # Skip for certain models that shouldn't be logged
    from django.contrib.contenttypes.models import ContentType
    from django.contrib.sessions.models import Session
    if isinstance(instance, (ContentType, Session)):
        return
    
    # Import here to avoid circular imports
    from .models import AuditLog

    # Skip these models
    skip_models = ['AuditLog', 'Session', 'LogEntry', 'ContentType', 'Permission']
    if sender.__name__ in skip_models:
        return
    
    # Skip if explicitly disabled via instance attribute
    if getattr(instance, '_skip_audit_log', False):
        return
    
    # Get current user from middleware or instance attribute
    user = get_current_user() or getattr(instance, '_current_user', None)
    
    # Determine action and changes
    if created:
        action = 'create'
        changes = {}
        description = f"Created new {sender._meta.verbose_name}: {instance}"
    else:
        action = 'update'
        
        # Get original instance for comparison
        original_key = f"{sender.__name__}_{instance.pk}"
        original = _original_instances.pop(original_key, None)
        
        if original:
            # Get field changes
            changes = AuditLog.get_field_changes(original, instance)
            
            # Generate description
            if changes:
                changed_fields = ', '.join([v['label'] for v in changes.values()])
                description = f"Updated {sender._meta.verbose_name}: {changed_fields}"
            else:
                # No changes detected, skip logging
                return
        else:
            changes = {}
            description = f"Updated {sender._meta.verbose_name}: {instance}"
    
    # Special handling for specific models
    if sender.__name__ == 'User':
        # Don't log password in changes
        if 'password' in changes:
            changes['password'] = {
                'old': '••••••••',
                'new': '••••••••',
                'label': 'Password'
            }
            description = "Changed password"
    
    elif sender.__name__ == 'Appointment':
        # Special logging for appointment status changes
        if changes.get('status'):
            old_status = changes['status']['old']
            new_status = changes['status']['new']
            
            if new_status == 'confirmed':
                action = 'approve'
                description = f"Approved appointment: {old_status} → {new_status}"
            elif new_status == 'rejected':
                action = 'reject'
                description = f"Rejected appointment request"
            elif new_status == 'cancelled':
                action = 'cancel'
                description = f"Cancelled appointment"
            elif new_status == 'completed':
                description = f"Marked appointment as completed"
    
    # Log the action
    AuditLog.objects.create(
        user=user,
        action=action,
        model_name=sender._meta.model_name,
        object_id=instance.pk,
        object_repr=str(instance)[:200],
        changes=changes,
        description=description
    )


@receiver(post_delete)
def log_model_delete(sender, instance, **kwargs):
    """Automatically log delete actions"""

    # CRITICAL: Skip during migrations and tests
    if 'migrate' in sys.argv or 'test' in sys.argv:
        return
    
    # Skip if explicitly disabled
    if hasattr(instance, '_skip_audit_log') and instance._skip_audit_log:
        return
    
    # Skip these models
    skip_models = ['AuditLog', 'Session', 'LogEntry', 'ContentType', 'Permission']
    if sender.__name__ in skip_models:
        return
    
    # Get current user from middleware or instance attribute
    user = get_current_user() or getattr(instance, '_current_user', None)
    
    AuditLog.objects.create(
        user=user,
        action='delete',
        model_name=sender._meta.model_name,
        object_id=instance.pk,
        object_repr=str(instance)[:200],
        description=f"Deleted {sender._meta.verbose_name}: {instance}"
    )


@receiver(user_logged_in)
def log_user_login(sender, request, user, **kwargs):
    """Log successful user login"""
    AuditLog.log_login(user, request, success=True)


@receiver(user_logged_out)
def log_user_logout(sender, request, user, **kwargs):
    """Log user logout"""
    if user:
        AuditLog.log_logout(user, request)


@receiver(user_login_failed)
def log_failed_login(sender, credentials, request, **kwargs):
    """Log failed login attempts"""
    from users.models import User
    
    # Try to find user
    username = credentials.get('username')
    user = None
    if username:
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            pass
    
    # Count recent failed attempts for this user
    if user:
        from django.utils import timezone
        from datetime import timedelta
        
        # Count failed attempts in last 30 minutes
        thirty_min_ago = timezone.now() - timedelta(minutes=30)
        recent_failures = AuditLog.objects.filter(
            object_id=user.pk,
            model_name='user',
            action='login_failed',
            timestamp__gte=thirty_min_ago
        ).count()
        
        # Only log if this is the 5th attempt or more
        if recent_failures >= 4:
            description = f"Multiple failed login attempts ({recent_failures + 1})"
            AuditLog.objects.create(
                user=None,
                action='login_failed',
                model_name='user',
                object_id=user.pk,
                object_repr=user.username,
                description=description,
                ip_address=AuditLog.get_client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', '')[:255]
            )
    else:
        # Unknown username - log as suspicious activity
        AuditLog.objects.create(
            user=None,
            action='login_failed',
            model_name='user',
            object_repr=username or 'Unknown',
            description=f"Failed login attempt with unknown username: {username}",
            ip_address=AuditLog.get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:255]
        )