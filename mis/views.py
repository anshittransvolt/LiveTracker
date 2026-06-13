"""
MIS (Management Information System) Views
==========================================
Core views for trip reports, daily logs, and analytics.
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt

from .models import DailyLog, CalculatedTrip
from .services.trip_report_orchestrator import TripReportOrchestrator

from datetime import datetime, date, timedelta
import logging
import os

logger = logging.getLogger(__name__)


# ===== DASHBOARD =====

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


# ===== DAILY LOG MANAGEMENT =====

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


# ===== REPORT GENERATION =====

@login_required
def generate_report_view(request):
    """Report generation page with date range and type selection."""
    context = {
        'today': date.today(),
        'week_ago': date.today() - timedelta(days=7),
    }
    return render(request, 'mis/generate_report.html', context)


@login_required
def download_report(request):
    """Generate and download trip report based on selected date range."""
    try:
        start_date_str = request.GET.get('start_date')
        end_date_str = request.GET.get('end_date')
        report_type = request.GET.get('report_type', 'daily')
        vehicle_no = request.GET.get('vehicle_no', None)
        
        if not start_date_str or not end_date_str:
            messages.error(request, 'Start date and end date are required')
            return redirect('mis:generate_report')
        
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        
        if start_date > end_date:
            messages.error(request, 'Start date must be before or equal to end date')
            return redirect('mis:generate_report')
        
        # Check if cached data exists for this date range
        cached_count = CalculatedTrip.objects.filter(
            log_date__gte=start_date,
            log_date__lte=end_date
        ).count()
        
        # Use cached data if available, or calculate if needed
        date_range_days = (end_date - start_date).days + 1
        use_cached = cached_count > 0
        
        
        logger.info(
            f"User {request.user.username} generating {report_type} report: "
            f"{start_date} to {end_date} (cached: {cached_count} trips)"
        )
        
        orchestrator = TripReportOrchestrator()
        excel_file = orchestrator.generate_report(
            start_date=start_date,
            end_date=end_date,
            report_type=report_type,
            vehicle_no=vehicle_no,
            save_to_db=True,
            use_cached=use_cached
        )
        
        filename = f"trip_report_{report_type}_{start_date}_{end_date}.xlsx"
        response = HttpResponse(
            excel_file.read(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        logger.info(f"Report generated successfully: {filename}")
        return response
        
    except Exception as e:
        logger.error(f"Error generating report: {e}", exc_info=True)
        messages.error(request, f'Error generating report: {str(e)}')
        return redirect('mis:generate_report')


# ===== ASYNC REPORT GENERATION =====

@login_required
@require_http_methods(["POST"])
def generate_report_async(request):
    """
    Start background report generation task.
    Returns task ID for progress tracking.
    """
    try:
        start_date_str = request.POST.get('start_date')
        end_date_str = request.POST.get('end_date')
        report_type = request.POST.get('report_type', 'daily')
        vehicle_no = request.POST.get('vehicle_no', None)
        
        if not start_date_str or not end_date_str:
            return JsonResponse({'error': 'Start date and end date are required'}, status=400)
        
        # Validate dates
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        except ValueError:
            return JsonResponse({'error': 'Invalid date format. Use YYYY-MM-DD'}, status=400)
        
        if start_date > end_date:
            return JsonResponse({'error': 'Start date must be before or equal to end date'}, status=400)
        
        # Check date range (prevent extremely long ranges)
        date_range_days = (end_date - start_date).days + 1
        if date_range_days > 90:  # Limit to 3 months
            return JsonResponse({
                'error': f'Date range too large ({date_range_days} days). Maximum allowed is 90 days.'
            }, status=400)
        
        logger.info(
            f"User {request.user.username} starting async report generation: "
            f"{start_date} to {end_date} ({date_range_days} days), type: {report_type}"
        )
        
        # Import and start the Celery task
        from .tasks import generate_report_async
        
        task = generate_report_async.delay(
            start_date_str=start_date_str,
            end_date_str=end_date_str,
            report_type=report_type,
            vehicle_no=vehicle_no,
            user_id=request.user.id
        )
        
        logger.info(f"Started background task {task.id} for user {request.user.username}")
        
        return JsonResponse({
            'success': True,
            'task_id': task.id,
            'message': 'Report generation started in background',
            'date_range': f'{start_date} to {end_date}',
            'report_type': report_type,
            'estimated_time': '2-5 minutes'
        })
        
    except Exception as e:
        logger.error(f"Error starting async report generation: {e}", exc_info=True)
        return JsonResponse({'error': f'Failed to start report generation: {str(e)}'}, status=500)


@login_required
@require_http_methods(["GET"])
def report_task_status(request, task_id):
    """
    Check the status of a background report generation task.
    """
    try:
        from celery.result import AsyncResult
        
        task_result = AsyncResult(task_id)
        
        if task_result.state == 'PENDING':
            response = {
                'state': task_result.state,
                'status': 'Task is waiting in queue...',
                'progress': 0
            }
        elif task_result.state == 'PROGRESS':
            response = {
                'state': task_result.state,
                'status': task_result.info.get('status', 'Processing...'),
                'progress': task_result.info.get('progress', 0)
            }
        elif task_result.state == 'SUCCESS':
            response = {
                'state': task_result.state,
                'status': 'Report generation completed!',
                'progress': 100,
                'result': task_result.info
            }
        else:  # FAILURE or other error states
            response = {
                'state': task_result.state,
                'status': 'Report generation failed',
                'progress': 0,
                'error': str(task_result.info) if task_result.info else 'Unknown error'
            }
        
        return JsonResponse(response)
        
    except Exception as e:
        logger.error(f"Error checking task status {task_id}: {e}", exc_info=True)
        return JsonResponse({
            'state': 'ERROR',
            'status': 'Failed to check task status',
            'error': str(e)
        }, status=500)


@login_required
@require_http_methods(["GET"])
def download_async_report(request, task_id):
    """
    Download the generated report file from a completed async task.
    """
    try:
        from celery.result import AsyncResult
        from django.core.cache import cache
        
        task_result = AsyncResult(task_id)
        
        if task_result.state != 'SUCCESS':
            return JsonResponse({
                'error': f'Task not completed. Current state: {task_result.state}'
            }, status=400)
        
        # Get file info from cache
        cache_key = f"report_file_{task_id}"
        file_info = cache.get(cache_key)
        
        if not file_info:
            return JsonResponse({
                'error': 'Report file not found or expired. Please regenerate the report.'
            }, status=404)
        
        file_path = file_info['file_path']
        filename = file_info['filename']
        
        # Check if file still exists
        if not os.path.exists(file_path):
            return JsonResponse({
                'error': 'Report file has been cleaned up. Please regenerate the report.'
            }, status=404)
        
        logger.info(f"User {request.user.username} downloading async report: {filename}")
        
        # Serve the file
        with open(file_path, 'rb') as f:
            response = HttpResponse(
                f.read(),
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            
        # Clean up the file after successful download
        try:
            os.unlink(file_path)
            cache.delete(cache_key)
            logger.info(f"Cleaned up report file: {file_path}")
        except Exception as cleanup_error:
            logger.warning(f"Failed to cleanup file {file_path}: {cleanup_error}")
        
        return response
        
    except Exception as e:
        logger.error(f"Error downloading async report {task_id}: {e}", exc_info=True)
        return JsonResponse({'error': f'Failed to download report: {str(e)}'}, status=500)


# ===== CACHE & CALCULATION =====

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


# ===== API ENDPOINTS =====

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


# ===== EXCEL UPLOAD =====

@login_required
@require_http_methods(["POST"])
def upload_excel(request):
    """Handle Excel file upload for bulk daily log entries (flexible headers)."""
    from .services.manual_entry_merger import ManualEntryMerger
    import tempfile, os
    try:
        if 'excel_file' not in request.FILES:
            messages.error(request, 'No Excel file provided')
            return redirect('mis:dashboard')

        excel_file = request.FILES['excel_file']

        # Save to a temporary file to pass to pandas importer
        with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp:
            for chunk in excel_file.chunks():
                tmp.write(chunk)
            temp_path = tmp.name

        merger = ManualEntryMerger()
        imported_count = merger.import_daily_logs_from_excel(temp_path)

        # Clean up temp file
        try:
            os.unlink(temp_path)
        except Exception:
            pass

        if imported_count > 0:
            messages.success(request, f'Successfully imported {imported_count} daily logs')
        else:
            messages.warning(request, 'No rows imported. Please verify headers and data formats.')

        logger.info(f"Excel upload: {imported_count} imported by {request.user}")
        return redirect('mis:dashboard')

    except Exception as e:
        logger.error(f"Error uploading Excel file: {e}", exc_info=True)
        messages.error(request, f'Error processing Excel file: {str(e)}')
        return redirect('mis:dashboard')


# ===== TEMPLATE DOWNLOAD =====

@login_required
@require_http_methods(["GET"])
def download_manual_template(request):
    """Generate and download the manual logs Excel template.

    Query params:
    - date: YYYY-MM-DD (defaults to today)
    - horse: vehicle/horse number string (defaults to 'MH 18 BZ 0000')
    - variant: '1' to use headers 'Date' and 'Vehicle No', else 'Log Date' and 'Horse No'
    """
    try:
        import pandas as pd
        from datetime import datetime, date as _date
        
        date_str = request.GET.get('date')
        horse_no = request.GET.get('horse', 'MH 18 BZ 0000')
        variant = request.GET.get('variant', '0') == '1'

        if date_str:
            try:
                dt = datetime.fromisoformat(date_str).date()
            except ValueError:
                messages.warning(request, 'Invalid date format; expected YYYY-MM-DD. Using today.')
                dt = _date.today()
        else:
            dt = _date.today()

        date_col = "Date" if variant else "Log Date"
        horse_col = "Vehicle No" if variant else "Horse No"

        row = {
            date_col: dt,
            horse_col: horse_no,
            "Trailer No": "TR-XXX",
            "Driver ID": "DRV-001",
            "LR": "LR-123",
            "Trailer OEM": "OEM-Brand",
            "Delivery No": "DEL-001",
            "Driver ID (Jhulwania)": "DRV-002",
            "Trailer No (Jhulwania)": "TR-YYY",
            "Horse No (Jhulwania)": "MH 18 BZ 0001",
            "Tonnage Load": 22.5,
            "Tonnage Unload": 22.0,
            "Toll Paid (Manawar to Jhulwania)": 300.0,
            "Toll Paid (Jhulwania to Dhule)": 400.0,
            "Maintenance": "OK",
        }

        df = pd.DataFrame([row])
        from io import BytesIO
        bio = BytesIO()
        # Use pandas to_excel (uses openpyxl/xlsxwriter depending on env)
        df.to_excel(bio, index=False)
        bio.seek(0)

        filename = f"manual_logs_template_{dt.isoformat()}.xlsx"
        response = HttpResponse(
            bio.read(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response
    
    except Exception as e:
        logger.error(f"Error generating manual template: {e}", exc_info=True)
        messages.error(request, f'Error generating template: {str(e)}')
        return redirect('mis:dashboard')


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
