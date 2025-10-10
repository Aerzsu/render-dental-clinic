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
python manage.py migrate

# Create default roles if they don't exist
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

# Initialize slot system if needed
python manage.py initialize_slot_system || true

echo "Build completed successfully!"