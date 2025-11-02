# appointments/migrations/0XXX_add_payment_lock_fields.py
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('appointments', '0007_add_arrived_at_field'),
    ]

    operations = [
        migrations.AddField(
            model_name='payment',
            name='is_locked',
            field=models.BooleanField(
                default=False,
                help_text='Invoice is locked after first payment to prevent accidental modifications'
            ),
        ),
        migrations.AddField(
            model_name='payment',
            name='locked_at',
            field=models.DateTimeField(
                blank=True,
                null=True,
                help_text='Timestamp when invoice was locked'
            ),
        ),
        migrations.AddField(
            model_name='payment',
            name='locked_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='locked_payments',
                to=settings.AUTH_USER_MODEL,
                help_text='User who triggered the lock (via payment or manual action)'
            ),
        ),
        migrations.AddField(
            model_name='payment',
            name='lock_reason',
            field=models.CharField(
                blank=True,
                max_length=255,
                default='',
                help_text='Reason for locking (e.g., "first_payment_received", "manual_lock")'
            ),
        ),
        migrations.AddField(
            model_name='payment',
            name='invoice_sent_at',
            field=models.DateTimeField(
                blank=True,
                null=True,
                help_text='Timestamp when invoice was first emailed to patient'
            ),
        ),
        migrations.AddField(
            model_name='payment',
            name='invoice_download_count',
            field=models.PositiveIntegerField(
                default=0,
                help_text='Number of times invoice PDF was downloaded'
            ),
        ),
    ]