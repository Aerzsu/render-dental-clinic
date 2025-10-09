# patient_portal/urls.py
from django.urls import path
from . import views

app_name = 'patient_portal'

urlpatterns = [
    path('', views.PatientPortalLoginView.as_view(), name='login'),
    path('verify/', views.PatientPortalVerifyView.as_view(), name='verify_code'),
    path('dashboard/', views.PatientPortalDashboardView.as_view(), name='dashboard'),
    path('appointments/', views.PatientPortalAppointmentsView.as_view(), name='appointments'),
    path('billing/', views.PatientPortalBillingView.as_view(), name='billing'),
    path('appointments/<int:appointment_id>/cancel/', views.cancel_appointment_view, name='cancel_appointment'),
    path('logout/', views.logout_view, name='logout'),
]