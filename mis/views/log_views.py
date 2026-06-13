"""
MIS Daily Log Management Views
==============================
Views for CRUD operations on daily log entries.
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from ..models import DailyLog
import logging

logger = logging.getLogger(__name__)


@login_required
def manual_entry(request):
    """Create a new daily log entry."""
    if request.method == 'POST':
        try:
            log = DailyLog(
                log_date=request.POST.get('log_date'),
                driver_id=request.POST.get('driver_id') or None,
                lr=request.POST.get('lr') or None,
                from_location=request.POST.get('from_location') or None,
                trailer_no=request.POST.get('trailer_no') or None,
                horse_no=request.POST.get('horse_no') or None,
                trailer_oem=request.POST.get('trailer_oem') or None,
                delivery_no=request.POST.get('delivery_no') or None,
                tonnage_load=request.POST.get('tonnage_load') or None,
                toll_paid_manawar_jhulwania=request.POST.get('toll_paid_manawar_jhulwania') or None,
                driver_id_jhulwania=request.POST.get('driver_id_jhulwania') or None,
                trailer_no_jhulwania=request.POST.get('trailer_no_jhulwania') or None,
                horse_no_jhulwania=request.POST.get('horse_no_jhulwania') or None,
                toll_paid_jhulwania_dhule=request.POST.get('toll_paid_jhulwania_dhule') or None,
                tonnage_unload=request.POST.get('tonnage_unload') or None,
                maintenance=request.POST.get('maintenance') or None,
                created_by=request.user
            )
            log.full_clean()
            log.save()
            messages.success(request, 'Daily log entry created successfully')
            return redirect('mis:dashboard')
        except Exception as e:
            messages.error(request, f'Error creating log entry: {str(e)}')
    
    return render(request, 'mis/manual_entry.html')


@login_required
def log_detail(request, log_id):
    """View daily log details."""
    log = get_object_or_404(DailyLog, id=log_id)
    return render(request, 'mis/log_detail.html', {'log': log})


@login_required
def log_edit(request, log_id):
    """Edit an existing daily log entry."""
    log = get_object_or_404(DailyLog, id=log_id)
    
    if request.method == 'POST':
        try:
            for field in [
                'log_date', 'driver_id', 'lr', 'from_location', 'trailer_no', 'horse_no',
                'trailer_oem', 'delivery_no', 'tonnage_load', 'toll_paid_manawar_jhulwania',
                'driver_id_jhulwania', 'trailer_no_jhulwania', 'horse_no_jhulwania',
                'toll_paid_jhulwania_dhule', 'tonnage_unload', 'maintenance'
            ]:
                value = request.POST.get(field)
                if value or value == '':
                    setattr(log, field, value or None)
            
            log.full_clean()
            log.save()
            messages.success(request, 'Log entry updated successfully')
            return redirect('mis:log_detail', log_id=log_id)
        except Exception as e:
            messages.error(request, f'Error updating log entry: {str(e)}')
    
    return render(request, 'mis/log_edit.html', {'log': log})


@login_required
def log_delete(request, log_id):
    """Delete a daily log entry."""
    log = get_object_or_404(DailyLog, id=log_id)
    log.delete()
    messages.success(request, 'Log entry deleted successfully')
    return redirect('mis:dashboard')