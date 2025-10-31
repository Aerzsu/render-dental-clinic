# appointments/urls.py - Updated with treatment record endpoints
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

    # Check-in page
    path('check-in/', views.CheckInView.as_view(), name='check_in'),
    path('<int:pk>/mark-arrived/', views.mark_patient_arrived, name='mark_patient_arrived'),

    # Appointment actions (BACKEND)
    path('<int:pk>/approve/', views.approve_appointment, name='approve_appointment'),
    path('<int:pk>/reject/', views.reject_appointment, name='reject_appointment'),
    path('appointment/<int:pk>/update-status/', views.update_appointment_status, name='update_appointment_status'),

    # Self-service cancellation (PUBLIC - uses token)
    path('cancel/<str:token>/', views.cancel_appointment_confirm, name='cancel_confirm'),
    path('cancel/<str:token>/process/', views.cancel_appointment_process, name='cancel_process'),

    # Treatment Record endpoints (BACKEND)
    path('treatment/<int:appointment_pk>/notes/update/', views.update_treatment_record_notes, name='treatment_notes_update'),
    path('treatment/<int:appointment_pk>/notes/get/', views.get_treatment_record_notes, name='treatment_notes_get'),
    
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
    path('payments/<int:payment_pk>/force-add-item/', payment_views.force_add_payment_item, name='force_add_payment_item'),
    path('payments/dashboard/', payment_views.payment_dashboard, name='payment_dashboard'),
    
    # Helper endpoint to clear invoice modal flag
    path('clear-invoice-modal/', views.clear_invoice_modal, name='clear_invoice_modal'),
    
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

    # Treatment Records (Keep existing URLs if you have them for the full treatment record management)
    path('<int:appointment_pk>/treatment/', views.treatment_record_view, name='treatment_record'),
    path('<int:appointment_pk>/treatment/delete/', views.delete_treatment_record, name='treatment_record_delete'),
]