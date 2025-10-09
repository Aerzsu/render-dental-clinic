#users/views.py
import secrets
import string
from django.shortcuts import get_object_or_404, redirect
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.urls import reverse_lazy, reverse
from django.views.generic import ListView, DetailView, CreateView, UpdateView
from django.db.models import Q
from .models import User, Role
from core.models import AuditLog
from .forms import UserForm, RoleForm  # Import forms from forms.py

class UserListView(LoginRequiredMixin, ListView):
    """List all users with search and filtering functionality"""
    model = User
    template_name = 'users/user_list.html'
    context_object_name = 'users'
    paginate_by = 15
    
    def dispatch(self, request, *args, **kwargs):
        if not request.user.has_permission('maintenance'):
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('core:dashboard')
        return super().dispatch(request, *args, **kwargs)
    
    def get_queryset(self):
        queryset = User.objects.select_related('role')
        
        # Search functionality
        search_query = self.request.GET.get('search')
        if search_query:
            queryset = queryset.filter(
                Q(username__icontains=search_query) |
                Q(first_name__icontains=search_query) |
                Q(last_name__icontains=search_query) |
                Q(email__icontains=search_query)
            )
        
        # Role filter - only show non-archived roles
        role_filter = self.request.GET.get('role_filter')
        if role_filter:
            if role_filter == 'no_role':
                queryset = queryset.filter(role__isnull=True)
            else:
                try:
                    role_id = int(role_filter)
                    queryset = queryset.filter(role_id=role_id)
                except (ValueError, TypeError):
                    pass
        
        # Status filter
        status_filter = self.request.GET.get('status_filter')
        if status_filter:
            if status_filter == 'active':
                queryset = queryset.filter(is_active=True)
            elif status_filter == 'inactive':
                queryset = queryset.filter(is_active=False)
            elif status_filter == 'dentist':
                queryset = queryset.filter(is_active_dentist=True)
            elif status_filter == 'non_dentist':
                queryset = queryset.filter(is_active_dentist=False)
        
        # Sorting
        sort_by = self.request.GET.get('sort', 'username')
        valid_sorts = [
            'username', '-username', 'first_name', '-first_name', 
            'last_name', '-last_name', 'role__display_name', '-role__display_name',
            'created_at', '-created_at', '-updated_at'
        ]
        if sort_by in valid_sorts:
            # Handle sorting by role for users without roles
            if sort_by in ['role__display_name', '-role__display_name']:
                # Put users without roles at the end
                if sort_by.startswith('-'):
                    queryset = queryset.order_by('-role__display_name', 'username')
                else:
                    queryset = queryset.order_by('role__display_name', 'username')
            else:
                queryset = queryset.order_by(sort_by)
        else:
            queryset = queryset.order_by('username')
        
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            'search_query': self.request.GET.get('search', ''),
            'role_filter': self.request.GET.get('role_filter', ''),
            'status_filter': self.request.GET.get('status_filter', ''),
            'sort_by': self.request.GET.get('sort', 'username'),
            # Only show non-archived roles in the filter dropdown
            'available_roles': Role.objects.filter(is_archived=False).order_by('display_name'),
        })
        return context

class UserDetailView(LoginRequiredMixin, DetailView):
    """View user details"""
    model = User
    template_name = 'users/user_detail.html'
    context_object_name = 'user_obj'
    
    def dispatch(self, request, *args, **kwargs):
        if not request.user.has_permission('maintenance'):
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('core:dashboard')
        return super().dispatch(request, *args, **kwargs)

class UserCreateView(LoginRequiredMixin, CreateView):
    """Create new user"""
    model = User
    form_class = UserForm
    template_name = 'users/user_form.html'
    
    def dispatch(self, request, *args, **kwargs):
        if not request.user.has_permission('maintenance'):
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('core:dashboard')
        return super().dispatch(request, *args, **kwargs)
    
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['is_update'] = False
        kwargs['request_user'] = self.request.user
        return kwargs
    
    def form_valid(self, form):
        messages.success(self.request, f'User {form.instance.username} created successfully.')
        return super().form_valid(form)
    
    def get_success_url(self):
        return reverse_lazy('users:user_detail', kwargs={'pk': self.object.pk})

class UserUpdateView(LoginRequiredMixin, UpdateView):
    """Update user information"""
    model = User
    form_class = UserForm
    template_name = 'users/user_form.html'
    context_object_name = 'user_obj'
    
    def dispatch(self, request, *args, **kwargs):
        if not request.user.has_permission('maintenance'):
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('core:dashboard')
        return super().dispatch(request, *args, **kwargs)
    
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['is_update'] = True
        kwargs['request_user'] = self.request.user
        return kwargs
    
    def form_valid(self, form):
        # Additional validation for last admin protection
        if (self.object.role and self.object.role.name == 'admin' and 
            form.cleaned_data.get('role') and form.cleaned_data['role'].name != 'admin'):
            
            # Check if this would be removing the last admin
            admin_count = User.objects.filter(
                role__name='admin', 
                is_active=True
            ).exclude(pk=self.object.pk).count()
            
            if admin_count == 0:
                messages.error(self.request, 'Cannot change role: This is the last admin user in the system.')
                return super().form_invalid(form)

        return super().form_valid(form)
    
    def get_success_url(self):
        return reverse_lazy('users:user_detail', kwargs={'pk': self.object.pk})

@login_required
def toggle_user_active(request, pk):
    """Toggle user active status"""
    if not request.user.has_permission('maintenance'):
        messages.error(request, 'You do not have permission to perform this action.')
        return redirect('core:dashboard')
    
    user = get_object_or_404(User, pk=pk)
    
    # Don't let users deactivate themselves
    if user == request.user:
        messages.error(request, 'You cannot deactivate your own account.')
        return redirect('users:user_detail', pk=pk)
    
    # Prevent deactivating the last admin
    if (user.role and user.role.name == 'admin' and user.is_active):
        admin_count = User.objects.filter(
            role__name='admin', 
            is_active=True
        ).exclude(pk=user.pk).count()
        
        if admin_count == 0:
            messages.error(request, 'Cannot deactivate: This is the last admin user in the system.')
            return redirect('users:user_detail', pk=pk)
    
    user.is_active = not user.is_active
    user.save()
    
    status = 'activated' if user.is_active else 'deactivated'
    messages.success(request, f'User {user.username} has been {status}.')
    
    return redirect('users:user_detail', pk=pk)

@login_required
def toggle_role_archive(request, pk):
    """Toggle role archive status"""
    if not request.user.has_permission('maintenance'):
        messages.error(request, 'You do not have permission to perform this action.')
        return redirect('core:dashboard')
    
    role = get_object_or_404(Role, pk=pk)
    
    # Don't allow archiving protected roles (like admin)
    if role.is_protected():
        messages.error(request, 'Protected roles cannot be archived.')
        return redirect('users:role_list')
    
    # Toggle archive status
    if role.is_archived:
        role.is_archived = False
        status_message = f'Role "{role.display_name}" has been restored.'
    else:
        role.is_archived = True
        status_message = f'Role "{role.display_name}" has been archived.'
        
        # Warn about users who will lose access
        affected_users = role.user_set.filter(is_active=True).count()
        if affected_users > 0:
            status_message += f' {affected_users} user{"s" if affected_users != 1 else ""} with this role will lose system access until reassigned.'
    
    role.save()
    messages.success(request, status_message)
    
    return redirect('users:role_detail', pk=pk)

@login_required
def reset_user_password(request, pk):
    """Reset a user's password to a random temporary password"""
    if not request.user.has_permission('maintenance'):
        messages.error(request, 'You do not have permission to perform this action.')
        return redirect('core:dashboard')
    
    user_to_reset = get_object_or_404(User, pk=pk)
    
    # Don't let users reset their own password this way
    if user_to_reset == request.user:
        messages.error(request, 'You cannot reset your own password. Please use the Change Password feature.')
        return redirect('users:user_detail', pk=pk)
    
    # Only process POST requests (from the confirmation)
    if request.method != 'POST':
        messages.error(request, 'Invalid request method.')
        return redirect('users:user_update', pk=pk)
    
    # Generate a random 12-character password
    # Mix of uppercase, lowercase, digits, and a few safe special characters
    alphabet = string.ascii_letters + string.digits + '!@#$%'
    temp_password = ''.join(secrets.choice(alphabet) for _ in range(12))
    
    # Set the new password
    user_to_reset.set_password(temp_password)
    user_to_reset.save()
    
    # Log the action in AuditLog
    AuditLog.objects.create(
        user=request.user,
        action='password_reset',
        model_name='User',
        object_id=str(user_to_reset.pk),
        details=f'Password reset for user: {user_to_reset.username}'
    )
    
    # Store the temporary password in session to display once
    request.session['temp_password'] = temp_password
    request.session['temp_password_username'] = user_to_reset.username
    
    messages.success(
        request, 
        f'Password has been reset for {user_to_reset.get_full_name() or user_to_reset.username}. '
        'The temporary password is displayed below and will only be shown once.'
    )
    
    return redirect('users:user_update', pk=pk)

# Role Views
class RoleListView(LoginRequiredMixin, ListView):
    """List all roles"""
    model = Role
    template_name = 'users/role_list.html'
    context_object_name = 'roles'
    
    def dispatch(self, request, *args, **kwargs):
        if not request.user.has_permission('maintenance'):
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('core:dashboard')
        return super().dispatch(request, *args, **kwargs)
    
    def get_queryset(self):
        # Show archived roles if requested, otherwise show only active
        show_archived = self.request.GET.get('show_archived') == 'true'
        if show_archived:
            return Role.objects.all().order_by('is_archived', 'name')
        else:
            return Role.objects.filter(is_archived=False).order_by('name')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['show_archived'] = self.request.GET.get('show_archived') == 'true'
        context['archived_count'] = Role.objects.filter(is_archived=True).count()
        return context

class RoleDetailView(LoginRequiredMixin, DetailView):
    """View role details"""
    model = Role
    template_name = 'users/role_detail.html'
    context_object_name = 'role'
    
    def dispatch(self, request, *args, **kwargs):
        if not request.user.has_permission('maintenance'):
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('core:dashboard')
        return super().dispatch(request, *args, **kwargs)

class RoleCreateView(LoginRequiredMixin, CreateView):
    """Create new role"""
    model = Role
    form_class = RoleForm
    template_name = 'users/role_form.html'
    
    def dispatch(self, request, *args, **kwargs):
        if not request.user.has_permission('maintenance'):
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('core:dashboard')
        return super().dispatch(request, *args, **kwargs)
    
    def form_valid(self, form):
        messages.success(self.request, f'Role {form.instance.display_name} created successfully.')
        return super().form_valid(form)
    
    def get_success_url(self):
        return reverse_lazy('users:role_detail', kwargs={'pk': self.object.pk})

class RoleUpdateView(LoginRequiredMixin, UpdateView):
    """Update role information"""
    model = Role
    form_class = RoleForm
    template_name = 'users/role_form.html'
    
    def dispatch(self, request, *args, **kwargs):
        if not request.user.has_permission('maintenance'):
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('core:dashboard')
        return super().dispatch(request, *args, **kwargs)
    
    def get_object(self):
        role = super().get_object()
        # Only prevent editing of admin role (protected role)
        if role.is_protected():
            messages.error(self.request, 'Admin role cannot be edited.')
            return redirect('users:role_list')
        return role
    
    def form_valid(self, form):
        messages.success(self.request, f'Role {form.instance.display_name} updated successfully.')
        return super().form_valid(form)
    
    def get_success_url(self):
        return reverse_lazy('users:role_detail', kwargs={'pk': self.object.pk})