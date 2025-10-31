# Generated migration file
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('appointments', '0006_add_reschedule_token'),
    ]

    operations = [
        migrations.AddField(
            model_name='appointment',
            name='arrived_at',
            field=models.DateTimeField(
                blank=True,
                null=True,
                help_text='Timestamp when patient checked in/arrived'
            ),
        ),
        migrations.AddIndex(
            model_name='appointment',
            index=models.Index(fields=['arrived_at'], name='appt_arrived_at_idx'),
        ),
    ]