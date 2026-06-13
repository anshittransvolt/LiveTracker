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
    
    # Get the latest assignment for each active driver
    # Using distinct driver codes to avoid duplicates
    drivers_with_assignments = HorseTrolleyAssignment.objects.select_related(
        'driver', 'horse'
    ).filter(
        driver__is_active=True
    ).order_by('-assigned_date')
    
    # Get unique drivers (latest assignment for each)
    seen_drivers = set()
    unique_assignments = []
    
    for assignment in drivers_with_assignments:
        driver_code = assignment.driver.employee_code
        if driver_code not in seen_drivers:
            seen_drivers.add(driver_code)
            unique_assignments.append(assignment)
    
    # Day-wise active vehicles (last 7 days)
    today = date.today()
    day_wise_stats = []
    
    for days_ago in range(6, -1, -1):  # Last 7 days in chronological order
        target_date = today - timedelta(days=days_ago)
        
        # Get assignments for this date
        assignments_on_date = HorseTrolleyAssignment.objects.filter(
            assigned_date__date=target_date,
            driver__is_active=True
        ).select_related('horse', 'driver')
        
        # Count unique vehicles
        unique_vehicles = assignments_on_date.values('horse__horse_number').distinct().count()
        unique_drivers_count = assignments_on_date.values('driver__employee_code').distinct().count()
        
        # Route breakdown
        dhar_to_dhule = assignments_on_date.filter(route='DHAR_TO_DHULE').count()
        dhule_to_dhar = assignments_on_date.filter(route='DHULE_TO_DHAR').count()
        
        day_wise_stats.append({
            'date': target_date,
            'day_name': target_date.strftime('%A'),
            'unique_vehicles': unique_vehicles,
            'unique_drivers': unique_drivers_count,
            'total_assignments': assignments_on_date.count(),
            'dhar_to_dhule': dhar_to_dhule,
            'dhule_to_dhar': dhule_to_dhar,
            'is_today': target_date == today,
        })
    
    context = {
        'drivers': unique_assignments,
        'current_time': timezone.now(),
        'total_count': len(unique_assignments),
        'day_wise_stats': day_wise_stats,
    }
    
    return render(request, 'reports/active_drivers.html', context)


@login_required
def active_vehicles_report(request):
    """
    Display active vehicles report with assignments
    Shows vehicles (horses) that have been assigned to drivers
    Also includes day-wise active vehicle statistics
    """
    
    # Get the latest assignment for each active vehicle
    # Using distinct horse numbers to avoid duplicates
    vehicles_with_assignments = HorseTrolleyAssignment.objects.select_related(
        'horse', 'driver'
    ).filter(
        driver__is_active=True
    ).order_by('-assigned_date')
    
    # Get unique vehicles (latest assignment for each)
    seen_vehicles = set()
    unique_assignments = []
    
    for assignment in vehicles_with_assignments:
        horse_number = assignment.horse.horse_number
        if horse_number not in seen_vehicles:
            seen_vehicles.add(horse_number)
            unique_assignments.append(assignment)
    
    # Day-wise active vehicles (last 7 days)
    today = date.today()
    day_wise_stats = []
    
    for days_ago in range(6, -1, -1):  # Last 7 days in chronological order
        target_date = today - timedelta(days=days_ago)
        
        # Get assignments for this date
        assignments_on_date = HorseTrolleyAssignment.objects.filter(
            assigned_date__date=target_date,
            driver__is_active=True
        ).select_related('horse', 'driver')
        
        # Count unique vehicles
        unique_vehicles = assignments_on_date.values('horse__horse_number').distinct().count()
        unique_drivers_count = assignments_on_date.values('driver__employee_code').distinct().count()
        
        # Route breakdown
        dhar_to_dhule = assignments_on_date.filter(route='DHAR_TO_DHULE').count()
        dhule_to_dhar = assignments_on_date.filter(route='DHULE_TO_DHAR').count()
        
        day_wise_stats.append({
            'date': target_date,
            'day_name': target_date.strftime('%A'),
            'unique_vehicles': unique_vehicles,
            'unique_drivers': unique_drivers_count,
            'total_assignments': assignments_on_date.count(),
            'dhar_to_dhule': dhar_to_dhule,
            'dhule_to_dhar': dhule_to_dhar,
            'is_today': target_date == today,
        })
    
    context = {
        'vehicles': unique_assignments,
        'current_time': timezone.now(),
        'total_count': len(unique_assignments),
        'day_wise_stats': day_wise_stats,
    }
    
    return render(request, 'reports/active_vehicles.html', context)


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
