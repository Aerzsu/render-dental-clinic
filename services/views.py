# services/views.py
from django.shortcuts import redirect, get_object_or_404
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.urls import reverse, reverse_lazy
from django.http import JsonResponse
from django.views.generic import ListView, DetailView, CreateView, UpdateView, View

from django.db.models import Q, Count
from users.templatetags.user_tags import has_permission
from .models import Product, Service, Discount, ProductCategory, ServicePreset
from .forms import ServiceForm, DiscountForm, ProductCategoryForm, ProductForm, ServicePresetForm
import json

class ServiceListView(LoginRequiredMixin, ListView):
    """List all services with search and filtering functionality"""
    model = Service
    template_name = 'services/service_list.html'
    context_object_name = 'services'
    paginate_by = 15
    
    def dispatch(self, request, *args, **kwargs):
        if not has_permission(request.user, 'billing'):
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('core:dashboard')
        return super().dispatch(request, *args, **kwargs)
    
    def get_queryset(self):
        queryset = Service.objects.all()
        
        # Search functionality
        search_query = self.request.GET.get('search')
        if search_query:
            queryset = queryset.filter(
                Q(name__icontains=search_query) |
                Q(description__icontains=search_query)
            )
        
        # Filter by archived status
        show_archived = self.request.GET.get('show_archived')
        if not show_archived:
            queryset = queryset.filter(is_archived=False)
        
        # Price range filter
        price_range = self.request.GET.get('price_range')
        if price_range:
            if price_range == '0-500':
                queryset = queryset.filter(min_price__lt=500)
            elif price_range == '500-1000':
                queryset = queryset.filter(min_price__gte=500, max_price__lte=1000)
            elif price_range == '1000-2000':
                queryset = queryset.filter(min_price__gte=1000, max_price__lte=2000)
            elif price_range == '2000-5000':
                queryset = queryset.filter(min_price__gte=2000, max_price__lte=5000)
            elif price_range == '5000+':
                queryset = queryset.filter(min_price__gte=5000)
        
        # Duration range filter
        duration_range = self.request.GET.get('duration_range')
        if duration_range:
            if duration_range == '0-30':
                queryset = queryset.filter(duration_minutes__lt=30)
            elif duration_range == '30-60':
                queryset = queryset.filter(duration_minutes__gte=30, duration_minutes__lte=60)
            elif duration_range == '60-120':
                queryset = queryset.filter(duration_minutes__gte=60, duration_minutes__lte=120)
            elif duration_range == '120+':
                queryset = queryset.filter(duration_minutes__gte=120)
        
        # Sorting
        sort_by = self.request.GET.get('sort', 'name')
        valid_sorts = ['name', '-name', 'min_price', '-min_price', 'duration_minutes', 
                      '-duration_minutes', 'created_at', '-created_at', '-updated_at']
        if sort_by in valid_sorts:
            queryset = queryset.order_by(sort_by)
        else:
            queryset = queryset.order_by('name')
        
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            'search_query': self.request.GET.get('search', ''),
            'show_archived': self.request.GET.get('show_archived', False),
            'price_range': self.request.GET.get('price_range', ''),
            'duration_range': self.request.GET.get('duration_range', ''),
            'sort_by': self.request.GET.get('sort', 'name'),
        })
        return context

class ServiceDetailView(LoginRequiredMixin, DetailView):
    """View service details"""
    model = Service
    template_name = 'services/service_detail.html'
    context_object_name = 'service'
    
    def dispatch(self, request, *args, **kwargs):
        if not has_permission(request.user, 'billing'):
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('core:dashboard')
        return super().dispatch(request, *args, **kwargs)

class ServiceCreateView(LoginRequiredMixin, CreateView):
    """Create new service"""
    model = Service
    form_class = ServiceForm
    template_name = 'services/service_form.html'
    
    def dispatch(self, request, *args, **kwargs):
        if not has_permission(request.user, 'billing'):
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('core:dashboard')
        return super().dispatch(request, *args, **kwargs)
    
    def form_valid(self, form):
        messages.success(self.request, f'Service "{form.instance.name}" created successfully.')
        return super().form_valid(form)
    
    def get_success_url(self):
        return reverse_lazy('services:service_detail', kwargs={'pk': self.object.pk})

class ServiceUpdateView(LoginRequiredMixin, UpdateView):
    """Update service information"""
    model = Service
    form_class = ServiceForm
    template_name = 'services/service_form.html'
    
    def dispatch(self, request, *args, **kwargs):
        if not has_permission(request.user, 'billing'):
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('core:dashboard')
        return super().dispatch(request, *args, **kwargs)
    
    def form_valid(self, form):
        messages.success(self.request, f'Service "{form.instance.name}" updated successfully.')
        return super().form_valid(form)
    
    def get_success_url(self):
        return reverse_lazy('services:service_detail', kwargs={'pk': self.object.pk})

class ServiceArchiveView(LoginRequiredMixin, View):
    """Toggle service archive status"""
    
    def dispatch(self, request, *args, **kwargs):
        if not has_permission(request.user, 'billing'):
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('core:dashboard')
        return super().dispatch(request, *args, **kwargs)
    
    def get(self, request, pk):
        service = get_object_or_404(Service, pk=pk)
        service.is_archived = not service.is_archived
        service.save()
        
        status = 'archived' if service.is_archived else 'unarchived'
        messages.success(request, f'Service "{service.name}" has been {status} successfully.')
        
        return redirect('services:service_detail', pk=service.pk)

# Discount Views
class DiscountListView(LoginRequiredMixin, ListView):
    """List all discounts with search and filtering functionality"""
    model = Discount
    template_name = 'services/discount_list.html'
    context_object_name = 'discounts'
    paginate_by = 15
    
    def dispatch(self, request, *args, **kwargs):
        if not has_permission(request.user, 'billing'):
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('core:dashboard')
        return super().dispatch(request, *args, **kwargs)
    
    def get_queryset(self):
        queryset = Discount.objects.all()
        
        # Search functionality
        search_query = self.request.GET.get('search')
        if search_query:
            queryset = queryset.filter(name__icontains=search_query)
        
        # Filter by active status
        show_inactive = self.request.GET.get('show_inactive')
        if not show_inactive:
            queryset = queryset.filter(is_active=True)
        
        # Discount type filter
        discount_type = self.request.GET.get('discount_type')
        if discount_type:
            if discount_type == 'percentage':
                queryset = queryset.filter(is_percentage=True)
            elif discount_type == 'fixed':
                queryset = queryset.filter(is_percentage=False)
        
        # Amount range filter
        amount_range = self.request.GET.get('amount_range')
        if amount_range:
            if amount_range == '0-5':
                queryset = queryset.filter(
                    Q(is_percentage=True, amount__lt=5) |
                    Q(is_percentage=False, amount__lt=100)
                )
            elif amount_range == '5-10':
                queryset = queryset.filter(
                    Q(is_percentage=True, amount__gte=5, amount__lte=10) |
                    Q(is_percentage=False, amount__gte=100, amount__lte=500)
                )
            elif amount_range == '10-25':
                queryset = queryset.filter(
                    Q(is_percentage=True, amount__gte=10, amount__lte=25) |
                    Q(is_percentage=False, amount__gte=500, amount__lte=1000)
                )
            elif amount_range == '25+':
                queryset = queryset.filter(
                    Q(is_percentage=True, amount__gte=25) |
                    Q(is_percentage=False, amount__gte=1000)
                )
        
        # Sorting
        sort_by = self.request.GET.get('sort', 'name')
        valid_sorts = ['name', '-name', 'amount', '-amount', 'created_at', '-created_at', '-updated_at']
        if sort_by in valid_sorts:
            queryset = queryset.order_by(sort_by)
        else:
            queryset = queryset.order_by('name')
        
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            'search_query': self.request.GET.get('search', ''),
            'show_inactive': self.request.GET.get('show_inactive', False),
            'discount_type': self.request.GET.get('discount_type', ''),
            'amount_range': self.request.GET.get('amount_range', ''),
            'sort_by': self.request.GET.get('sort', 'name'),
        })
        return context

class DiscountDetailView(LoginRequiredMixin, DetailView):
    """View discount details"""
    model = Discount
    template_name = 'services/discount_detail.html'
    context_object_name = 'discount'
    
    def dispatch(self, request, *args, **kwargs):
        if not has_permission(request.user, 'billing'):
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('core:dashboard')
        return super().dispatch(request, *args, **kwargs)

class DiscountCreateView(LoginRequiredMixin, CreateView):
    """Create new discount"""
    model = Discount
    form_class = DiscountForm
    template_name = 'services/discount_form.html'
    
    def dispatch(self, request, *args, **kwargs):
        if not has_permission(request.user, 'billing'):
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('core:dashboard')
        return super().dispatch(request, *args, **kwargs)
    
    def form_valid(self, form):
        messages.success(self.request, f'Discount "{form.instance.name}" created successfully.')
        return super().form_valid(form)
    
    def get_success_url(self):
        return reverse_lazy('services:discount_detail', kwargs={'pk': self.object.pk})

class DiscountUpdateView(LoginRequiredMixin, UpdateView):
    """Update discount information"""
    model = Discount
    form_class = DiscountForm
    template_name = 'services/discount_form.html'
    
    def dispatch(self, request, *args, **kwargs):
        if not has_permission(request.user, 'billing'):
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('core:dashboard')
        return super().dispatch(request, *args, **kwargs)
    
    def form_valid(self, form):
        messages.success(self.request, f'Discount "{form.instance.name}" updated successfully.')
        return super().form_valid(form)
    
    def get_success_url(self):
        return reverse_lazy('services:discount_detail', kwargs={'pk': self.object.pk})

class DiscountToggleView(LoginRequiredMixin, View):
    """Toggle discount active status"""
    
    def dispatch(self, request, *args, **kwargs):
        if not has_permission(request.user, 'billing'):
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('core:dashboard')
        return super().dispatch(request, *args, **kwargs)
    
    def get(self, request, pk):
        discount = get_object_or_404(Discount, pk=pk)
        discount.is_active = not discount.is_active
        discount.save()
        
        status = 'activated' if discount.is_active else 'deactivated'
        messages.success(request, f'Discount "{discount.name}" has been {status} successfully.')
        
        return redirect('services:discount_detail', pk=discount.pk)
    

# Product Category Views
class ProductCategoryListView(LoginRequiredMixin, ListView):
    """List all product categories with search functionality"""
    model = ProductCategory
    template_name = 'services/product_category_list.html'
    context_object_name = 'categories'
    paginate_by = 15
    
    def dispatch(self, request, *args, **kwargs):
        if not has_permission(request.user, 'maintenance'):
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('core:dashboard')
        return super().dispatch(request, *args, **kwargs)
    
    def get_queryset(self):
        queryset = ProductCategory.objects.annotate(
            active_products_count=Count(
                'products',
                filter=Q(products__is_active=True)
            ),
            total_products_count=Count('products')
        )
        
        # Search functionality
        search_query = self.request.GET.get('search')
        if search_query:
            queryset = queryset.filter(
                Q(name__icontains=search_query) |
                Q(description__icontains=search_query)
            )
        
        # Sorting
        sort_by = self.request.GET.get('sort', 'display_order')
        valid_sorts = ['display_order', 'name', '-name', 'created_at', '-created_at', '-updated_at']
        if sort_by in valid_sorts:
            queryset = queryset.order_by(sort_by)
        else:
            queryset = queryset.order_by('display_order', 'name')
        
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            'search_query': self.request.GET.get('search', ''),
            'sort_by': self.request.GET.get('sort', 'display_order'),
        })
        return context


class ProductCategoryCreateView(LoginRequiredMixin, CreateView):
    """Create new product category"""
    model = ProductCategory
    form_class = ProductCategoryForm
    template_name = 'services/product_category_form.html'
    
    def dispatch(self, request, *args, **kwargs):
        if not has_permission(request.user, 'maintenance'):
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('core:dashboard')
        return super().dispatch(request, *args, **kwargs)
    
    def form_valid(self, form):
        messages.success(self.request, f'Category "{form.instance.name}" created successfully.')
        return super().form_valid(form)
    
    def get_success_url(self):
        return reverse_lazy('services:product_category_list')


class ProductCategoryUpdateView(LoginRequiredMixin, UpdateView):
    """Update product category"""
    model = ProductCategory
    form_class = ProductCategoryForm
    template_name = 'services/product_category_form.html'
    
    def dispatch(self, request, *args, **kwargs):
        if not has_permission(request.user, 'maintenance'):
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('core:dashboard')
        return super().dispatch(request, *args, **kwargs)
    
    def form_valid(self, form):
        messages.success(self.request, f'Category "{form.instance.name}" updated successfully.')
        return super().form_valid(form)
    
    def get_success_url(self):
        return reverse_lazy('services:product_category_list')


class ProductCategoryDeleteView(LoginRequiredMixin, View):
    """Delete product category (only if no active products)"""
    
    def dispatch(self, request, *args, **kwargs):
        if not has_permission(request.user, 'maintenance'):
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('core:dashboard')
        return super().dispatch(request, *args, **kwargs)
    
    def post(self, request, pk):
        category = get_object_or_404(ProductCategory, pk=pk)
        
        # Check if category has active products
        if not category.can_be_deleted():
            active_count = category.get_active_products_count()
            messages.error(
                request,
                f'Cannot delete category "{category.name}" because it has {active_count} active product(s). '
                f'Please deactivate or move all products before deleting this category.'
            )
            return redirect('services:product_category_list')
        
        # Check if category has any products (including inactive)
        total_count = category.get_total_products_count()
        if total_count > 0:
            messages.error(
                request,
                f'Cannot delete category "{category.name}" because it has {total_count} product(s) (including inactive). '
                f'Please remove or reassign all products before deleting this category.'
            )
            return redirect('services:product_category_list')
        
        # Safe to delete
        category_name = category.name
        category.delete()
        messages.success(request, f'Category "{category_name}" deleted successfully.')
        
        return redirect('services:product_category_list')


# Product Views
class ProductListView(LoginRequiredMixin, ListView):
    """List all products with search and filtering functionality"""
    model = Product
    template_name = 'services/product_list.html'
    context_object_name = 'products'
    paginate_by = 15
    
    def dispatch(self, request, *args, **kwargs):
        if not has_permission(request.user, 'maintenance'):
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('core:dashboard')
        return super().dispatch(request, *args, **kwargs)
    
    def get_queryset(self):
        queryset = Product.objects.select_related('category', 'created_by')
        
        # Search functionality
        search_query = self.request.GET.get('search')
        if search_query:
            queryset = queryset.filter(
                Q(name__icontains=search_query) |
                Q(description__icontains=search_query) |
                Q(category__name__icontains=search_query)
            )
        
        # Filter by active status
        show_inactive = self.request.GET.get('show_inactive')
        if not show_inactive:
            queryset = queryset.filter(is_active=True)
        
        # Filter by category
        category_id = self.request.GET.get('category')
        if category_id:
            queryset = queryset.filter(category_id=category_id)
        
        # Price range filter
        price_range = self.request.GET.get('price_range')
        if price_range:
            if price_range == '0-50':
                queryset = queryset.filter(price__lt=50)
            elif price_range == '50-100':
                queryset = queryset.filter(price__gte=50, price__lte=100)
            elif price_range == '100-500':
                queryset = queryset.filter(price__gte=100, price__lte=500)
            elif price_range == '500+':
                queryset = queryset.filter(price__gte=500)
        
        # Sorting
        sort_by = self.request.GET.get('sort', 'category')
        valid_sorts = ['name', '-name', 'price', '-price', 'category__name', 
                      '-category__name', 'created_at', '-created_at', '-updated_at']
        if sort_by in valid_sorts:
            if sort_by == 'category':
                queryset = queryset.order_by('category__name', 'name')
            else:
                queryset = queryset.order_by(sort_by)
        else:
            queryset = queryset.order_by('category__name', 'name')
        
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            'search_query': self.request.GET.get('search', ''),
            'show_inactive': self.request.GET.get('show_inactive', False),
            'selected_category': self.request.GET.get('category', ''),
            'price_range': self.request.GET.get('price_range', ''),
            'sort_by': self.request.GET.get('sort', 'category'),
            'categories': ProductCategory.objects.all(),
        })
        return context


class ProductDetailView(LoginRequiredMixin, DetailView):
    """View product details"""
    model = Product
    template_name = 'services/product_detail.html'
    context_object_name = 'product'
    
    def dispatch(self, request, *args, **kwargs):
        if not has_permission(request.user, 'maintenance'):
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('core:dashboard')
        return super().dispatch(request, *args, **kwargs)
    
    def get_queryset(self):
        return Product.objects.select_related('category', 'created_by')


class ProductCreateView(LoginRequiredMixin, CreateView):
    """Create new product"""
    model = Product
    form_class = ProductForm
    template_name = 'services/product_form.html'
    
    def dispatch(self, request, *args, **kwargs):
        if not has_permission(request.user, 'maintenance'):
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('core:dashboard')
        return super().dispatch(request, *args, **kwargs)
    
    def form_valid(self, form):
        # Set created_by to current user
        form.instance.created_by = self.request.user
        messages.success(self.request, f'Product "{form.instance.name}" created successfully.')
        return super().form_valid(form)
    
    def get_success_url(self):
        return reverse_lazy('services:product_detail', kwargs={'pk': self.object.pk})


class ProductUpdateView(LoginRequiredMixin, UpdateView):
    """Update product information"""
    model = Product
    form_class = ProductForm
    template_name = 'services/product_form.html'
    
    def dispatch(self, request, *args, **kwargs):
        if not has_permission(request.user, 'maintenance'):
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('core:dashboard')
        return super().dispatch(request, *args, **kwargs)
    
    def form_valid(self, form):
        # Check if price changed - log for audit
        if self.object.price != form.cleaned_data['price']:
            old_price = self.object.price
            new_price = form.cleaned_data['price']
            
            # Import here to avoid circular imports
            from core.models import AuditLog
            
            # Create audit log for price change
            AuditLog.objects.create(
                user=self.request.user,
                action='update',
                model_name='Product',
                object_id=str(self.object.pk),
                object_repr=self.object.name,
                changes={
                    'price': {
                        'old': float(old_price),
                        'new': float(new_price)
                    }
                },
                ip_address=self.request.META.get('REMOTE_ADDR')
            )
        
        messages.success(self.request, f'Product "{form.instance.name}" updated successfully.')
        return super().form_valid(form)
    
    def get_success_url(self):
        return reverse_lazy('services:product_detail', kwargs={'pk': self.object.pk})


class ProductToggleActiveView(LoginRequiredMixin, View):
    """Toggle product active status"""
    
    def dispatch(self, request, *args, **kwargs):
        if not has_permission(request.user, 'maintenance'):
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('core:dashboard')
        return super().dispatch(request, *args, **kwargs)
    
    def get(self, request, pk):
        product = get_object_or_404(Product, pk=pk)
        product.is_active = not product.is_active
        product.save()
        
        status = 'activated' if product.is_active else 'deactivated'
        messages.success(request, f'Product "{product.name}" has been {status} successfully.')
        
        return redirect('services:product_detail', pk=product.pk)
    
class ServicePresetListView(LoginRequiredMixin, ListView):
    """List all presets created by current user"""
    model = ServicePreset
    template_name = 'services/preset_list.html'
    context_object_name = 'presets'
    paginate_by = 15
    
    def dispatch(self, request, *args, **kwargs):
        if not request.user.has_permission('appointments'):
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('core:dashboard')
        return super().dispatch(request, *args, **kwargs)
    
    def get_queryset(self):
        """Return only presets created by current user"""
        queryset = ServicePreset.objects.filter(
            created_by=self.request.user
        ).select_related('service').prefetch_related('products__product')
        
        # Filter by service if provided
        service_id = self.request.GET.get('service')
        if service_id:
            queryset = queryset.filter(service_id=service_id)
        
        # Search by name
        search = self.request.GET.get('search', '').strip()
        if search:
            queryset = queryset.filter(name__icontains=search)
        
        return queryset.order_by('-is_default', 'service__name', 'name')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['services'] = Service.active.all()
        context['search_query'] = self.request.GET.get('search', '')
        context['selected_service'] = self.request.GET.get('service', '')
        
        # Group presets by service for better display
        presets_by_service = {}
        for preset in context['presets']:
            service_name = preset.service.name
            if service_name not in presets_by_service:
                presets_by_service[service_name] = []
            presets_by_service[service_name].append(preset)
        
        context['presets_by_service'] = presets_by_service
        return context


class ServicePresetCreateView(LoginRequiredMixin, CreateView):
    """Create new service preset"""
    model = ServicePreset
    form_class = ServicePresetForm
    template_name = 'services/preset_form.html'
    
    def dispatch(self, request, *args, **kwargs):
        if not request.user.has_permission('appointments'):
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('core:dashboard')
        return super().dispatch(request, *args, **kwargs)
    
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get available products grouped by category
        products_by_category = {}
        for product in Product.objects.filter(is_active=True).select_related('category').order_by('category__display_order', 'category__name', 'name'):
            cat_name = product.category.name
            if cat_name not in products_by_category:
                products_by_category[cat_name] = []
            products_by_category[cat_name].append({
                'id': product.id,
                'name': product.name,
                'price': float(product.price)
            })
        
        context['products_by_category'] = products_by_category
        context['products_json'] = json.dumps(
            list(Product.objects.filter(is_active=True).values('id', 'name', 'category__name'))
        )
        
        # Pre-select service if provided in URL
        service_id = self.request.GET.get('service')
        if service_id:
            context['preselected_service'] = service_id
        
        return context
    
    def form_valid(self, form):
        # Set the created_by field before saving
        form.instance.created_by = self.request.user
        messages.success(self.request, f'Preset "{form.instance.name}" created successfully.')
        return super().form_valid(form)
    
    def form_invalid(self, form):
        for field, errors in form.errors.items():
            for error in errors:
                messages.error(self.request, f'{field}: {error}')
        return super().form_invalid(form)
    
    def get_success_url(self):
        # If opened from treatment record, return there
        return_url = self.request.GET.get('return_to')
        if return_url:
            return return_url
        return reverse('services:preset_list')


class ServicePresetUpdateView(LoginRequiredMixin, UpdateView):
    """Update existing service preset"""
    model = ServicePreset
    form_class = ServicePresetForm
    template_name = 'services/preset_form.html'
    
    def dispatch(self, request, *args, **kwargs):
        if not request.user.has_permission('appointments'):
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('core:dashboard')
        
        # Ensure user can only edit their own presets
        preset = self.get_object()
        if preset.created_by != request.user:
            messages.error(request, 'You can only edit your own presets.')
            return redirect('services:preset_list')
        
        return super().dispatch(request, *args, **kwargs)
    
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get available products grouped by category
        products_by_category = {}
        for product in Product.objects.filter(is_active=True).select_related('category').order_by('category__display_order', 'category__name', 'name'):
            cat_name = product.category.name
            if cat_name not in products_by_category:
                products_by_category[cat_name] = []
            products_by_category[cat_name].append({
                'id': product.id,
                'name': product.name,
                'price': float(product.price)
            })
        
        context['products_by_category'] = products_by_category
        context['products_json'] = json.dumps(
            list(Product.objects.filter(is_active=True).values('id', 'name', 'category__name'))
        )
        
        return context
    
    def form_valid(self, form):
        messages.success(self.request, f'Preset "{form.instance.name}" updated successfully.')
        return super().form_valid(form)
    
    def get_success_url(self):
        return reverse('services:preset_list')


class ServicePresetDetailView(LoginRequiredMixin, DetailView):
    """View preset details"""
    model = ServicePreset
    template_name = 'services/preset_detail.html'
    context_object_name = 'preset'
    
    def dispatch(self, request, *args, **kwargs):
        if not request.user.has_permission('appointments'):
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('core:dashboard')
        
        # Ensure user can only view their own presets
        preset = self.get_object()
        if preset.created_by != request.user:
            messages.error(request, 'You can only view your own presets.')
            return redirect('services:preset_list')
        
        return super().dispatch(request, *args, **kwargs)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['products'] = self.object.products.select_related('product__category').order_by('order')
        return context


@login_required
@require_POST
def delete_service_preset(request, pk):
    """Delete service preset"""
    if not request.user.has_permission('appointments'):
        messages.error(request, 'You do not have permission to perform this action.')
        return redirect('core:dashboard')
    
    preset = get_object_or_404(ServicePreset, pk=pk)
    
    # Ensure user can only delete their own presets
    if preset.created_by != request.user:
        messages.error(request, 'You can only delete your own presets.')
        return redirect('services:preset_list')
    
    preset_name = preset.name
    preset.delete()
    
    messages.success(request, f'Preset "{preset_name}" deleted successfully.')
    return redirect('services:preset_list')


@login_required
def get_service_presets_api(request, service_id):
    """
    API endpoint to get presets for a specific service
    Used by treatment record form to load presets
    """
    if not request.user.has_permission('appointments'):
        return JsonResponse({'error': 'Permission denied'}, status=403)
    
    try:
        service = Service.objects.get(pk=service_id)
    except Service.DoesNotExist:
        return JsonResponse({'error': 'Service not found'}, status=404)
    
    # Get presets for this service created by current user
    presets = ServicePreset.objects.filter(
        service=service,
        created_by=request.user
    ).prefetch_related('products__product')
    
    presets_data = []
    for preset in presets:
        products_data = []
        for preset_product in preset.products.all():
            products_data.append({
                'product_id': preset_product.product.id,
                'product_name': preset_product.product.name,
                'quantity': preset_product.quantity,
                'notes': preset_product.notes
            })
        
        presets_data.append({
            'id': preset.id,
            'name': preset.name,
            'description': preset.description,
            'is_default': preset.is_default,
            'products': products_data
        })
    
    return JsonResponse({
        'success': True,
        'service_name': service.name,
        'presets': presets_data
    })
