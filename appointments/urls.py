# appointments/urls.py - Updated with timeslot system endpoints
from django.urls import path
from . import views, payment_views

app_name = 'appointments'

urlpatterns = [
    # Main appointment views (BACKEND - for staff/admin)
    path('', views.AppointmentListView.as_view(), name='appointment_list'),
    path('calendar/', views.AppointmentCalendarView.as_view(), name='appointment_calendar'),
    path('requests/', views.AppointmentRequestsView.as_view(), name='appointment_requests'),
    path('requests/partial/', views.appointment_requests_partial, name='appointment_requests_partial'),
    
    # Appointment CRUD (BACKEND)
    path('create/', views.AppointmentCreateView.as_view(), name='appointment_create'),
    path('<int:pk>/', views.AppointmentDetailView.as_view(), name='appointment_detail'),
    path('<int:pk>/edit/', views.AppointmentUpdateView.as_view(), name='appointment_update'),
    
    # Appointment actions (BACKEND)
    path('<int:pk>/approve/', views.approve_appointment, name='approve_appointment'),
    path('<int:pk>/reject/', views.reject_appointment, name='reject_appointment'),
    path('appointment/<int:pk>/update-status/', views.update_appointment_status, name='update_appointment_status'),

    # Appointment notes (BACKEND)
    path('notes/<int:appointment_pk>/update/', views.update_appointment_note, name='appointment_note_update'),
    path('notes/<int:appointment_pk>/get/', views.get_appointment_notes, name='appointment_notes_get'),
    
    # TimeSlot Configuration Management (BACKEND)
    path('timeslots/', views.TimeSlotConfigurationListView.as_view(), name='daily_slots_list'),
    path('timeslots/create/', views.TimeSlotConfigurationCreateView.as_view(), name='daily_slots_create'),
    path('timeslots/<int:pk>/edit/', views.TimeSlotConfigurationUpdateView.as_view(), name='daily_slots_update'),
    path('timeslots/bulk-preview/', views.bulk_create_timeslot_configs_preview, name='bulk_create_preview'),
    path('timeslots/bulk-confirm/', views.bulk_create_timeslot_configs_confirm, name='bulk_create_confirm'),
    
    # Payment URLs
    path('payments/', payment_views.PaymentListView.as_view(), name='payment_list'),
    path('payments/<int:pk>/', payment_views.PaymentDetailView.as_view(), name='payment_detail'),
    path('payments/create/<int:appointment_pk>/', payment_views.PaymentCreateView.as_view(), name='payment_create'),
    path('payments/<int:payment_pk>/add-item/', payment_views.add_payment_item, name='add_payment_item'),
    path('payment-items/<int:pk>/delete/', payment_views.delete_payment_item, name='delete_payment_item'),
    path('payments/<int:payment_pk>/add-payment/', payment_views.add_payment_transaction, name='add_payment_transaction'),
    path('payments/dashboard/', payment_views.payment_dashboard, name='payment_dashboard'),
    
    # Patient Payment Summary
    path('patients/<int:pk>/payment-summary/', payment_views.PatientPaymentSummaryView.as_view(), name='patient_payment_summary'),

    # Admin verification for price overrides
    path('admin/verify-password/', payment_views.verify_admin_password, name='verify_admin_password'),
    
    # Receipt PDF Generation
    path('receipts/<int:transaction_pk>/pdf/', payment_views.receipt_pdf, name='receipt_pdf'),

    # API endpoints for timeslot system (PUBLIC + BACKEND)
    path('api/timeslot-availability/', views.get_timeslot_availability_api, name='timeslot_availability_api'),
    path('api/timeslots-for-date/', views.get_timeslots_for_date_api, name='timeslots_for_date_api'),
    path('api/find-patient/', views.find_patient_api, name='find_patient_api'),
    path('api/check-double-booking/', views.check_double_booking_api, name='check_double_booking_api'),

    # API endpoint for pending appointments count (for notification badge)
    path('api/pending-count/', views.pending_count_api, name='pending_count_api'),

    # Treatment Records
    path('<int:appointment_pk>/treatment/', views.treatment_record_view, name='treatment_record'),
    path('<int:appointment_pk>/treatment/delete/', views.delete_treatment_record, name='treatment_record_delete'),
]