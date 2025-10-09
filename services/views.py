# services/views.py
from django.shortcuts import redirect
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.urls import reverse_lazy
from django.views.generic import ListView, DetailView, CreateView, UpdateView
from django.db.models import Q
from users.templatetags.user_tags import has_permission
from .models import Service, Discount
from .forms import ServiceForm, DiscountForm

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
        messages.success(self.request, f'Service {form.instance.name} created successfully.')
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
        messages.success(self.request, f'Service {form.instance.name} updated successfully.')
        return super().form_valid(form)
    
    def get_success_url(self):
        return reverse_lazy('services:service_detail', kwargs={'pk': self.object.pk})

class ServiceArchiveView(LoginRequiredMixin, UpdateView):
    """Archive/unarchive service"""
    model = Service
    fields = []
    
    def dispatch(self, request, *args, **kwargs):
        if not has_permission(request.user, 'billing'):
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('core:dashboard')
        return super().dispatch(request, *args, **kwargs)
    
    def form_valid(self, form):
        service = self.get_object()
        service.is_archived = not service.is_archived
        service.save()
        
        status = 'archived' if service.is_archived else 'unarchived'
        messages.success(self.request, f'Service {service.name} has been {status}.')
        
        return redirect('services:service_list')

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
                # Under 5% or ₱100
                queryset = queryset.filter(
                    Q(is_percentage=True, amount__lt=5) |
                    Q(is_percentage=False, amount__lt=100)
                )
            elif amount_range == '5-10':
                # 5-10% or ₱100-500
                queryset = queryset.filter(
                    Q(is_percentage=True, amount__gte=5, amount__lte=10) |
                    Q(is_percentage=False, amount__gte=100, amount__lte=500)
                )
            elif amount_range == '10-25':
                # 10-25% or ₱500-1000
                queryset = queryset.filter(
                    Q(is_percentage=True, amount__gte=10, amount__lte=25) |
                    Q(is_percentage=False, amount__gte=500, amount__lte=1000)
                )
            elif amount_range == '25+':
                # Over 25% or ₱1000
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
        messages.success(self.request, f'Discount {form.instance.name} created successfully.')
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
        messages.success(self.request, f'Discount {form.instance.name} updated successfully.')
        return super().form_valid(form)
    
    def get_success_url(self):
        return reverse_lazy('services:discount_detail', kwargs={'pk': self.object.pk})

class DiscountToggleView(LoginRequiredMixin, UpdateView):
    """Toggle discount active status"""
    model = Discount
    fields = []
    
    def dispatch(self, request, *args, **kwargs):
        if not has_permission(request.user, 'billing'):
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('core:dashboard')
        return super().dispatch(request, *args, **kwargs)
    
    def form_valid(self, form):
        discount = self.get_object()
        discount.is_active = not discount.is_active
        discount.save()
        
        status = 'activated' if discount.is_active else 'deactivated'
        messages.success(self.request, f'Discount {discount.name} has been {status}.')
        
        return redirect('services:discount_list')