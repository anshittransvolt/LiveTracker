from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
import time
import gc
import os
from django.db import transaction
from django.core.cache import cache
from celery import shared_task
from io import BytesIO
import tempfile

from .services.telemetry_fetcher import TelemetryFetcher
from .services.raw_storage import save_daily_raw
from .services.trip_report_orchestrator import TripReportOrchestrator
from .models import CalculatedTrip, RecomputeRun

logger = logging.getLogger(__name__)


@shared_task(bind=True, name="mis.tasks.generate_report_async")
def generate_report_async(self, start_date_str, end_date_str, report_type='daily', vehicle_no=None, user_id=None):
    """
    Background task to generate MIS report with memory optimization.
    
    Args:
        start_date_str: Start date in YYYY-MM-DD format
        end_date_str: End date in YYYY-MM-DD format
        report_type: Type of report ('daily', 'weekly', 'monthly')
        vehicle_no: Optional specific vehicle number
        user_id: User ID for logging purposes
    
    Returns:
        dict: Task result with success/error status and file info
    """
    task_id = self.request.id
    logger.info(f"🚀 [Task {task_id}] Starting background report generation")
    
    # Update task progress
    self.update_state(state='PROGRESS', meta={'status': 'Initializing...', 'progress': 0})
    
    try:
        # Parse dates
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        
        date_range_days = (end_date - start_date).days + 1
        logger.info(f"📊 [Task {task_id}] Report parameters: {start_date} to {end_date} ({date_range_days} days), type: {report_type}")
        
        # Memory usage monitoring
        def log_memory_usage(stage):
            try:
                import psutil
                process = psutil.Process(os.getpid())
                memory_mb = process.memory_info().rss / 1024 / 1024
                logger.info(f"💾 [Task {task_id}] Memory usage at {stage}: {memory_mb:.1f} MB")
            except ImportError:
                logger.debug(f"📊 [Task {task_id}] Memory monitoring not available (psutil not installed)")
        
        log_memory_usage("start")
        
        # Check for cached data
        self.update_state(state='PROGRESS', meta={'status': 'Checking cached data...', 'progress': 10})
        
        cached_count = CalculatedTrip.objects.filter(
            log_date__gte=start_date,
            log_date__lte=end_date
        ).count()
        
        use_cached = cached_count > 0
        
        logger.info(f"📈 [Task {task_id}] Found {cached_count} cached trips, using cached: {use_cached}")
        
        # Force garbage collection before heavy operations
        gc.collect()
        log_memory_usage("before_orchestrator")
        
        # Generate report with timing
        self.update_state(state='PROGRESS', meta={'status': 'Generating report...', 'progress': 20})
        
        t_start = time.time()
        orchestrator = TripReportOrchestrator()
        
        try:
            excel_file = orchestrator.generate_report(
                start_date=start_date,
                end_date=end_date,
                report_type=report_type,
                vehicle_no=vehicle_no,
                save_to_db=True,
                use_cached=use_cached
            )
            
            generation_time = time.time() - t_start
            logger.info(f"⏱️ [Task {task_id}] Report generation completed in {generation_time:.2f}s")
            
        except Exception as e:
            logger.error(f"💥 [Task {task_id}] Report generation failed: {str(e)}", exc_info=True)
            raise
        
        log_memory_usage("after_report_generation")
        
        # Save to temporary file with unique name
        self.update_state(state='PROGRESS', meta={'status': 'Saving file...', 'progress': 80})
        
        filename = f"trip_report_{report_type}_{start_date}_{end_date}_{task_id[:8]}.xlsx"
        
        # Use Django's temp directory
        temp_dir = tempfile.gettempdir()
        temp_file_path = os.path.join(temp_dir, filename)
        
        try:
            with open(temp_file_path, 'wb') as f:
                f.write(excel_file.read())
            
            file_size_mb = os.path.getsize(temp_file_path) / 1024 / 1024
            logger.info(f"💾 [Task {task_id}] File saved: {temp_file_path} ({file_size_mb:.2f} MB)")
            
        except Exception as e:
            logger.error(f"💥 [Task {task_id}] Failed to save file: {str(e)}")
            raise
        
        # Clean up memory
        del excel_file
        del orchestrator
        gc.collect()
        log_memory_usage("after_cleanup")
        
        # Store file path in cache for retrieval (expire in 1 hour)
        cache_key = f"report_file_{task_id}"
        cache.set(cache_key, {
            'file_path': temp_file_path,
            'filename': filename,
            'size_mb': file_size_mb,
            'created_at': time.time()
        }, timeout=3600)  # 1 hour
        
        total_time = time.time() - t_start
        
        result = {
            'status': 'success',
            'message': f'Report generated successfully in {total_time:.1f}s',
            'filename': filename,
            'size_mb': round(file_size_mb, 2),
            'cached_trips': cached_count,
            'generation_time_s': round(generation_time, 2),
            'total_time_s': round(total_time, 2),
            'date_range': f"{start_date} to {end_date}",
            'report_type': report_type
        }
        
        logger.info(f"✅ [Task {task_id}] Background report generation completed successfully")
        
        # Final progress update
        self.update_state(state='SUCCESS', meta=result)
        
        return result
        
    except Exception as e:
        error_msg = f"Report generation failed: {str(e)}"
        logger.error(f"💥 [Task {task_id}] {error_msg}", exc_info=True)
        
        # Clean up any partial files
        if 'temp_file_path' in locals() and os.path.exists(temp_file_path):
            try:
                os.unlink(temp_file_path)
                logger.info(f"🗑️ [Task {task_id}] Cleaned up partial file: {temp_file_path}")
            except Exception as cleanup_error:
                logger.warning(f"⚠️ [Task {task_id}] Failed to cleanup file: {cleanup_error}")
        
        # Force garbage collection on error
        gc.collect()
        
        result = {
            'status': 'error',
            'message': error_msg,
            'error_type': type(e).__name__
        }
        
        self.update_state(state='FAILURE', meta=result)
        
        # Re-raise the exception so Celery marks it as failed
        raise


@shared_task(name="mis.tasks.recompute_month_cache_task")
def recompute_month_cache_task(target_iso_date: str | None = None, lookback_days: int = 5):
    """Celery task to recompute month-to-date cache with 5-day lookback.

    Args:
        target_iso_date: optional YYYY-MM-DD (defaults to yesterday)
        lookback_days: days to look back for continuity
    """
    # Resolve target day (default yesterday)
    if target_iso_date:
        target_day = datetime.fromisoformat(target_iso_date).date()
    else:
        target_day = date.today() - timedelta(days=1)

    month_start = target_day.replace(day=1)
    month_end = target_day

    logger.info(f"[Recompute] Month={month_start:%Y-%m} TargetDay={target_day} Lookback={lookback_days}")

    run = RecomputeRun(
        month=month_start,
        target_day=target_day,
        lookback_days=lookback_days,
        status='running'
    )
    run.save()
    t0 = time.time()

    # 1) Fetch and store raw for target day
    fetcher = TelemetryFetcher()
    raw_df = fetcher.fetch_range(target_day, target_day, None)
    if not raw_df.empty:
        save_daily_raw(raw_df, target_day)
        run.raw_rows = len(raw_df)
    else:
        logger.warning("[Recompute] No raw data fetched for target day")

    # 2) Calculate trips with lookback for month-to-date
    orch = TripReportOrchestrator()
    trips = orch.calculate_trips_with_lookback(month_start, month_end, vehicle_no=None, lookback_days=lookback_days)
    run.telemetry_rows = sum(1 for _ in [] )  # placeholder; we don't expose telemetry rows directly here
    run.calculated_trips = len(trips)

    # 3) Filter trips to month
    trips_in_month = []
    for t in trips:
        ld = t.get("log_date")
        if not ld:
            continue
        if isinstance(ld, datetime):
            ld = ld.date()
        if month_start <= ld <= month_end:
            trips_in_month.append(t)

    # 4) Replace month cache transactionally
    try:
        with transaction.atomic():
            deleted, _ = CalculatedTrip.objects.filter(log_date__gte=month_start, log_date__lte=month_end).delete()
            logger.info(f"[Recompute] Deleted {deleted} trips for {month_start:%Y-%m}")
            saved = 0
            if trips_in_month:
                saved = orch.merger.save_calculated_trips(trips_in_month)
        run.deleted_count = deleted
        run.saved_count = saved
        logger.info(f"[Recompute] Saved {saved} trips for {month_start:%Y-%m}")
        return {"month": f"{month_start:%Y-%m}", "deleted": deleted, "saved": saved}
    except Exception as e:
        run.status = 'failed'
        run.error_message = str(e)
        run.ended_at = datetime.now()
        run.duration_seconds = round(time.time() - t0, 2)
        run.save()
        raise
    finally:
        if run.status != 'failed':
            run.status = 'success'
        run.ended_at = datetime.now()
        run.duration_seconds = round(time.time() - t0, 2)
        run.save()
