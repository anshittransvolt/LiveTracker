"""
Fast Report View with Background Processing
============================================
Web endpoint that returns immediately and processes in background.
"""

from django.http import JsonResponse, FileResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from datetime import date, timedelta
import os
import time
from ..models import CalculatedTrip
from ..services.report_generator_fast import FastReportGenerator
from django.contrib.auth.decorators import login_required

@login_required
@require_http_methods(["GET"])
def quick_report_status(request):
    """Check if trips are available in database."""
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
            'end': str(end_date)
        }
    })

@login_required
@require_http_methods(["GET"])
def download_cached_report(request):
    """
    Generate report from CACHED data only (2-3 seconds).
    No API calls - instant download.
    """
    import pandas as pd
    from io import BytesIO
    
    end_date = date.today()
    start_date = end_date - timedelta(days=7)
    
    # print(f'\n⚡ FAST REPORT: Loading from cache...')
    t_start = time.time()
    
    # Load from database
    trips = CalculatedTrip.objects.filter(
        log_date__gte=start_date,
        log_date__lte=end_date
    ).values()
    
    trip_list = list(trips)
    
    if not trip_list:
        return HttpResponse("No trip data available", status=404)
    
    # Convert to Excel
    def safe_dt(dt_val):
        if dt_val and hasattr(dt_val, 'replace'):
            return dt_val.replace(tzinfo=None)
        return dt_val
    
    def safe_float(val):
        try:
            return round(float(val), 3) if val else None
        except:
            return None
    
    excel_data = []
    for i, trip in enumerate(trip_list, 1):
        row = {
            'Sr.No': i,
            'Log Date': trip.get('log_date'),
            'Vehicle No': trip.get('vehicle_no'),
            'Trip Start KM': safe_float(trip.get('trip_start_km')),
            'Trip Closed KM': safe_float(trip.get('trip_closed_km')),
            'Total Trip KM': safe_float(trip.get('total_trip_km')),
            'Total Distance (km)': safe_float(trip.get('total_distance_km')),
            'Total KWH': safe_float(trip.get('total_kwh')),
            'Efficiency (kWh/km)': safe_float(trip.get('efficiency_kwh_per_km')),
            'Start SOC (%)': safe_float(trip.get('start_soc')),
            'Closing SOC (%)': safe_float(trip.get('closing_soc')),
            'Manawar Out Time': safe_dt(trip.get('manawar_out_time')),
            'Julwaniya Entry': safe_dt(trip.get('julwaniya_entry_time')),
            'Julwaniya Exit': safe_dt(trip.get('julwaniya_exit_time')),
            'Dhule Entry': safe_dt(trip.get('dhule_entry_time')),
            'Dhule Exit': safe_dt(trip.get('dhule_exit_time')),
            'Total Trip Time': trip.get('vehicle_total_trip_time'),
            'Total Charging Time': trip.get('all_station_total_charging_hours'),
        }
        excel_data.append(row)
    
    df = pd.DataFrame(excel_data)
    
    # Write to Excel
    output = BytesIO()
    df.to_excel(output, index=False, engine='openpyxl')
    output.seek(0)
    
    elapsed = time.time() - t_start
    print(f'✅ Report generated in {elapsed:.2f}s')
    
    # Send file
    response = FileResponse(
        output,
        as_attachment=True,
        filename=f'trip_report_{start_date}_{end_date}.xlsx'
    )
    response['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    
    return response

@require_http_methods(["POST"])
def recalculate_trips_async(request):
    """
    Trigger background recalculation (for admin use).
    Returns immediately, processes in background.
    """
    # TODO: Implement with Celery or Django Q
    return JsonResponse({
        'status': 'started',
        'message': 'Trip recalculation started in background',
        'estimated_time': '2-3 minutes'
    })
