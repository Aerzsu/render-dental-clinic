# patient_portal/management/commands/cleanup_portal_data.py
"""
Management command to clean up expired portal access codes and sessions
Run daily via cron: python manage.py cleanup_portal_data
"""
from django.core.management.base import BaseCommand
from patient_portal.models import PatientPortalAccess, PatientPortalSession


class Command(BaseCommand):
    help = 'Clean up expired patient portal access codes and sessions'

    def handle(self, *args, **options):
        # Clean up expired access codes
        deleted_codes = PatientPortalAccess.cleanup_expired_codes()
        self.stdout.write(
            self.style.SUCCESS(f'Deleted {deleted_codes} expired access codes')
        )
        
        # Clean up expired sessions
        deleted_sessions = PatientPortalSession.cleanup_expired_sessions()
        self.stdout.write(
            self.style.SUCCESS(f'Deleted {deleted_sessions} expired sessions')
        )
        
        self.stdout.write(
            self.style.SUCCESS('Portal data cleanup completed successfully')
        )