from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from users.models import Role
from services.models import Service, Discount
from core.models import SystemSetting
from decimal import Decimal

User = get_user_model()

class Command(BaseCommand):
    help = 'Set up initial data for the dental clinic system'
    
    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Setting up initial data...'))
        
        # Create default roles
        self.create_default_roles()
        
        # Create admin user if not exists
        self.create_admin_user()
        
        # Create default services
        self.create_default_services()
        
        # Create default discounts
        self.create_default_discounts()
        
        # Create system settings
        self.create_system_settings()
        
        self.stdout.write(self.style.SUCCESS('Initial data setup completed!'))
    
    def create_default_roles(self):
        """Create default roles with permissions"""
        self.stdout.write('Creating default roles...')
        
        roles_data = [
            {
                'name': 'admin',
                'display_name': 'Administrator',
                'description': 'Full system access',
                'permissions': {
                    'dashboard': True,
                    'appointments': True,
                    'patients': True,
                    'billing': True,
                    'reports': True,
                    'maintenance': True,
                },
                'is_default': True,
            },
            {
                'name': 'dentist',
                'display_name': 'Dentist',
                'description': 'Dentist with patient and appointment management',
                'permissions': {
                    'dashboard': True,
                    'appointments': True,
                    'patients': True,
                    'billing': True,
                    'reports': False,
                    'maintenance': False,
                },
                'is_default': True,
            },
            {
                'name': 'staff',
                'display_name': 'Staff',
                'description': 'Reception staff with limited access',
                'permissions': {
                    'dashboard': True,
                    'appointments': True,
                    'patients': True,
                    'billing': False,
                    'reports': False,
                    'maintenance': False,
                },
                'is_default': True,
            }
        ]
        
        for role_data in roles_data:
            role, created = Role.objects.get_or_create(
                name=role_data['name'],
                defaults=role_data
            )
            if created:
                self.stdout.write(f'  ✓ Created role: {role.display_name}')
            else:
                self.stdout.write(f'  - Role already exists: {role.display_name}')
    
    def create_admin_user(self):
        """Create default admin user"""
        self.stdout.write('Creating admin user...')
        
        admin_role = Role.objects.get(name='admin')
        
        if not User.objects.filter(username='admin').exists():
            admin_user = User.objects.create_superuser(
                username='admin',
                email='admin@dentalclinic.com',
                password='admin123',
                first_name='System',
                last_name='Administrator',
                role=admin_role
            )
            self.stdout.write(f'  ✓ Created admin user: {admin_user.username}')
            self.stdout.write(f'    Username: admin')
            self.stdout.write(f'    Password: admin123')
            self.stdout.write(f'    Please change this password after first login!')
        else:
            self.stdout.write(f'  - Admin user already exists')
    
    def create_default_services(self):
        """Create default dental services"""
        self.stdout.write('Creating default services...')
        
        services_data = [
            {
                'name': 'General Checkup',
                'description': 'Routine dental examination and cleaning',
                'min_price': Decimal('500.00'),
                'max_price': Decimal('800.00'),
                'duration_minutes': 30,
            },
            {
                'name': 'Teeth Cleaning',
                'description': 'Professional teeth cleaning and oral prophylaxis',
                'min_price': Decimal('800.00'),
                'max_price': Decimal('1200.00'),
                'duration_minutes': 60,
            },
            {
                'name': 'Tooth Filling',
                'description': 'Dental restoration using composite or amalgam filling',
                'min_price': Decimal('1500.00'),
                'max_price': Decimal('3000.00'),
                'duration_minutes': 60,
            },
            {
                'name': 'Tooth Extraction',
                'description': 'Simple or surgical tooth extraction',
                'min_price': Decimal('2000.00'),
                'max_price': Decimal('5000.00'),
                'duration_minutes': 90,
            },
            {
                'name': 'Root Canal Treatment',
                'description': 'Endodontic treatment for infected or damaged tooth pulp',
                'min_price': Decimal('8000.00'),
                'max_price': Decimal('15000.00'),
                'duration_minutes': 120,
            },
            {
                'name': 'Dental Crown',
                'description': 'Protective cap placed over damaged tooth',
                'min_price': Decimal('10000.00'),
                'max_price': Decimal('20000.00'),
                'duration_minutes': 90,
            },
            {
                'name': 'Teeth Whitening',
                'description': 'Professional teeth whitening treatment',
                'min_price': Decimal('5000.00'),
                'max_price': Decimal('8000.00'),
                'duration_minutes': 60,
            },
            {
                'name': 'Dental X-Ray',
                'description': 'Radiographic examination of teeth and jaw',
                'min_price': Decimal('300.00'),
                'max_price': Decimal('800.00'),
                'duration_minutes': 30,
            },
        ]
        
        for service_data in services_data:
            service, created = Service.objects.get_or_create(
                name=service_data['name'],
                defaults=service_data
            )
            if created:
                self.stdout.write(f'  ✓ Created service: {service.name}')
            else:
                self.stdout.write(f'  - Service already exists: {service.name}')
    
    def create_default_discounts(self):
        """Create default discount options"""
        self.stdout.write('Creating default discounts...')
        
        discounts_data = [
            {
                'name': 'Senior Citizen',
                'amount': Decimal('20.00'),
                'is_percentage': True,
            },
            {
                'name': 'PWD Discount',
                'amount': Decimal('20.00'),
                'is_percentage': True,
            },
            {
                'name': 'Student Discount',
                'amount': Decimal('10.00'),
                'is_percentage': True,
            },
            {
                'name': 'Family Package',
                'amount': Decimal('15.00'),
                'is_percentage': True,
            },
            {
                'name': 'New Patient Promo',
                'amount': Decimal('500.00'),
                'is_percentage': False,
            },
        ]
        
        for discount_data in discounts_data:
            discount, created = Discount.objects.get_or_create(
                name=discount_data['name'],
                defaults=discount_data
            )
            if created:
                self.stdout.write(f'  ✓ Created discount: {discount.name} ({discount.display_value})')
            else:
                self.stdout.write(f'  - Discount already exists: {discount.name}')
    
    def create_system_settings(self):
        """Create default system settings"""
        self.stdout.write('Creating system settings...')
        
        settings_data = [
            {
                'key': 'clinic_name',
                'value': 'Dental Clinic Management System',
                'description': 'Name of the dental clinic',
            },
            {
                'key': 'clinic_address',
                'value': '123 Main Street, Quezon City, Metro Manila, Philippines',
                'description': 'Clinic address',
            },
            {
                'key': 'clinic_phone',
                'value': '+63 2 1234 5678',
                'description': 'Clinic contact number',
            },
            {
                'key': 'clinic_email',
                'value': 'info@dentalclinic.com',
                'description': 'Clinic email address',
            },
            {
                'key': 'clinic_hours',
                'value': 'Monday to Saturday: 10:00 AM - 6:00 PM',
                'description': 'Clinic operating hours',
            },
            {
                'key': 'appointment_advance_booking_days',
                'value': '30',
                'description': 'Number of days in advance patients can book appointments',
            },
            {
                'key': 'appointment_cancellation_hours',
                'value': '24',
                'description': 'Minimum hours before appointment for cancellation',
            },
        ]
        
        for setting_data in settings_data:
            setting, created = SystemSetting.objects.get_or_create(
                key=setting_data['key'],
                defaults=setting_data
            )
            if created:
                self.stdout.write(f'  ✓ Created setting: {setting.key}')
            else:
                self.stdout.write(f'  - Setting already exists: {setting.key}')