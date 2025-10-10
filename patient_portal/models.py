# patient_portal/models.py
"""
Patient portal authentication models
UPDATED: Added purpose field to support both portal and booking OTP
"""
from django.db import models
from django.utils import timezone
from datetime import timedelta
import secrets
import string


class PatientPortalAccess(models.Model):
    """
    Temporary access codes for patient portal authentication AND booking verification
    Codes expire after 15 minutes
    UPDATED: Added purpose and verified_patient fields
    """
    PURPOSE_CHOICES = [
        ('portal', 'Patient Portal Login'),
        ('booking', 'Appointment Booking Verification'),
    ]
    
    email = models.EmailField(db_index=True)
    code = models.CharField(max_length=6, db_index=True)
    purpose = models.CharField(max_length=10, choices=PURPOSE_CHOICES, default='portal', 
                              help_text="What this code is being used for")
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)
    used_at = models.DateTimeField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    
    # For booking: track which patient was selected (null until patient selects)
    verified_patient = models.ForeignKey('patients.Patient', on_delete=models.CASCADE, 
                                        null=True, blank=True, related_name='booking_verifications',
                                        help_text="Selected patient after OTP verification")
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['email', 'code'], name='portal_email_code_idx'),
            models.Index(fields=['expires_at'], name='portal_expires_idx'),
            models.Index(fields=['created_at'], name='portal_created_idx'),
            models.Index(fields=['purpose'], name='portal_purpose_idx'),
        ]
        verbose_name = 'Patient Portal Access'
        verbose_name_plural = 'Patient Portal Access Codes'
    
    def __str__(self):
        status = 'Used' if self.is_used else 'Active'
        return f"{self.email} - {self.code} ({self.get_purpose_display()}) - {status}"
    
    @property
    def is_expired(self):
        """Check if code has expired"""
        return timezone.now() > self.expires_at
    
    @property
    def is_valid(self):
        """Check if code is valid (not used and not expired)"""
        return not self.is_used and not self.is_expired
    
    def mark_as_used(self, patient=None):
        """Mark code as used and optionally link patient"""
        self.is_used = True
        self.used_at = timezone.now()
        if patient:
            self.verified_patient = patient
        self.save(update_fields=['is_used', 'used_at', 'verified_patient'])
    
    @classmethod
    def generate_code(cls):
        """Generate a random 6-digit code"""
        return ''.join(secrets.choice(string.digits) for _ in range(6))
    
    @classmethod
    def create_access_code(cls, email, purpose='portal', ip_address=None):
        """
        Create a new access code for email
        Returns (code_instance, created, error_message) tuple
        
        Rate limiting: max 3 requests per hour
        """
        # Check rate limiting - max 3 requests per hour for this email
        one_hour_ago = timezone.now() - timedelta(hours=1)
        recent_codes = cls.objects.filter(
            email=email,
            purpose=purpose,
            created_at__gte=one_hour_ago
        ).count()
        
        if recent_codes >= 3:
            return None, False, "Too many verification requests. Please wait an hour and try again."
        
        # Generate unique code
        code = cls.generate_code()
        
        # Create access code with 15-minute expiry
        access_code = cls.objects.create(
            email=email,
            code=code,
            purpose=purpose,
            expires_at=timezone.now() + timedelta(minutes=15),
            ip_address=ip_address
        )
        
        return access_code, True, None
    
    @classmethod
    def verify_code(cls, email, code, purpose='portal'):
        """
        Verify if code is valid for email and purpose
        Returns (is_valid, access_code_instance or error_message)
        """
        try:
            access_code = cls.objects.filter(
                email=email,
                code=code,
                purpose=purpose,
                is_used=False
            ).latest('created_at')
            
            if access_code.is_expired:
                return False, 'Code has expired. Please request a new code.'
            
            return True, access_code
            
        except cls.DoesNotExist:
            return False, 'Invalid code. Please check and try again.'
    
    @classmethod
    def get_remaining_attempts(cls, email, purpose='portal'):
        """Get remaining OTP request attempts for this email"""
        one_hour_ago = timezone.now() - timedelta(hours=1)
        recent_codes = cls.objects.filter(
            email=email,
            purpose=purpose,
            created_at__gte=one_hour_ago
        ).count()
        
        return max(0, 3 - recent_codes)
    
    @classmethod
    def cleanup_expired_codes(cls):
        """Delete expired codes older than 24 hours (maintenance task)"""
        cutoff = timezone.now() - timedelta(hours=24)
        deleted_count = cls.objects.filter(expires_at__lt=cutoff).delete()[0]
        return deleted_count


class PatientPortalSession(models.Model):
    """
    Track active patient portal sessions
    Sessions expire after 30 minutes of inactivity
    """
    email = models.EmailField(db_index=True)
    session_key = models.CharField(max_length=40, unique=True, db_index=True)
    patient = models.ForeignKey('patients.Patient', on_delete=models.CASCADE, related_name='portal_sessions')
    created_at = models.DateTimeField(auto_now_add=True)
    last_activity = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField()
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['session_key'], name='portal_session_key_idx'),
            models.Index(fields=['email'], name='portal_session_email_idx'),
            models.Index(fields=['expires_at'], name='portal_session_expires_idx'),
        ]
        verbose_name = 'Patient Portal Session'
        verbose_name_plural = 'Patient Portal Sessions'
    
    def __str__(self):
        return f"{self.email} - Session {self.session_key[:8]}..."
    
    @property
    def is_expired(self):
        """Check if session has expired"""
        return timezone.now() > self.expires_at
    
    @property
    def is_valid(self):
        """Check if session is valid"""
        return self.is_active and not self.is_expired
    
    def refresh(self):
        """Refresh session expiry time"""
        self.expires_at = timezone.now() + timedelta(minutes=30)
        self.save(update_fields=['expires_at', 'last_activity'])
    
    def terminate(self):
        """Terminate session"""
        self.is_active = False
        self.save(update_fields=['is_active'])
    
    @classmethod
    def create_session(cls, email, patient, ip_address=None):
        """Create a new portal session"""
        session_key = secrets.token_urlsafe(32)
        
        session = cls.objects.create(
            email=email,
            session_key=session_key,
            patient=patient,
            expires_at=timezone.now() + timedelta(minutes=30),
            ip_address=ip_address
        )
        
        return session
    
    @classmethod
    def get_valid_session(cls, session_key):
        """Get and validate session by key"""
        try:
            session = cls.objects.get(session_key=session_key, is_active=True)
            
            if session.is_expired:
                session.terminate()
                return None
            
            # Refresh session on access
            session.refresh()
            return session
            
        except cls.DoesNotExist:
            return None
    
    @classmethod
    def cleanup_expired_sessions(cls):
        """Delete expired sessions (maintenance task)"""
        cutoff = timezone.now()
        deleted_count = cls.objects.filter(expires_at__lt=cutoff).delete()[0]
        return deleted_count