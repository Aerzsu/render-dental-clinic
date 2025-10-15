# appointments/management/commands/delete_daily_slots.py
"""
Management command to delete daily slots for specific date(s)
Useful for cleaning up incorrectly created slots or closing clinic for specific days

Usage:
    # Delete slots for a single date
    python manage.py delete_daily_slots --date 2025-10-20
    
    # Delete slots for a date range
    python manage.py delete_daily_slots --start-date 2025-10-20 --end-date 2025-10-25
    
    # Delete all slots for a specific month
    python manage.py delete_daily_slots --month 2025-11
    
    # Dry run (preview what would be deleted)
    python manage.py delete_daily_slots --date 2025-10-20 --dry-run
    
    # Force delete without confirmation
    python manage.py delete_daily_slots --date 2025-10-20 --force
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from appointments.models import DailySlots, Appointment
from datetime import datetime, timedelta
import sys


class Command(BaseCommand):
    help = 'Delete daily slots for specific date(s). CAUTION: This will affect appointment bookings!'

    def add_arguments(self, parser):
        # Single date option
        parser.add_argument(
            '--date',
            type=str,
            help='Delete slots for a specific date (YYYY-MM-DD format)'
        )
        
        # Date range options
        parser.add_argument(
            '--start-date',
            type=str,
            help='Start date for range deletion (YYYY-MM-DD format)'
        )
        parser.add_argument(
            '--end-date',
            type=str,
            help='End date for range deletion (YYYY-MM-DD format)'
        )
        
        # Month option
        parser.add_argument(
            '--month',
            type=str,
            help='Delete all slots for a specific month (YYYY-MM format)'
        )
        
        # Safety options
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be deleted without actually deleting'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Skip confirmation prompt'
        )
        parser.add_argument(
            '--check-appointments',
            action='store_true',
            default=True,
            help='Check for existing appointments before deleting (default: True)'
        )

    def handle(self, *args, **options):
        # Parse options
        single_date = options.get('date')
        start_date = options.get('start_date')
        end_date = options.get('end_date')
        month = options.get('month')
        dry_run = options.get('dry_run')
        force = options.get('force')
        check_appointments = options.get('check_appointments')
        
        # Validate input
        if not any([single_date, (start_date and end_date), month]):
            raise CommandError(
                'You must provide one of: --date, --start-date with --end-date, or --month'
            )
        
        if single_date and (start_date or end_date):
            raise CommandError('Cannot use --date with --start-date/--end-date')
        
        if (start_date and not end_date) or (end_date and not start_date):
            raise CommandError('Both --start-date and --end-date must be provided')
        
        # Determine date range
        try:
            if single_date:
                date_obj = datetime.strptime(single_date, '%Y-%m-%d').date()
                dates_to_delete = [date_obj]
                operation_desc = f"date {single_date}"
                
            elif start_date and end_date:
                start = datetime.strptime(start_date, '%Y-%m-%d').date()
                end = datetime.strptime(end_date, '%Y-%m-%d').date()
                
                if start > end:
                    raise CommandError('Start date must be before or equal to end date')
                
                dates_to_delete = []
                current = start
                while current <= end:
                    dates_to_delete.append(current)
                    current += timedelta(days=1)
                
                operation_desc = f"date range {start_date} to {end_date}"
                
            elif month:
                try:
                    year, month_num = month.split('-')
                    year = int(year)
                    month_num = int(month_num)
                    
                    if month_num < 1 or month_num > 12:
                        raise ValueError('Month must be between 1 and 12')
                    
                    # Get first and last day of month
                    start = datetime(year, month_num, 1).date()
                    if month_num == 12:
                        end = datetime(year + 1, 1, 1).date() - timedelta(days=1)
                    else:
                        end = datetime(year, month_num + 1, 1).date() - timedelta(days=1)
                    
                    dates_to_delete = []
                    current = start
                    while current <= end:
                        dates_to_delete.append(current)
                        current += timedelta(days=1)
                    
                    operation_desc = f"month {month}"
                    
                except ValueError as e:
                    raise CommandError(f'Invalid month format. Use YYYY-MM: {str(e)}')
        
        except ValueError:
            raise CommandError('Invalid date format. Use YYYY-MM-DD')
        
        # Get slots to delete
        slots_to_delete = DailySlots.objects.filter(date__in=dates_to_delete)
        count = slots_to_delete.count()
        
        if count == 0:
            self.stdout.write(self.style.WARNING(f'No slots found for {operation_desc}'))
            return
        
        # Display what will be deleted
        self.stdout.write(self.style.WARNING(f'\n{"="*70}'))
        self.stdout.write(self.style.WARNING(f'DELETION SUMMARY FOR {operation_desc.upper()}'))
        self.stdout.write(self.style.WARNING(f'{"="*70}\n'))
        
        self.stdout.write(f'Total slots to delete: {count}')
        self.stdout.write('')
        
        # Show details for each date
        for slot in slots_to_delete:
            self.stdout.write(f'  • {slot.date} - AM: {slot.am_slots}, PM: {slot.pm_slots}')
            
            # Check for appointments if requested
            if check_appointments:
                appointments = Appointment.objects.filter(
                    appointment_date=slot.date,
                    status__in=['pending', 'confirmed']
                )
                appt_count = appointments.count()
                
                if appt_count > 0:
                    self.stdout.write(
                        self.style.ERROR(f'    ⚠️  WARNING: {appt_count} active appointment(s) exist for this date!')
                    )
                    for appt in appointments:
                        self.stdout.write(
                            f'       - {appt.patient_name} ({appt.period}) - Status: {appt.status}'
                        )
        
        self.stdout.write('')
        
        # Dry run mode
        if dry_run:
            self.stdout.write(self.style.SUCCESS('DRY RUN MODE - No changes made'))
            return
        
        # Check for appointments that would be affected
        if check_appointments:
            total_appointments = Appointment.objects.filter(
                appointment_date__in=dates_to_delete,
                status__in=['pending', 'confirmed']
            ).count()
            
            if total_appointments > 0:
                self.stdout.write(
                    self.style.ERROR(
                        f'\n⚠️  DANGER: {total_appointments} active appointment(s) exist for these dates!'
                    )
                )
                self.stdout.write(
                    self.style.ERROR(
                        'Deleting slots will not delete appointments, but may cause booking conflicts.'
                    )
                )
                self.stdout.write('')
                
                if not force:
                    response = input('Do you want to continue anyway? Type "DELETE" to confirm: ')
                    if response != 'DELETE':
                        self.stdout.write(self.style.SUCCESS('Operation cancelled'))
                        return
        
        # Final confirmation
        if not force:
            self.stdout.write(self.style.WARNING('\nThis action cannot be undone!'))
            response = input(f'Type "DELETE" to confirm deletion of {count} slot(s): ')
            
            if response != 'DELETE':
                self.stdout.write(self.style.SUCCESS('Operation cancelled'))
                return
        
        # Perform deletion
        try:
            with transaction.atomic():
                deleted_count, _ = slots_to_delete.delete()
                
                self.stdout.write('')
                self.stdout.write(
                    self.style.SUCCESS(f'✓ Successfully deleted {deleted_count} daily slot(s)')
                )
                
                # Log the deletion
                self.stdout.write(f'\nDeleted slots for {operation_desc}')
                
        except Exception as e:
            raise CommandError(f'Error deleting slots: {str(e)}')


# Additional helper command for listing slots
class ListSlotsCommand(BaseCommand):
    """
    Separate command to just view slots without deleting
    Usage: python manage.py list_daily_slots --month 2025-10
    """
    help = 'List daily slots for specific date range'
    
    def add_arguments(self, parser):
        parser.add_argument('--date', type=str, help='Single date (YYYY-MM-DD)')
        parser.add_argument('--month', type=str, help='Month (YYYY-MM)')
        parser.add_argument('--start-date', type=str, help='Start date')
        parser.add_argument('--end-date', type=str, help='End date')
    
    def handle(self, *args, **options):
        # Similar date parsing logic as above
        # But just display, don't delete
        pass