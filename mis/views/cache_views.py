"""
MIS Cache Management Views
==========================
Views for managing trip calculation cache and background processing.
"""

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from datetime import datetime, date, timedelta
import logging

from ..models import CalculatedTrip
from ..services.trip_report_orchestrator import TripReportOrchestrator

logger = logging.getLogger(__name__)


@login_required
def calculate_daily_cache(request):
    """Manually trigger daily calculation to cache trips for yesterday and today."""
    try:
        from django.core.management import call_command
        
        days = request.GET.get('days', 2)
        force = request.GET.get('force', 'false').lower() == 'true'
        
        logger.info(f"User {request.user.username} triggered daily cache calculation")
        
        call_command(
            'calculate_daily_trips',
            days=int(days),
            force=force,
            verbosity=2
        )
        
        today = date.today()
        cached_count = CalculatedTrip.objects.filter(
            log_date__gte=today - timedelta(days=int(days)-1),
            log_date__lte=today
        ).count()
        
        return JsonResponse({
            'success': True,
            'message': f'Daily cache calculation completed. {cached_count} trips cached.',
            'cached_trips': cached_count
        })
        
    except Exception as e:
        logger.error(f"Error in daily cache calculation: {e}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def calculate_trips_background(request):
    """Calculate trips for a date range and save to database."""
    try:
        start_date_str = request.POST.get('start_date')
        end_date_str = request.POST.get('end_date')
        vehicle_no = request.POST.get('vehicle_no', None)
        
        if not start_date_str or not end_date_str:
            return JsonResponse({'error': 'Start date and end date are required'}, status=400)
        
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        
        orchestrator = TripReportOrchestrator()
        saved_count = orchestrator.calculate_and_save_trips(
            start_date=start_date,
            end_date=end_date,
            vehicle_no=vehicle_no
        )
        
        return JsonResponse({
            'success': True,
            'message': f'Successfully calculated and saved {saved_count} trips',
            'count': saved_count
        })
        
    except Exception as e:
        logger.error(f"Error calculating trips: {e}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@login_required
def clear_trip_cache(request):
    """Clear all calculated trips from the cache/database."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    try:
        deleted, _ = CalculatedTrip.objects.all().delete()
        logger.info(f"User {request.user.username} cleared all calculated trips cache ({deleted} records deleted)")
        return JsonResponse({
            'success': True,
            'message': f'Cleared {deleted} cached trips.'
        })
    except Exception as e:
        logger.error(f"Error clearing trip cache: {e}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)