"""
Trip Report Orchestrator
========================
Main service that coordinates trip reporting.
Fetch/calculation uses the incremental (state-based) orchestrator.
"""

import logging
import gc
import os
from datetime import date, datetime, timedelta
from typing import List, Dict, Any, Optional
from io import BytesIO

from .manual_entry_merger import ManualEntryMerger
from .report_generator_fast import ReportGenerator

logger = logging.getLogger(__name__)


class TripReportOrchestrator:
    """
    Main orchestrator for trip calculation and reporting.
    Coordinates all services to generate comprehensive reports.
    Enhanced with memory management and performance monitoring.
    """
    
    def __init__(self):
        self.merger = ManualEntryMerger()
        self.report_generator = ReportGenerator()
        
    def _log_memory_usage(self, stage: str, logger_instance: logging.Logger = None) -> None:
        """
        Log current memory usage with stage identifier.
        
        Args:
            stage: Description of the current processing stage
            logger_instance: Logger to use (defaults to module logger)
        """
        if logger_instance is None:
            logger_instance = logger
            
        try:
            import psutil
            process = psutil.Process(os.getpid())
            memory_mb = process.memory_info().rss / 1024 / 1024
            logger_instance.info(f"📊 Memory usage at {stage}: {memory_mb:.1f} MB")
        except ImportError:
            logger_instance.debug(f"📈 Memory monitoring at {stage} (psutil not available)")
        except Exception as e:
            logger_instance.debug(f"⚠️ Memory monitoring failed at {stage}: {e}")
    
    def _force_garbage_collection(self, stage: str) -> None:
        """
        Force garbage collection and log the action.
        
        Args:
            stage: Description of when GC is being triggered
        """
        logger.debug(f"🗑️ Triggering garbage collection at {stage}")
        collected = gc.collect()
        if collected > 0:
            logger.info(f"🗑️ Garbage collected {collected} objects at {stage}")
    
    def generate_report(
        self,
        start_date: date,
        end_date: date,
        report_type: str = 'daily',
        vehicle_no: Optional[str] = None,
        save_to_db: bool = True,
        use_cached: bool = True,
        lookback_days: int = 5,  # kept for API compatibility, unused
    ) -> BytesIO:
        """
        Generate a trip report.

        When use_cached=True (and cached data exists), loads directly from DB (fast).
        When use_cached=False, runs the incremental day-by-day calculation via
        IncrementalTripOrchestrator, which uses VehicleTripState carry-over rather
        than a smart-lookback API re-fetch.

        Args:
            start_date: Start date for report
            end_date: End date for report
            report_type: Type of report ('daily', 'weekly', 'monthly')
            vehicle_no: Optional specific vehicle number
            save_to_db: Whether to save calculated trips to database
            use_cached: If True, use cached database data instead of re-calculating
            lookback_days: Unused; kept for backwards-compatible call sites

        Returns:
            BytesIO object containing Excel report
        """
        logger.info(f"🚀 [Orchestrator] Starting report generation: {start_date} to {end_date}, type: {report_type}, cached: {use_cached}")
        logger.info(f"📋 [Orchestrator] Parameters - vehicle: {vehicle_no}, save_to_db: {save_to_db}, lookback_days: {lookback_days}")
        
        import time
        t_total_start = time.time()
        
        # Log initial memory usage
        self._log_memory_usage("start")
        
        try:
            if use_cached:
                logger.info("📦 [Orchestrator] Step 1: Using cached data from database (FAST MODE) 🚀")
                t_cache = time.time()
                merged_trips = self.get_merged_trips(start_date, end_date, vehicle_no)
                logger.info(f"⏱️ [Orchestrator] Cache retrieval: {time.time() - t_cache:.2f}s - Retrieved {len(merged_trips)} trips")
                self._log_memory_usage("after_cache_retrieval")
            else:
                logger.info("[Orchestrator] No cached data — running incremental calculation")
                from .incremental_trip_orchestrator import IncrementalTripOrchestrator
                if vehicle_no:
                    vehicle_list = [vehicle_no]
                else:
                    vehicle_list = IncrementalTripOrchestrator.get_known_vehicles()
                if not vehicle_list:
                    logger.warning("[Orchestrator] No known vehicles — generating empty report")
                    return self._generate_empty_report(start_date, end_date, report_type)
                inc = IncrementalTripOrchestrator()
                calculated_trips = inc.process_date_range(
                    start_date=start_date,
                    end_date=end_date,
                    vehicle_list=vehicle_list,
                    save_to_db=save_to_db,
                )
                if not calculated_trips:
                    logger.warning("[Orchestrator] No trips calculated — generating empty report")
                    return self._generate_empty_report(start_date, end_date, report_type)
                merged_trips = self.merger.merge_trips_with_logs(
                    calculated_trips, start_date, end_date
                )

            # Step 6: Generate Excel report
            logger.info("Step 6: Generating Excel report 📊")
            t_excel = time.time()
            if report_type == 'daily':
                excel_file = self.report_generator.generate_daily_report(
                    merged_trips,
                    start_date
                )
            elif report_type == 'weekly':
                excel_file = self.report_generator.generate_weekly_report(
                    merged_trips,
                    start_date,
                    end_date
                )
            elif report_type == 'monthly':
                excel_file = self.report_generator.generate_monthly_report(
                    merged_trips,
                    start_date.year,
                    start_date.month
                )
            else:
                raise ValueError(f"Invalid report type: {report_type}")

            logger.info(f"⏱️ Excel generation: {time.time() - t_excel:.2f}s")
            
            # Final cleanup
            del merged_trips
            self._force_garbage_collection("final_cleanup")
            self._log_memory_usage("after_excel_generation")
            
            logger.info(f"✅ Report generation completed in {time.time() - t_total_start:.2f}s total")
            return excel_file
            
        except Exception as e:
            logger.error(f"Error generating report: {e}", exc_info=True)
            raise
    
    def calculate_and_save_trips(
        self,
        start_date: date,
        end_date: date,
        vehicle_no: Optional[str] = None
    ) -> int:
        """
        Calculate trips incrementally (day-by-day, state-based) and save to DB.

        Returns:
            Number of trips saved
        """
        logger.info(f"Calculating and saving trips (incremental): {start_date} to {end_date}")
        from .incremental_trip_orchestrator import IncrementalTripOrchestrator
        vehicle_list = [vehicle_no] if vehicle_no else IncrementalTripOrchestrator.get_known_vehicles()
        if not vehicle_list:
            logger.warning("No known vehicles")
            return 0
        inc = IncrementalTripOrchestrator()
        trips = inc.process_date_range(
            start_date=start_date,
            end_date=end_date,
            vehicle_list=vehicle_list,
            save_to_db=True,
        )
        logger.info(f"Incremental calculation complete: {len(trips)} trips saved")
        return len(trips)

    def generate_report_incremental(
        self,
        start_date: date,
        end_date: date,
        vehicle_list: List[str],
        report_type: str = "daily",
        save_to_db: bool = True,
    ) -> BytesIO:
        """
        Generate a report using the incremental (day-by-day) fetching strategy.

        Instead of loading the entire date range at once, this method fetches one
        day per vehicle, merges it with the carry-over state stored in
        VehicleTripState, computes completed trips, and saves state for the next
        day.  Memory usage is bounded to ~1-3 days of data per vehicle regardless
        of the report date range.

        Args:
            start_date:   First day of the report.
            end_date:     Last day of the report.
            vehicle_list: Explicit list of vehicle registration numbers to process.
                          Use IncrementalTripOrchestrator.get_known_vehicles() if
                          you don't have an explicit list.
            report_type:  'daily' | 'weekly' | 'monthly'
            save_to_db:   Persist completed trips to mis_calculated_trip.

        Returns:
            BytesIO containing the Excel report.
        """
        from .incremental_trip_orchestrator import IncrementalTripOrchestrator

        logger.info(
            f"[Incremental] Generating {report_type} report: {start_date} → {end_date}, "
            f"{len(vehicle_list)} vehicle(s)"
        )

        orchestrator = IncrementalTripOrchestrator()
        calculated_trips = orchestrator.process_date_range(
            start_date=start_date,
            end_date=end_date,
            vehicle_list=vehicle_list,
            save_to_db=save_to_db,
        )

        if not calculated_trips:
            logger.warning("[Incremental] No trips calculated — generating empty report")
            return self._generate_empty_report(start_date, end_date, report_type)

        merged_trips = self.merger.merge_trips_with_logs(
            calculated_trips, start_date, end_date
        )

        if report_type == "daily":
            return self.report_generator.generate_daily_report(merged_trips, start_date)
        elif report_type == "weekly":
            return self.report_generator.generate_weekly_report(merged_trips, start_date, end_date)
        elif report_type == "monthly":
            return self.report_generator.generate_monthly_report(
                merged_trips, start_date.year, start_date.month
            )
        else:
            raise ValueError(f"Invalid report type: {report_type}")

    def get_merged_trips(
        self,
        start_date: date,
        end_date: date,
        vehicle_no: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get merged trip data from DATABASE (NO API CALLS - FAST).
        
        Args:
            start_date: Start date
            end_date: End date
            vehicle_no: Optional specific vehicle
            
        Returns:
            List of merged trip dictionaries from cache
        """
        import time
        t_start = time.time()
        
        from ..models import CalculatedTrip, DailyLog
        
        # Query from database
        # Use log_date as the canonical day key for reports (aligns with manual logs)
        query = CalculatedTrip.objects.filter(
            log_date__gte=start_date,
            log_date__lte=end_date
        )
        if vehicle_no:
            # Normalize filter to match stored format (uppercase, remove non-alphanumerics)
            from .manual_entry_merger import normalize_vehicle_no
            norm_v = normalize_vehicle_no(vehicle_no)
            query = query.filter(vehicle_no=norm_v)
        calculated_trips_qs = query.values()
        calculated_trips = list(calculated_trips_qs)
        
        logger.info(f"Retrieved {len(calculated_trips)} trips from database cache in {time.time()-t_start:.2f}s")
        
        if not calculated_trips:
            return []
        
        # Merge with manual logs
        merged_trips = self.merger.merge_trips_with_logs(
            calculated_trips,
            start_date,
            end_date
        )
        
        logger.info(f"Merged trips: {len(merged_trips)} in total {time.time()-t_start:.2f}s")
        return merged_trips

    def calculate_trips_with_lookback(
        self,
        start_date: date,
        end_date: date,
        vehicle_no: Optional[str] = None,
        lookback_days: int = 5,  # unused; kept for call-site compatibility
    ) -> List[Dict[str, Any]]:
        """Calculate trips using the incremental orchestrator and return them (no DB writes).

        Previously used smart lookback; now delegates to IncrementalTripOrchestrator
        which uses VehicleTripState carry-over instead.
        """
        logger.info(f"Calculating trips (incremental): {start_date} to {end_date}")
        from .incremental_trip_orchestrator import IncrementalTripOrchestrator
        vehicle_list = [vehicle_no] if vehicle_no else IncrementalTripOrchestrator.get_known_vehicles()
        if not vehicle_list:
            logger.warning("No known vehicles")
            return []
        inc = IncrementalTripOrchestrator()
        return inc.process_date_range(
            start_date=start_date,
            end_date=end_date,
            vehicle_list=vehicle_list,
            save_to_db=False,
        )

    def _generate_empty_report(
        self,
        start_date: date,
        end_date: date,
        report_type: str
    ) -> BytesIO:
        """Generate empty report when no data available."""
        logger.info("Generating empty report")
        
        if report_type == 'daily':
            return self.report_generator.generate_daily_report([], start_date)
        elif report_type == 'weekly':
            return self.report_generator.generate_weekly_report([], start_date, end_date)
        elif report_type == 'monthly':
            return self.report_generator.generate_monthly_report(
                [],
                start_date.year,
                start_date.month
            )
        else:
            return self.report_generator.generate_weekly_report([], start_date, end_date)