from django.urls import path
from . import views

app_name = 'services'

urlpatterns = [
    # Services
    path('', views.ServiceListView.as_view(), name='service_list'),
    path('create/', views.ServiceCreateView.as_view(), name='service_create'),
    path('<int:pk>/', views.ServiceDetailView.as_view(), name='service_detail'),
    path('<int:pk>/edit/', views.ServiceUpdateView.as_view(), name='service_update'),
    path('<int:pk>/toggle-archive/', views.ServiceArchiveView.as_view(), name='service_toggle_archive'),
    
    # Discounts
    path('discounts/', views.DiscountListView.as_view(), name='discount_list'),
    path('discounts/create/', views.DiscountCreateView.as_view(), name='discount_create'),
    path('discounts/<int:pk>/', views.DiscountDetailView.as_view(), name='discount_detail'),
    path('discounts/<int:pk>/edit/', views.DiscountUpdateView.as_view(), name='discount_update'),
    path('discounts/<int:pk>/toggle/', views.DiscountToggleView.as_view(), name='discount_toggle'),
    
    # Service Preset Management
    path('presets/', views.ServicePresetListView.as_view(), name='preset_list'),
    path('presets/create/', views.ServicePresetCreateView.as_view(), name='preset_create'),
    path('presets/<int:pk>/', views.ServicePresetDetailView.as_view(), name='preset_detail'),
    path('presets/<int:pk>/edit/', views.ServicePresetUpdateView.as_view(), name='preset_update'),
    path('presets/<int:pk>/delete/', views.delete_service_preset, name='preset_delete'),
    
    # API endpoint for getting presets by service
    path('api/presets/service/<int:service_id>/', views.get_service_presets_api, name='preset_api'),

    # Product Categories
    path('products/categories/', views.ProductCategoryListView.as_view(), name='product_category_list'),
    path('products/categories/create/', views.ProductCategoryCreateView.as_view(), name='product_category_create'),
    path('products/categories/<int:pk>/edit/', views.ProductCategoryUpdateView.as_view(), name='product_category_update'),
    path('products/categories/<int:pk>/delete/', views.ProductCategoryDeleteView.as_view(), name='product_category_delete'),
    
    # Products
    path('products/', views.ProductListView.as_view(), name='product_list'),
    path('products/create/', views.ProductCreateView.as_view(), name='product_create'),
    path('products/<int:pk>/', views.ProductDetailView.as_view(), name='product_detail'),
    path('products/<int:pk>/edit/', views.ProductUpdateView.as_view(), name='product_update'),
    path('products/<int:pk>/toggle-active/', views.ProductToggleActiveView.as_view(), name='product_toggle_active'),
]