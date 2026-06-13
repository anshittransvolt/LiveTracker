"""
MIS API Views
=============
API endpoints for MIS functionality.
"""

from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from datetime import date, timedelta
import logging

from ..models import CalculatedTrip
from ..services.trip_report_orchestrator import TripReportOrchestrator

logger = logging.getLogger(__name__)


@require_http_methods(["GET"])
def quick_report_status(request):
    """Check if trips are cached in database for the last 7 days."""
    end_date = date.today()
    start_date = end_date - timedelta(days=7)
    
    count = CalculatedTrip.objects.filter(
        log_date__gte=start_date,
        log_date__lte=end_date
    ).count()
    
    return JsonResponse({
        'status': 'ready' if count > 0 else 'no_data',
        'trip_count': count,
        'date_range': {
            'start': str(start_date),
            'end': str(end_date),
        }
    })


@require_http_methods(["GET"])
def download_cached_report(request):
    """Fast report download from cached database (2-3 seconds)."""
    try:
        end_date = date.today()
        start_date = end_date - timedelta(days=7)
        orchestrator = TripReportOrchestrator()
        # Use merged trips so manual logs uploaded later are included by (log_date, horse_no)
        trips = orchestrator.get_merged_trips(start_date, end_date)
        if not trips:
            return JsonResponse({'error': 'No cached trips available'}, status=404)
        excel_file = orchestrator.report_generator.generate_daily_report(trips, start_date)
        
        response = HttpResponse(
            excel_file.read(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = f'attachment; filename="cached_report_{start_date}_{end_date}.xlsx"'
        
        return response
        
    except Exception as e:
        logger.error(f"Error downloading cached report: {e}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)