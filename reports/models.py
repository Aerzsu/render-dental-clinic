# reports/models.py
from django.db import models

# No models needed for reports module
# All data is queried from existing models:
# - Appointment, Payment, PaymentTransaction, PaymentItem
# - Patient, Service, Discount

# IMPORTANT NOTES FOR FUTURE REFERENCE:
# ==================================================
# 1. Revenue calculations use PaymentTransaction.payment_date (actual cash received date)
#    NOT Payment.created_at (bill creation date)
#    
#    If you need to track "billing date" vs "payment date" separately in the future:
#    - Add reports that filter by Payment.created_at for "bills issued"
#    - Keep PaymentTransaction.payment_date for "cash collected"
#    - This gives you both accounts receivable AND cash flow tracking
#
# 2. Service revenue is calculated from PaymentItem.service (what was actually billed)
#    NOT from Appointment.service (what was originally booked)
#    
#    This is correct because:
#    - Patients may book wrong service
#    - Dentist can add/remove services during treatment
#    - Final bill reflects actual services provided
#
# 3. All revenue reports only count appointments with status='completed'
#    This ensures we only report on finished treatments with finalized bills
#
# ==================================================