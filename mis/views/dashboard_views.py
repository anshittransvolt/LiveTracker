"""
MIS Dashboard Views
==================
Views for MIS dashboard and overview functionality.
"""

from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from datetime import datetime
from ..models import DailyLog


@login_required
def mis_dashboard(request):
    """MIS Dashboard with key statistics and recent logs."""
    from django.db.models import Count
    
    current_month = datetime.now().month
    current_year = datetime.now().year
    
    total_logs = DailyLog.objects.count()
    logs_this_month = DailyLog.objects.filter(
        log_date__month=current_month,
        log_date__year=current_year
    ).count()
    recent_logs = DailyLog.objects.order_by('-log_date', '-created_at')[:10]
    
    context = {
        'total_logs': total_logs,
        'logs_this_month': logs_this_month,
        'recent_logs': recent_logs,
    }
    return render(request, 'mis/dashboard.html', context)