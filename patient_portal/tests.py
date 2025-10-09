# patient_portal/tests.py
"""
Unit tests for patient portal functionality
"""
from django.test import TestCase, Client
from django.utils import timezone
from django.urls import reverse
from datetime import timedelta

from django.db.models.signals import post_save, post_delete
from .models import PatientPortalAccess, PatientPortalSession
from patients.models import Patient
from appointments.models import Appointment, DailySlots
from services.models import Service


class PatientPortalAccessModelTest(TestCase):
    """Test PatientPortalAccess model"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Disconnect audit logging signals for tests
        post_save.disconnect(dispatch_uid='log_model_save')
        post_delete.disconnect(dispatch_uid='log_model_delete')

    def setUp(self):
        self.email = 'test@example.com'
    
    def test_create_access_code(self):
        """Test creating access code"""
        access_code, created = PatientPortalAccess.create_access_code(self.email)
        
        self.assertTrue(created)
        self.assertEqual(access_code.email, self.email)
        self.assertEqual(len(access_code.code), 6)
        self.assertFalse(access_code.is_used)
        self.assertFalse(access_code.is_expired)
    
    def test_code_expiration(self):
        """Test code expiration"""
        access_code, _ = PatientPortalAccess.create_access_code(self.email)
        
        # Should not be expired initially
        self.assertFalse(access_code.is_expired)
        
        # Manually set expiry to past
        access_code.expires_at = timezone.now() - timedelta(minutes=1)
        access_code.save()
        
        self.assertTrue(access_code.is_expired)
        self.assertFalse(access_code.is_valid)
    
    def test_rate_limiting(self):
        """Test rate limiting (max 3 codes per hour)"""
        # Create 3 codes
        for i in range(3):
            access_code, created = PatientPortalAccess.create_access_code(self.email)
            self.assertTrue(created)
        
        # 4th code should fail due to rate limit
        access_code, created = PatientPortalAccess.create_access_code(self.email)
        self.assertIsNone(access_code)
        self.assertFalse(created)
    
    def test_verify_code(self):
        """Test code verification"""
        access_code, _ = PatientPortalAccess.create_access_code(self.email)
        
        # Valid code
        is_valid, result = PatientPortalAccess.verify_code(self.email, access_code.code)
        self.assertTrue(is_valid)
        self.assertEqual(result, access_code)
        
        # Invalid code
        is_valid, message = PatientPortalAccess.verify_code(self.email, '999999')
        self.assertFalse(is_valid)
        self.assertIn('Invalid code', message)
    
    def test_mark_as_used(self):
        """Test marking code as used"""
        access_code, _ = PatientPortalAccess.create_access_code(self.email)
        
        access_code.mark_as_used()
        
        self.assertTrue(access_code.is_used)
        self.assertIsNotNone(access_code.used_at)
        self.assertFalse(access_code.is_valid)


class PatientPortalSessionModelTest(TestCase):
    """Test PatientPortalSession model"""
    
    def setUp(self):
        self.patient = Patient.objects.create(
            first_name='John',
            last_name='Doe',
            email='john@example.com'
        )
    
    def test_create_session(self):
        """Test creating portal session"""
        session = PatientPortalSession.create_session(
            email=self.patient.email,
            patient=self.patient
        )
        
        self.assertEqual(session.email, self.patient.email)
        self.assertEqual(session.patient, self.patient)
        self.assertTrue(session.is_active)
        self.assertFalse(session.is_expired)
    
    def test_session_refresh(self):
        """Test session refresh"""
        session = PatientPortalSession.create_session(
            email=self.patient.email,
            patient=self.patient
        )
        
        old_expires_at = session.expires_at
        session.refresh()
        
        self.assertGreater(session.expires_at, old_expires_at)
    
    def test_session_termination(self):
        """Test session termination"""
        session = PatientPortalSession.create_session(
            email=self.patient.email,
            patient=self.patient
        )
        
        session.terminate()
        
        self.assertFalse(session.is_active)
        self.assertFalse(session.is_valid)
    
    def test_get_valid_session(self):
        """Test getting valid session"""
        session = PatientPortalSession.create_session(
            email=self.patient.email,
            patient=self.patient
        )
        
        # Valid session
        retrieved = PatientPortalSession.get_valid_session(session.session_key)
        self.assertEqual(retrieved, session)
        
        # Invalid session key
        retrieved = PatientPortalSession.get_valid_session('invalid-key')
        self.assertIsNone(retrieved)


class PatientPortalViewsTest(TestCase):
    """Test patient portal views"""
    
    def setUp(self):
        self.client = Client()
        self.patient = Patient.objects.create(
            first_name='Jane',
            last_name='Smith',
            email='jane@example.com',
            contact_number='+639123456789'
        )
        
        # Create service for appointments
        self.service = Service.objects.create(
            name='Dental Cleaning',
            min_price=500,
            max_price=1000
        )
        
        # Create daily slots
        tomorrow = timezone.now().date() + timedelta(days=1)
        DailySlots.objects.create(
            date=tomorrow,
            am_slots=6,
            pm_slots=8
        )
        
        # Create appointment
        self.appointment = Appointment.objects.create(
            patient=self.patient,
            service=self.service,
            appointment_date=tomorrow,
            period='AM',
            status='confirmed'
        )
    
    def test_login_page_loads(self):
        """Test portal login page loads"""
        response = self.client.get(reverse('patient_portal:login'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Patient Portal')
    
    def test_request_verification_code(self):
        """Test requesting verification code"""
        response = self.client.post(
            reverse('patient_portal:login'),
            {'email': self.patient.email}
        )
        
        self.assertEqual(response.status_code, 302)  # Redirect to verify
        self.assertTrue(
            PatientPortalAccess.objects.filter(email=self.patient.email).exists()
        )
    
    def test_invalid_email_login(self):
        """Test login with non-existent email"""
        response = self.client.post(
            reverse('patient_portal:login'),
            {'email': 'nonexistent@example.com'}
        )
        
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No patient record found')
    
    def test_verify_code_access_without_email(self):
        """Test accessing verify page without requesting code"""
        response = self.client.get(reverse('patient_portal:verify_code'))
        
        self.assertEqual(response.status_code, 302)  # Redirect to login
    
    def test_dashboard_requires_authentication(self):
        """Test dashboard requires authentication"""
        response = self.client.get(reverse('patient_portal:dashboard'))
        
        self.assertEqual(response.status_code, 302)  # Redirect to login


class EmailServiceTest(TestCase):
    """Test email service functionality"""
    
    def setUp(self):
        self.patient = Patient.objects.create(
            first_name='Test',
            last_name='Patient',
            email='test@example.com'
        )
        
        self.service = Service.objects.create(
            name='Test Service',
            min_price=500,
            max_price=1000
        )
        
        tomorrow = timezone.now().date() + timedelta(days=1)
        DailySlots.objects.create(date=tomorrow, am_slots=6, pm_slots=8)
        
        self.appointment = Appointment.objects.create(
            patient=self.patient,
            service=self.service,
            appointment_date=tomorrow,
            period='AM',
            status='pending'
        )
    
    def test_email_service_import(self):
        """Test that email service can be imported"""
        from core.email_service import EmailService
        self.assertIsNotNone(EmailService)
    
    def test_email_methods_exist(self):
        """Test that all email methods exist"""
        from core.email_service import EmailService
        
        self.assertTrue(hasattr(EmailService, 'send_appointment_approved_email'))
        self.assertTrue(hasattr(EmailService, 'send_appointment_rejected_email'))
        self.assertTrue(hasattr(EmailService, 'send_appointment_cancelled_email'))
        self.assertTrue(hasattr(EmailService, 'send_verification_code_email'))


class AppointmentCancellationTest(TestCase):
    """Test appointment cancellation from portal"""
    
    def setUp(self):
        self.client = Client()
        self.patient = Patient.objects.create(
            first_name='Cancel',
            last_name='Test',
            email='cancel@example.com'
        )
        
        self.service = Service.objects.create(
            name='Test Service',
            min_price=500,
            max_price=1000
        )
        
        # Create appointment 2 days in future (can be cancelled)
        future_date = timezone.now().date() + timedelta(days=2)
        DailySlots.objects.create(date=future_date, am_slots=6, pm_slots=8)
        
        self.appointment = Appointment.objects.create(
            patient=self.patient,
            service=self.service,
            appointment_date=future_date,
            period='AM',
            status='confirmed'
        )
        
        # Create portal session
        self.session = PatientPortalSession.create_session(
            email=self.patient.email,
            patient=self.patient
        )
        
        # Set session in client
        session = self.client.session
        session['portal_session_key'] = self.session.session_key
        session['portal_patient_id'] = self.patient.id
        session.save()
    
    def test_cancel_appointment_from_portal(self):
        """Test cancelling appointment from portal"""
        response = self.client.post(
            reverse('patient_portal:cancel_appointment', args=[self.appointment.id])
        )
        
        # Refresh appointment from database
        self.appointment.refresh_from_db()
        
        self.assertEqual(self.appointment.status, 'cancelled')
        self.assertEqual(response.status_code, 302)  # Redirect
    
    def test_cannot_cancel_past_appointment(self):
        """Test cannot cancel appointment within 24 hours"""
        # Create appointment tomorrow (within 24 hours)
        tomorrow = timezone.now().date() + timedelta(days=1)
        DailySlots.objects.create(date=tomorrow, am_slots=6, pm_slots=8)
        
        past_appointment = Appointment.objects.create(
            patient=self.patient,
            service=self.service,
            appointment_date=tomorrow,
            period='AM',
            status='confirmed'
        )
        
        response = self.client.post(
            reverse('patient_portal:cancel_appointment', args=[past_appointment.id])
        )
        
        # Refresh appointment
        past_appointment.refresh_from_db()
        
        # Should still be confirmed
        self.assertEqual(past_appointment.status, 'confirmed')