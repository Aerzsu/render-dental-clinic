#core/urls.py
from django.urls import path
from . import views
from appointments import views as appointment_views
from core.views import BookAppointmentView
from .views import ThemeToggleView

app_name = 'core'

urlpatterns = [
    # Public pages
    path('', views.HomeView.as_view(), name='home'),
    path('book-appointment/', BookAppointmentView.as_view(), name='book_appointment'),
    # Authenticated pages
    path('theme/toggle/', ThemeToggleView.as_view(), name='theme_toggle'),
    path('dashboard/', views.DashboardView.as_view(), name='dashboard'),
    
    # Maintenance module
    path('maintenance/', views.MaintenanceHubView.as_view(), name='maintenance_hub'),
    
    # Audit logs
    path('audit-logs/', views.AuditLogListView.as_view(), name='audit_logs'),
    
    # System settings
    path('maintenance/settings/', views.SystemSettingsView.as_view(), name='settings'),

    # Booking OTP endpoints
    path('api/booking/send-otp/', views.send_booking_otp, name='send_booking_otp'),
    path('api/booking/verify-otp/', views.verify_booking_otp, name='verify_booking_otp'),
    path('api/booking/select-patient/', views.select_booking_patient, name='select_booking_patient'),
    path('api/booking/submit/', views.submit_booking_appointment, name='submit_booking_appointment'),  # NEW
]