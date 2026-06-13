"""
MIS Report Generation Views
===========================
Views for generating trip reports both synchronously and asynchronously.
"""

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from datetime import datetime, date, timedelta
import logging
import os

from ..models import CalculatedTrip
from ..services.trip_report_orchestrator import TripReportOrchestrator

logger = logging.getLogger(__name__)


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
    logger.info(f"🚀 [Backend] Report download request started by user: {request.user.username}")
    logger.info(f"📋 [Backend] Request method: {request.method}")
    logger.info(f"📋 [Backend] GET parameters: {dict(request.GET.items())}")
    
    try:
        start_date_str = request.GET.get('start_date')
        end_date_str = request.GET.get('end_date')
        report_type = request.GET.get('report_type', 'daily')
        vehicle_no = request.GET.get('vehicle_no', None)
        
        logger.info(f"📊 [Backend] Parsed parameters - start: {start_date_str}, end: {end_date_str}, type: {report_type}, vehicle: {vehicle_no}")
        
        if not start_date_str or not end_date_str:
            logger.error("❌ [Backend] Missing required date parameters")
            messages.error(request, 'Start date and end date are required')
            return redirect('mis:generate_report')
        
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        
        logger.info(f"✅ [Backend] Date parsing successful - start: {start_date}, end: {end_date}")
        
        if start_date > end_date:
            logger.error("❌ [Backend] Invalid date range - start date after end date")
            messages.error(request, 'Start date must be before or equal to end date')
            return redirect('mis:generate_report')
        
        # Check if cached data exists for this date range
        logger.info("🔍 [Backend] Checking for cached data...")
        cached_count = CalculatedTrip.objects.filter(
            log_date__gte=start_date,
            log_date__lte=end_date
        ).count()
        
        use_cached = cached_count > 0
        logger.info(f"📈 [Backend] Found {cached_count} cached trips, using cached: {use_cached}")
        
        logger.info(
            f"📊 [Backend] User {request.user.username} generating {report_type} report: "
            f"{start_date} to {end_date} (cached: {cached_count} trips)"
        )

        logger.info("🏭 [Backend] Creating TripReportOrchestrator...")
        orchestrator = TripReportOrchestrator()
        
        logger.info("⚙️ [Backend] Starting report generation...")
        excel_file = orchestrator.generate_report(
            start_date=start_date,
            end_date=end_date,
            report_type=report_type,
            vehicle_no=vehicle_no,
            save_to_db=True,
            use_cached=use_cached
        )
        
        logger.info("✅ [Backend] Report generation completed successfully!")
        file_size = len(excel_file.read())
        excel_file.seek(0)  # Reset file pointer
        logger.info(f"📦 [Backend] Generated file size: {file_size} bytes ({file_size/1024:.1f} KB)")

        filename = f"trip_report_{report_type}_{start_date}_{end_date}.xlsx"
        logger.info(f"📄 [Backend] Creating response with filename: {filename}")
        
        response = HttpResponse(
            excel_file.read(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        logger.info(f"🎉 [Backend] Report generated successfully: {filename}")
        return response
        
    except Exception as e:
        logger.error(f"💥 [Backend] Error generating report: {e}", exc_info=True)
        logger.error(f"💥 [Backend] Exception type: {type(e).__name__}")
        logger.error(f"💥 [Backend] Exception details: {str(e)}")
        messages.error(request, f'Error generating report: {str(e)}')
        return redirect('mis:generate_report')


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
        from ..tasks import generate_report_async
        
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


@login_required
def download_report_incremental(request):
    """
    Generate and download a report using the incremental (day-by-day) strategy.

    Query params (same as download_report):
      - start_date  YYYY-MM-DD
      - end_date    YYYY-MM-DD
      - report_type daily | weekly | monthly  (default: daily)
      - vehicle_no  optional single vehicle registration number

    Fetches one day at a time per vehicle and carries in-progress trip state
    across day boundaries via VehicleTripState, bounding memory usage to ~1-3
    days of trip data per vehicle regardless of the total date range requested.
    """
    try:
        start_date_str = request.GET.get("start_date")
        end_date_str = request.GET.get("end_date")
        report_type = request.GET.get("report_type", "daily")
        vehicle_no = request.GET.get("vehicle_no") or None

        if not start_date_str or not end_date_str:
            messages.error(request, "Start date and end date are required")
            return redirect("mis:generate_report")

        start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
        end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()

        if start_date > end_date:
            messages.error(request, "Start date must be before or equal to end date")
            return redirect("mis:generate_report")

        from ..services.incremental_trip_orchestrator import IncrementalTripOrchestrator

        if vehicle_no:
            vehicle_list = [vehicle_no]
        else:
            vehicle_list = IncrementalTripOrchestrator.get_known_vehicles()
            if not vehicle_list:
                messages.error(request, "No known vehicles found. Please specify a vehicle number.")
                return redirect("mis:generate_report")

        logger.info(
            f"User {request.user.username} starting incremental report: "
            f"{start_date} → {end_date}, {len(vehicle_list)} vehicle(s), type={report_type}"
        )

        orchestrator = TripReportOrchestrator()
        excel_file = orchestrator.generate_report_incremental(
            start_date=start_date,
            end_date=end_date,
            vehicle_list=vehicle_list,
            report_type=report_type,
            save_to_db=True,
        )

        filename = f"trip_report_incremental_{report_type}_{start_date}_{end_date}.xlsx"
        response = HttpResponse(
            excel_file.read(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        logger.info(f"Incremental report generated: {filename}")
        return response

    except Exception as e:
        logger.error(f"Error generating incremental report: {e}", exc_info=True)
        messages.error(request, f"Error generating report: {str(e)}")
        return redirect("mis:generate_report")