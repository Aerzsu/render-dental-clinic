# appointments/urls.py - FIXED for AM/PM slot system
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
    
    # Daily Slots Management (BACKEND - NEW for AM/PM system)
    path('slots/', views.DailySlotsManagementView.as_view(), name='daily_slots_list'),
    path('slots/create/', views.DailySlotsCreateView.as_view(), name='daily_slots_create'),
    path('slots/<int:pk>/edit/', views.DailySlotsUpdateView.as_view(), name='daily_slots_update'),
    path('slots/bulk-create/', views.bulk_create_daily_slots, name='bulk_create_daily_slots'),
    
    # Payment URLs
    path('payments/', payment_views.PaymentListView.as_view(), name='payment_list'),
    path('payments/<int:pk>/', payment_views.PaymentDetailView.as_view(), name='payment_detail'),
    path('payments/create/<int:appointment_pk>/', payment_views.PaymentCreateView.as_view(), name='payment_create'),
    path('payments/<int:payment_pk>/add-item/', payment_views.add_payment_item, name='add_payment_item'),
    path('payment-items/<int:pk>/delete/', payment_views.delete_payment_item, name='delete_payment_item'),
    path('payments/<int:payment_pk>/add-payment/', payment_views.add_payment_transaction, name='add_payment_transaction'),
    path('receipts/<int:transaction_pk>/pdf/', payment_views.generate_receipt_pdf, name='receipt_pdf'),
    path('payments/dashboard/', payment_views.payment_dashboard, name='payment_dashboard'),
    
    # Admin verification for price overrides
    path('admin/verify-password/', payment_views.verify_admin_password, name='verify_admin_password'),

    # API endpoints for AM/PM slot system (PUBLIC + BACKEND)
    path('api/slot-availability/', views.get_slot_availability_api, name='slot_availability_api'),
    path('api/find-patient/', views.find_patient_api, name='find_patient_api'),
]