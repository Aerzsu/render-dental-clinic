# patient_portal/management/commands/test_email.py
from django.core.management.base import BaseCommand
from django.core.mail import send_mail
from django.conf import settings


class Command(BaseCommand):
    help = 'Test email configuration'

    def handle(self, *args, **options):
        try:
            send_mail(
                subject='Test Email from Dental Clinic',
                message='This is a test email.',
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=['aerzsuu@gmail.com'],  # Change this
                fail_silently=False,
            )
            self.stdout.write(self.style.SUCCESS('Email sent successfully!'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Email failed: {str(e)}'))