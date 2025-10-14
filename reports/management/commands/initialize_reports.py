# reports/management/commands/initialize_reports.py
from django.core.management.base import BaseCommand
from core.models import SystemSetting


class Command(BaseCommand):
    help = 'Initialize default settings for reports module'
    
    def handle(self, *args, **options):
        settings_to_create = [
            {
                'key': 'reports_default_date_range',
                'value': 'last_30_days',
                'description': 'Default date range for reports (today, yesterday, last_7_days, last_30_days, custom)'
            },
            {
                'key': 'reports_top_services_limit',
                'value': '10',
                'description': 'Number of top services to display in analytics'
            },
            {
                'key': 'reports_top_discounts_limit',
                'value': '5',
                'description': 'Number of top discounts to display in analytics'
            },
            {
                'key': 'clinic_name',
                'value': 'KingJoy Dental Clinic',
                'description': 'Clinic name for reports and documents'
            },
            {
                'key': 'clinic_address',
                'value': '54 Obanic St.\nQuezon City, Metro Manila',
                'description': 'Clinic address for reports and documents'
            },
            {
                'key': 'clinic_phone',
                'value': '+63 956 631 6581',
                'description': 'Clinic phone number for reports and documents'
            },
            {
                'key': 'clinic_email',
                'value': 'contact@kingjoydental.com',
                'description': 'Clinic email for reports and documents'
            },
        ]
        
        created_count = 0
        updated_count = 0
        
        for setting_data in settings_to_create:
            setting, created = SystemSetting.objects.get_or_create(
                key=setting_data['key'],
                defaults={
                    'value': setting_data['value'],
                    'description': setting_data['description'],
                    'is_active': True
                }
            )
            
            if created:
                created_count += 1
                self.stdout.write(
                    self.style.SUCCESS(f"✓ Created setting: {setting_data['key']}")
                )
            else:
                if not setting.description:
                    setting.description = setting_data['description']
                    setting.save()
                    updated_count += 1
                    self.stdout.write(
                        self.style.WARNING(f"↻ Updated setting: {setting_data['key']}")
                    )
                else:
                    self.stdout.write(
                        self.style.NOTICE(f"- Setting already exists: {setting_data['key']}")
                    )
        
        self.stdout.write(
            self.style.SUCCESS(
                f"\nReports initialization complete! Created: {created_count}, Updated: {updated_count}"
            )
        )