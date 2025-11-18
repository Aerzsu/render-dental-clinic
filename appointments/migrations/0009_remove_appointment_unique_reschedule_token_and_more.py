from django.db import migrations, models


def infer_auto_approvals(apps, schema_editor):
    """
    Infer auto-approvals from existing data
    Mark appointments as auto-approved if confirmed_by is a superuser
    """
    Appointment = apps.get_model('appointments', 'Appointment')
    User = apps.get_model('users', 'User')
    
    # Get all superusers (system users)
    system_users = User.objects.filter(is_superuser=True).values_list('id', flat=True)
    
    # Mark appointments confirmed by system users as auto-approved
    updated = Appointment.objects.filter(
        confirmed_by_id__in=system_users,
        status='confirmed'
    ).update(is_auto_approved=True)
    
    print(f"Marked {updated} existing appointments as auto-approved")


class Migration(migrations.Migration):

    dependencies = [
        ('appointments', '0008_add_payment_lock_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='appointment',
            name='is_auto_approved',
            field=models.BooleanField(default=False, help_text='Whether this appointment was automatically approved by the system'),
        ),
        migrations.RunPython(infer_auto_approvals, reverse_code=migrations.RunPython.noop),
    ]