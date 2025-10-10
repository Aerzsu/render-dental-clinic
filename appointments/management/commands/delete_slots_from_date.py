# appointments/management/commands/delete_slots_from_date.py
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import datetime
from appointments.models import DailySlots


class Command(BaseCommand):
    help = 'Delete all daily slots from a specified date onwards'

    def add_arguments(self, parser):
        parser.add_argument(
            '--date',
            type=str,
            default='2026-01-01',
            help='Delete slots from this date onwards (format: YYYY-MM-DD). Default: 2026-01-01'
        )
        parser.add_argument(
            '--confirm',
            action='store_true',
            help='Confirm deletion without prompting (use with caution)'
        )

    def handle(self, *args, **options):
        date_str = options['date']
        
        try:
            delete_from_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            self.stdout.write(
                self.style.ERROR(f'Invalid date format: {date_str}. Use YYYY-MM-DD')
            )
            return

        # Count slots to be deleted
        slots_to_delete = DailySlots.objects.filter(date__gte=delete_from_date)
        count = slots_to_delete.count()

        if count == 0:
            self.stdout.write(
                self.style.WARNING(f'No slots found from {date_str} onwards.')
            )
            return

        # Show confirmation
        self.stdout.write(
            self.style.WARNING(
                f'\n⚠️  WARNING: This will delete {count} slot records from {date_str} onwards.\n'
            )
        )

        # Show date range
        earliest = slots_to_delete.order_by('date').first()
        latest = slots_to_delete.order_by('-date').first()
        
        if earliest and latest:
            self.stdout.write(f'Date range: {earliest.date} to {latest.date}')
            self.stdout.write(f'Total slots to delete: {count}\n')

        # Prompt for confirmation
        if not options['confirm']:
            confirm = input('Are you sure you want to delete these slots? (yes/no): ').strip().lower()
            if confirm != 'yes':
                self.stdout.write(self.style.WARNING('Deletion cancelled.'))
                return

        # Perform deletion
        try:
            deleted_count, _ = slots_to_delete.delete()
            self.stdout.write(
                self.style.SUCCESS(
                    f'\n✅ Successfully deleted {deleted_count} slot records from {date_str} onwards.'
                )
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Error deleting slots: {str(e)}')
            )