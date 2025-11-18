#!/usr/bin/env bash
# exit on error
set -o errexit

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Create necessary directories
mkdir -p logs
mkdir -p media/treatment_files

# Collect static files
python manage.py collectstatic --no-input

# Run migrations
echo "Running migrations..."
python manage.py migrate

# Initialize system settings
echo "Initializing system settings..."
python manage.py initialize_settings

# Create default roles if they don't exist
echo "Creating default roles..."
python manage.py shell << EOF
from users.models import Role
from django.db import IntegrityError

roles = ['Admin', 'Dentist', 'Staff']
for role_name in roles:
    try:
        role, created = Role.objects.get_or_create(
            name=role_name,
            defaults={
                'description': f'{role_name} role with default permissions'
            }
        )
        if created:
            print(f'Created role: {role_name}')
        else:
            print(f'Role already exists: {role_name}')
    except Exception as e:
        print(f'Error creating role {role_name}: {e}')
EOF

# Create superuser if it doesn't exist
echo "Creating superuser..."
python manage.py shell << EOF
from django.contrib.auth import get_user_model
import os

User = get_user_model()
username = os.getenv('ADMIN_USERNAME', 'kingjoyadmin')
email = os.getenv('ADMIN_EMAIL', 'admin@kingjoydental.site')
password = os.getenv('ADMIN_PASSWORD')

if password:
    if not User.objects.filter(username=username).exists():
        User.objects.create_superuser(username, email, password)
        print(f'Created superuser: {username}')
    else:
        print(f'Superuser already exists: {username}')
else:
    print('Warning: ADMIN_PASSWORD not set - superuser creation skipped')
EOF