from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from datetime import timedelta, date
from django.db.models import Count, Q
from ..models import HorseTrolleyAssignment, DriverMaster
from roster.models import TimeboxReason


@login_required
def active_drivers_report(request):
    """
    Display active drivers report with assignments
    Shows drivers who have been assigned to vehicles
    Also includes day-wise active vehicle statistics
    """
    
    # Get assignments from last 14 days to support frontend filters (today, yesterday, weekly)
    start_date = timezone.now() - timedelta(days=14)
    
    # Get the latest assignment for each active driver
    # Using distinct driver codes to avoid duplicates
    drivers_with_assignments = HorseTrolleyAssignment.objects.select_related(
        'driver', 'horse'
    ).filter(
        driver__is_active=True,
        assigned_date__gte=start_date
    ).order_by('-assigned_date')
    
    # Get unique drivers (latest assignment for each)
    seen_drivers = set()
    unique_assignments = []
    
    for assignment in drivers_with_assignments:
        driver_code = assignment.driver.employee_code
        if driver_code not in seen_drivers:
            seen_drivers.add(driver_code)
            unique_assignments.append(assignment)
    
    context = {
        'drivers': unique_assignments,
        'current_time': timezone.now(),
        'total_count': len(unique_assignments),
    }
    
    return render(request, 'reports/active_drivers.html', context)


@login_required
def timebox_delay_reasons_report(request):
    """
    Display timebox delay reasons report
    Shows all delay reasons logged with filtering and sorting capabilities
    """
    
    # Get all timebox reasons ordered by most recent first
    timebox_reasons = TimeboxReason.objects.select_related(
        'logged_by'
    ).order_by('-logged_at')
    
    # Get unique vehicles and users for filters
    unique_vehicles = timebox_reasons.values_list(
        'vehicle_number', flat=True
    ).distinct().order_by('vehicle_number')
    
    unique_users = timebox_reasons.filter(
        logged_by__isnull=False
    ).values_list(
        'logged_by__username', flat=True
    ).distinct().order_by('logged_by__username')
    
    context = {
        'timebox_reasons': timebox_reasons,
        'unique_vehicles': unique_vehicles,
        'unique_users': unique_users,
        'current_time': timezone.now(),
    }
    
    return render(request, 'reports/timebox_delay_reasons.html', context)
