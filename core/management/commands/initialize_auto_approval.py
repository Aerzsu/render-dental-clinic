from django.core.management.base import BaseCommand
from core.models import SystemSetting


class Command(BaseCommand):
    help = 'Initialize auto-approval system settings'

    def handle(self, *args, **options):
        self.stdout.write('Initializing auto-approval settings...')
        
        SystemSetting.initialize_auto_approval_settings()
        
        self.stdout.write(self.style.SUCCESS('✓ Auto-approval settings initialized'))
        self.stdout.write('\nDefault settings:')
        self.stdout.write('  • Auto-approval: Disabled (can be enabled in System Settings)')
        self.stdout.write('  • Require existing patients: Yes')