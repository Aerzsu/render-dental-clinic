# core/middleware.py
"""
Middleware to track current user for audit logging
This allows signals to access the current user when models are saved
"""

import threading
from django.shortcuts import redirect
from django.urls import reverse
from django.contrib.auth.views import redirect_to_login
from django.utils.cache import add_never_cache_headers

# Thread-local storage for the current user
_thread_locals = threading.local()


def get_current_user():
    """Get the current user from thread-local storage"""
    return getattr(_thread_locals, 'user', None)


def set_current_user(user):
    """Set the current user in thread-local storage"""
    _thread_locals.user = user


class AuditMiddleware:
    """
    Middleware to track the current user for audit logging
    Stores user in thread-local storage so signals can access it
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        # Set current user in thread-local storage
        user = getattr(request, 'user', None)
        if user and user.is_authenticated:
            set_current_user(user)
        else:
            set_current_user(None)
        
        response = self.get_response(request)
        
        # Clean up after request
        set_current_user(None)
        
        return response


class AuditMixin:
    """
    Mixin for models to attach current user before save
    Usage: class MyModel(AuditMixin, models.Model): ...
    """
    
    def save(self, *args, **kwargs):
        # Attach current user to instance for signal handlers
        current_user = get_current_user()
        if current_user:
            self._current_user = current_user
        
        return super().save(*args, **kwargs)
    

class SessionExpiredMiddleware:
    """
    Middleware to handle expired sessions gracefully.
    Redirects unauthenticated users to login page with next parameter.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        return response

    def process_exception(self, request, exception):
        """
        Catch authentication-related exceptions and redirect to login.
        """
        # If user is not authenticated and trying to access protected view
        if not request.user.is_authenticated:
            # Check if the request path requires authentication
            protected_paths = [
                '/dashboard/',
                '/appointments/',
                '/patients/',
                '/users/',
                '/services/',
                '/reports/',
            ]
            
            # Check if current path is protected
            if any(request.path.startswith(path) for path in protected_paths):
                # Redirect to login with next parameter
                return redirect_to_login(
                    request.get_full_path(),
                    login_url=reverse('users:login')
                )
        
        return None


class NoCacheMiddleware:
    """
    Middleware to prevent browser caching of authenticated pages.
    This ensures that after logout, pressing back button won't show cached pages.
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        response = self.get_response(request)
        
        # Only apply no-cache headers to authenticated pages
        if request.user.is_authenticated:
            # Add headers to prevent caching
            add_never_cache_headers(response)
            
            # Additional cache control headers for maximum compatibility
            response['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
            response['Pragma'] = 'no-cache'
            response['Expires'] = '0'
        
        return response