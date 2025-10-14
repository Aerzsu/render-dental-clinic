# reports/urls.py
from django.urls import path
from . import views

app_name = 'reports'

urlpatterns = [
    path('', views.ReportsView.as_view(), name='dashboard'),
    path('export/pdf/', views.export_reports_pdf, name='export_pdf'),
]