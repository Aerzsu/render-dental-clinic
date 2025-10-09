# patient_portal/admin.py
from django.contrib import admin
from .models import PatientPortalAccess, PatientPortalSession


@admin.register(PatientPortalAccess)
class PatientPortalAccessAdmin(admin.ModelAdmin):
    list_display = ['email', 'code', 'created_at', 'expires_at', 'is_used', 'is_expired']
    list_filter = ['is_used', 'created_at']
    search_fields = ['email', 'code']
    readonly_fields = ['created_at', 'used_at']
    date_hierarchy = 'created_at'
    
    def is_expired(self, obj):
        return obj.is_expired
    is_expired.boolean = True


@admin.register(PatientPortalSession)
class PatientPortalSessionAdmin(admin.ModelAdmin):
    list_display = ['email', 'patient', 'created_at', 'last_activity', 'expires_at', 'is_active', 'is_expired']
    list_filter = ['is_active', 'created_at']
    search_fields = ['email', 'session_key', 'patient__first_name', 'patient__last_name']
    readonly_fields = ['created_at', 'last_activity']
    date_hierarchy = 'created_at'
    
    def is_expired(self, obj):
        return obj.is_expired
    is_expired.boolean = True