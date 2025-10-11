from django.core.management.base import BaseCommand
from core.models import SystemSetting


class Command(BaseCommand):
    help = 'Initialize default system settings'

    def handle(self, *args, **options):
        settings_data = {
            'clinic_name': 'KingJoy Dental Clinic',
            'clinic_tagline': 'Quality Dental Care',
            'clinic_phone': '+63 956 631 6581',
            'clinic_email': 'papatmyfrend@gmail.com',
            'clinic_address': '54 Obanic St.\nQuezon City, Metro Manila',
            'clinic_hours': 'Monday - Saturday: 10:00 AM - 6:00 PM\nSunday: Closed',
            'am_period_display': '8:00 AM - 12:00 PM',
            'pm_period_display': '1:00 PM - 6:00 PM',
            'google_maps_embed': 'https://www.google.com/maps/embed?pb=!1m18!1m12!1m3!1d3859.2044935183562!2d121.08163467390081!3d14.701024674612498!2m3!1f0!2f0!3f0!3m2!1i1024!2i768!4f13.1!3m3!1m2!1s0x3397bbf97696c125%3A0x160a3affaaccc63f!2sKingJoy%20Dental%20Clinic!5e0!3m2!1sen!2sph!4v1755631445873!5m2!1sen!2sph',
        }
        
        created_count = 0
        skipped_count = 0
        
        for key, value in settings_data.items():
            setting, created = SystemSetting.objects.get_or_create(
                key=key,
                defaults={
                    'value': value,
                    'is_active': True,
                    'description': f'System setting for {key}'
                }
            )
            
            if created:
                created_count += 1
                self.stdout.write(self.style.SUCCESS(f'✓ Created setting: {key}'))
            else:
                skipped_count += 1
                # Only show this in verbose mode to keep logs clean
                if options.get('verbosity', 1) >= 2:
                    self.stdout.write(self.style.WARNING(f'⚠ Already exists: {key}'))
        
        # Summary message
        if created_count > 0:
            self.stdout.write(self.style.SUCCESS(
                f'\n✓ Settings initialization complete: {created_count} created, {skipped_count} already existed'
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f'✓ All settings already initialized ({skipped_count} settings)'
            ))