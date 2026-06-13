"""
Recompute Month-to-Date Trips Cache
===================================
Runs daily (00:01) for previous day D-1:
- Fetches and stores raw for D-1
- Recomputes trips for month M = month(D-1) with 5-day lookback
- Deletes cached trips for month M, then saves fresh trips scoped to M

Usage:
  python manage.py recompute_month_cache [--date YYYY-MM-DD] [--lookback 5] [--vehicle VEHICLENO]
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
import time
from django.core.management.base import BaseCommand
from django.db import transaction

from mis.services.telemetry_fetcher import TelemetryFetcher
from mis.services.raw_storage import save_daily_raw
from mis.services.manual_entry_merger import ManualEntryMerger
from mis.models import CalculatedTrip, RecomputeRun

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Recompute month-to-date trip cache for the month of the given date (default: yesterday)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            type=str,
            help="Target date (YYYY-MM-DD). Month(D) is recomputed; defaults to yesterday",
        )
        parser.add_argument(
            "--lookback",
            type=int,
            default=5,
            help="Lookback days for continuity (default: 5)",
        )
        parser.add_argument(
            "--vehicle",
            type=str,
            default=None,
            help="Optional vehicle number filter (debugging)",
        )

    def handle(self, *args, **options):
        # Resolve target day (default yesterday)
        if options.get("date"):
            target_day = datetime.fromisoformat(options["date"]).date()
        else:
            target_day = date.today() - timedelta(days=1)
        lookback_days = int(options.get("lookback", 5))
        vehicle_no = options.get("vehicle")

        month_start = target_day.replace(day=1)
        month_end = target_day

        self.stdout.write(self.style.SUCCESS(f"Recomputing cache for {month_start:%Y-%m} up to {month_end}"))

        try:
            t0 = time.time()
            # 1) Fetch and store raw for D-1
            fetcher = TelemetryFetcher()
            self.stdout.write(f"Fetching raw for {target_day}...")
            raw_df = fetcher.fetch_range(target_day, target_day, vehicle_no)
            run = RecomputeRun(
                month=month_start,
                target_day=target_day,
                lookback_days=lookback_days,
                vehicle_no=vehicle_no,
                status='running'
            )
            run.save()
            if not raw_df.empty:
                save_daily_raw(raw_df, target_day)
                run.raw_rows = len(raw_df)
            else:
                logger.warning("No raw data fetched for target day")

            # 2) Calculate trips incrementally (state-based) for month-to-date
            from mis.services.incremental_trip_orchestrator import IncrementalTripOrchestrator
            if vehicle_no:
                vehicle_list = [vehicle_no]
            else:
                vehicle_list = IncrementalTripOrchestrator.get_known_vehicles()
            self.stdout.write(
                f"Calculating trips (incremental) for {month_start}..{month_end}, "
                f"{len(vehicle_list)} vehicle(s)"
            )
            inc_orch = IncrementalTripOrchestrator()
            trips = inc_orch.process_date_range(
                month_start, month_end, vehicle_list, save_to_db=False
            )
            run.calculated_trips = len(trips)

            # 3) Filter only trips whose log_date is within [month_start, month_end]
            trips_in_month = []
            for t in trips:
                ld = t.get("log_date")
                if not ld:
                    continue
                if isinstance(ld, datetime):
                    ld = ld.date()
                if month_start <= ld <= month_end:
                    trips_in_month.append(t)

            # 4) Transactionally replace month cache
            with transaction.atomic():
                deleted, _ = CalculatedTrip.objects.filter(
                    log_date__gte=month_start, log_date__lte=month_end
                ).delete()
                self.stdout.write(f"Deleted {deleted} trips from cache for {month_start:%Y-%m}")

                if trips_in_month:
                    saved = ManualEntryMerger().save_calculated_trips(trips_in_month)
                else:
                    saved = 0
            run.deleted_count = deleted
            run.saved_count = saved
            run.status = 'success'
            run.ended_at = datetime.now()
            run.duration_seconds = round(time.time() - t0, 2)
            run.save()

            self.stdout.write(self.style.SUCCESS(f"Saved {saved} fresh trips for {month_start:%Y-%m}"))

        except Exception as e:
            logger.error(f"Error during recompute: {e}", exc_info=True)
            try:
                run.status = 'failed'
                run.error_message = str(e)
                run.ended_at = datetime.now()
                run.duration_seconds = round(time.time() - t0, 2)
                run.save()
            except Exception:
                pass
            self.stdout.write(self.style.ERROR(f"✗ Recompute failed: {str(e)}"))
            raise
