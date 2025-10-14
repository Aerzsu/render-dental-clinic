from django.urls import path
from . import views

app_name = 'patients'

urlpatterns = [
    # Patient management
    path('', views.PatientListView.as_view(), name='patient_list'),
    path('create/', views.PatientCreateView.as_view(), name='patient_create'),
    path('<int:pk>/', views.PatientDetailView.as_view(), name='patient_detail'),
    path('<int:pk>/edit/', views.PatientUpdateView.as_view(), name='patient_update'),
    path('<int:pk>/toggle-active/', views.toggle_patient_active, name='toggle_patient_active'),
    
    # Search and find functionality
    path('search/', views.PatientSearchView.as_view(), name='patient_search'),
    
    # AJAX endpoints
    path('api/<int:pk>/quick-info/', views.patient_quick_info, name='patient_quick_info'),
]