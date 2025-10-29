# appointments/admin.py - Updated for timeslot-based system
from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe
from .models import TimeSlotConfiguration, Appointment, Payment, PaymentItem, PaymentTransaction


@admin.register(TimeSlotConfiguration)
class TimeSlotConfigurationAdmin(admin.ModelAdmin):
    list_display = ['date', 'start_time', 'end_time', 'total_slots_count', 'availability_status', 'created_by']
    list_filter = ['created_by', 'date']
    search_fields = ['date', 'notes']
    date_hierarchy = 'date'
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = (
        ('Date & Time Range', {
            'fields': ('date', 'start_time', 'end_time')
        }),
        ('Details', {
            'fields': ('notes', 'created_by')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ['collapse']
        }),
    )
    
    def total_slots_count(self, obj):
        """Display total number of 30-minute slots"""
        slots = obj.get_all_timeslots()
        return len(slots)
    total_slots_count.short_description = 'Total Slots'
    
    def availability_status(self, obj):
        """Display availability with color coding"""
        # Get available slots for a 30-minute service (smallest unit)
        available_slots = obj.get_available_slots(30, include_pending=False)
        total_slots = len(obj.get_all_timeslots())
        pending_count = obj.get_pending_count()
        
        if len(available_slots) == 0:
            return format_html('<span style="color: red;">Fully Booked</span>')
        elif len(available_slots) < total_slots / 2:
            status_text = f'{len(available_slots)}/{total_slots} available'
            if pending_count > 0:
                status_text += f' ({pending_count} pending)'
            return format_html('<span style="color: orange;">{}</span>', status_text)
        else:
            status_text = f'{len(available_slots)}/{total_slots} available'
            if pending_count > 0:
                status_text += f' ({pending_count} pending)'
            return format_html('<span style="color: green;">{}</span>', status_text)
    
    availability_status.short_description = 'Availability'
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('created_by')


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ['patient_display', 'appointment_date', 'time_range', 'service', 'status', 'assigned_dentist', 'patient_type']
    list_filter = ['status', 'patient_type', 'assigned_dentist', 'service', 'appointment_date', 'requested_at']
    search_fields = ['patient__first_name', 'patient__last_name', 'temp_first_name', 'temp_last_name', 'reason']
    readonly_fields = ['requested_at', 'confirmed_at', 'updated_at']
    date_hierarchy = 'appointment_date'
    
    fieldsets = (
        ('Appointment Details', {
            'fields': ('patient', 'service', 'appointment_date', 'start_time')
        }),
        ('Temporary Patient Data (Pending Only)', {
            'fields': ('temp_first_name', 'temp_last_name', 'temp_email', 'temp_contact_number', 'temp_address'),
            'classes': ['collapse']
        }),
        ('Assignment & Status', {
            'fields': ('status', 'assigned_dentist', 'patient_type', 'confirmed_by')
        }),
        ('Clinical Notes', {
            'fields': ('reason', 'symptoms', 'procedures', 'diagnosis', 'staff_notes'),
            'classes': ['collapse']
        }),
        ('Timestamps', {
            'fields': ('requested_at', 'confirmed_at', 'updated_at'),
            'classes': ['collapse']
        }),
    )
    
    actions = ['approve_selected_appointments', 'cancel_selected_appointments']
    
    def patient_display(self, obj):
        """Display patient name from either linked patient or temp data"""
        return obj.patient_name
    patient_display.short_description = 'Patient'
    
    def time_range(self, obj):
        """Display time range (e.g., 10:00 AM - 12:00 PM)"""
        return obj.time_display
    time_range.short_description = 'Time'
    
    def approve_selected_appointments(self, request, queryset):
        """Bulk approve selected pending appointments"""
        pending_appointments = queryset.filter(status='pending')
        
        if not pending_appointments.exists():
            self.message_user(request, "No pending appointments selected.")
            return
        
        approved_count = 0
        errors = []
        
        for appointment in pending_appointments:
            try:
                # Check timeslot availability
                is_available, message = Appointment.check_timeslot_availability(
                    appointment.appointment_date,
                    appointment.start_time,
                    appointment.service.duration_minutes,
                    exclude_appointment_id=appointment.id
                )
                
                if is_available:
                    # Auto-assign first available dentist
                    from users.models import User
                    dentist = User.objects.filter(is_active_dentist=True).first()
                    appointment.approve(request.user, dentist)
                    approved_count += 1
                else:
                    errors.append(f"{appointment.patient_name}: {message}")
                    
            except Exception as e:
                errors.append(f"{appointment.patient_name}: {str(e)}")
        
        if approved_count:
            self.message_user(request, f"Successfully approved {approved_count} appointment(s).")
        
        if errors:
            self.message_user(request, f"Errors: {'; '.join(errors)}", level='ERROR')
    
    approve_selected_appointments.short_description = "Approve selected appointments"
    
    def cancel_selected_appointments(self, request, queryset):
        """Bulk cancel selected appointments"""
        cancellable_appointments = queryset.filter(
            status__in=['pending', 'confirmed']
        )
        
        cancelled_count = 0
        for appointment in cancellable_appointments:
            if appointment.can_be_cancelled:
                appointment.cancel()
                cancelled_count += 1
        
        self.message_user(request, f"Successfully cancelled {cancelled_count} appointment(s).")
    
    cancel_selected_appointments.short_description = "Cancel selected appointments"
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'patient', 'assigned_dentist', 'service', 'confirmed_by'
        )


class PaymentItemInline(admin.TabularInline):
    model = PaymentItem
    extra = 1
    readonly_fields = ['discount_amount_display', 'total_display']
    fields = ['service', 'price', 'discount', 'notes', 'discount_amount_display', 'total_display']
    
    def discount_amount_display(self, obj):
        if obj.pk:
            return f"₱{obj.discount_amount:,.2f}"
        return "-"
    discount_amount_display.short_description = 'Discount Amount'
    
    def total_display(self, obj):
        if obj.pk:
            return f"₱{obj.total:,.2f}"
        return "-"
    total_display.short_description = 'Total'


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ['id', 'patient', 'appointment', 'total_amount', 'amount_paid', 'outstanding_balance_display', 'status', 'payment_type']
    list_filter = ['status', 'payment_type', 'created_at']
    search_fields = ['patient__first_name', 'patient__last_name', 'appointment__id']
    readonly_fields = ['created_at', 'updated_at', 'outstanding_balance', 'payment_progress_percentage']
    date_hierarchy = 'created_at'
    inlines = [PaymentItemInline]
    
    fieldsets = (
        ('Payment Details', {
            'fields': ('patient', 'appointment', 'total_amount', 'amount_paid', 'outstanding_balance', 'status')
        }),
        ('Payment Type', {
            'fields': ('payment_type', 'installment_months', 'monthly_amount', 'next_due_date')
        }),
        ('Progress', {
            'fields': ('payment_progress_percentage',)
        }),
        ('Notes', {
            'fields': ('notes',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ['collapse']
        }),
    )
    
    def outstanding_balance_display(self, obj):
        balance = obj.outstanding_balance
        if balance == 0:
            return format_html('<span style="color: green;">₱0.00 (Paid)</span>')
        elif obj.is_overdue:
            return format_html('<span style="color: red;">₱{:,.2f} (Overdue)</span>', balance)
        else:
            return format_html('₱{:,.2f}', balance)
    outstanding_balance_display.short_description = 'Balance'
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('patient', 'appointment', 'appointment__service')


@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(admin.ModelAdmin):
    list_display = ['receipt_number', 'payment', 'amount', 'payment_date', 'created_by']
    list_filter = ['payment_date', 'created_by']
    search_fields = ['receipt_number', 'payment__patient__first_name', 'payment__patient__last_name']
    readonly_fields = ['payment_datetime', 'receipt_number']
    date_hierarchy = 'payment_date'
    
    fieldsets = (
        ('Transaction Details', {
            'fields': ('payment', 'amount', 'payment_date', 'receipt_number')
        }),
        ('Notes', {
            'fields': ('notes',)
        }),
        ('Metadata', {
            'fields': ('created_by', 'payment_datetime'),
            'classes': ['collapse']
        }),
    )
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('payment', 'payment__patient', 'created_by')


# Custom admin site configuration
admin.site.site_header = "KingJoy Dental Clinic Administration"
admin.site.site_title = "Dental Clinic Admin"
admin.site.index_title = "Welcome to Dental Clinic Administration"