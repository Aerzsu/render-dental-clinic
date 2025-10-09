# patient_portal/__init__.py
default_app_config = 'patient_portal.apps.PatientPortalConfig'


# patient_portal/apps.py
from django.apps import AppConfig


class PatientPortalConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'patient_portal'
    verbose_name = 'Patient Portal'