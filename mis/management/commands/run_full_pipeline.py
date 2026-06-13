"""
Full MIS + Performance Summary Pipeline
========================================
Calculates trips incrementally for a date range, saves them to DB,
rebuilds TripPerformanceSummary for every affected month, and stores
a full audit log in:
  - DB:  mis_full_pipeline_run table (FullPipelineRun model)
  - File: logs/mis_pipeline.log  (via mis.pipeline logger)

Run in the foreground:
  python manage.py run_full_pipeline --start 2026-01-01 --end 2026-04-08 --force

Run as a background process (logs to file automatically):
  ./scripts/run_pipeline_bg.sh --start 2026-01-01 --end 2026-04-08 --force
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

# All pipeline output goes to the dedicated mis.pipeline logger which writes
# to both console and logs/mis_pipeline.log (configured in settings.py).
logger = logging.getLogger("mis.pipeline")


def _parse_date(s: str) -> date:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        raise CommandError(f"Invalid date '{s}'. Expected YYYY-MM-DD.")


def _months_in_range(start: date, end: date):
    """Yield 'YYYY-MM' strings for every month that overlaps [start, end]."""
    cy, cm = start.year, start.month
    ey, em = end.year, end.month
    while (cy, cm) <= (ey, em):
        yield f"{cy:04d}-{cm:02d}"
        cm += 1
        if cm > 12:
            cm = 1
            cy += 1


class Command(BaseCommand):
    help = "Run trip calculation + performance summary for a date range (with DB + file audit log)"

    def add_arguments(self, parser):
        parser.add_argument("--start", required=True, type=str, help="Start date YYYY-MM-DD")
        parser.add_argument("--end", required=True, type=str, help="End date YYYY-MM-DD (inclusive)")
        parser.add_argument(
            "--vehicle", type=str, default=None,
            help="Optional: restrict to a single vehicle number",
        )
        parser.add_argument(
            "--force", action="store_true",
            help="Delete existing CalculatedTrip rows in range before recalculating",
        )

    # ------------------------------------------------------------------

    def _log(self, run, msg: str, level: str = "info"):
        """Emit msg to the pipeline file logger and the DB run log."""
        run.append_log(msg)
        getattr(logger, level)(msg)
        # Also echo to stdout so foreground runs are readable
        if level == "warning":
            self.stdout.write(self.style.WARNING(msg))
        elif level == "error":
            self.stdout.write(self.style.ERROR(msg))
        else:
            self.stdout.write(msg)

    # ------------------------------------------------------------------

    def handle(self, *args, **options):
        from mis.models import CalculatedTrip, FullPipelineRun, VehicleTripState
        from mis.services.incremental_trip_orchestrator import IncrementalTripOrchestrator
        from mis.services.trip_performance_summary_service import TripPerformanceSummaryService

        start_date = _parse_date(options["start"])
        end_date = _parse_date(options["end"])
        vehicle_no = options.get("vehicle")
        force = options.get("force", False)

        if start_date > end_date:
            raise CommandError("--start must be <= --end")

        # Create DB audit record immediately
        run = FullPipelineRun(
            start_date=start_date,
            end_date=end_date,
            vehicle_no=vehicle_no,
            status="running",
        )
        run.save()
        t0 = time.time()

        try:
            self._log(run, f"{'='*60}")
            self._log(run, f"FullPipelineRun #{run.pk} started")
            self._log(run, f"Range   : {start_date} → {end_date}")
            self._log(run, f"Vehicle : {vehicle_no or '(all)'}")
            self._log(run, f"Force   : {force}")
            self._log(run, f"Log file: logs/mis_pipeline.log")
            self._log(run, f"{'='*60}")

            # ----------------------------------------------------------
            # Step 0 — Optionally purge existing trips
            # ----------------------------------------------------------
            if force:
                qs = CalculatedTrip.objects.filter(
                    log_date__gte=start_date, log_date__lte=end_date
                )
                if vehicle_no:
                    qs = qs.filter(vehicle_no=vehicle_no)
                deleted, _ = qs.delete()
                self._log(run, f"[Force] Deleted {deleted} existing trip(s) in range.")

                # Also wipe vehicle carry-over states so trip detection starts fresh
                state_qs = VehicleTripState.objects.all()
                if vehicle_no:
                    state_qs = state_qs.filter(vehicle_no=vehicle_no)
                states_deleted, _ = state_qs.delete()
                self._log(run, f"[Force] Deleted {states_deleted} VehicleTripState row(s).")

            # ----------------------------------------------------------
            # Step 1 — Resolve vehicles
            # ----------------------------------------------------------
            if vehicle_no:
                vehicle_list = [vehicle_no]
            else:
                vehicle_list = IncrementalTripOrchestrator.get_known_vehicles()

            if not vehicle_list:
                self._log(run, "No vehicles found. Aborting.", "warning")
                run.status = "success"
                run.ended_at = timezone.now()
                run.duration_seconds = round(time.time() - t0, 2)
                run.save()
                return

            self._log(run, f"Vehicles ({len(vehicle_list)}): {', '.join(vehicle_list)}")

            # ----------------------------------------------------------
            # Step 2 — Calculate trips month by month
            # ----------------------------------------------------------
            self._log(run, "--- Step 1/3 : Calculating trips ---")
            total_calculated = 0
            total_saved = 0
            affected_months: list[str] = []

            current = start_date
            while current <= end_date:
                if current.month == 12:
                    next_month_start = date(current.year + 1, 1, 1)
                else:
                    next_month_start = date(current.year, current.month + 1, 1)

                month_start = current
                month_end = min(next_month_start - timedelta(days=1), end_date)
                month_str = current.strftime("%Y-%m")

                self._log(run, f"  [{month_str}] {month_start} → {month_end}")

                inc = IncrementalTripOrchestrator()
                # Save trips incrementally as each day is processed so that
                # progress is persisted even if the pipeline is interrupted.
                # skip_summary_rebuild=True defers the TripPerformanceSummary
                # rebuild to the bulk pass at the end of the pipeline.
                all_trips = inc.process_date_range(
                    start_date=month_start,
                    end_date=month_end,
                    vehicle_list=vehicle_list,
                    save_to_db=True,
                    skip_summary_rebuild=True,
                )

                self._log(run, f"    Calculated and saved {len(all_trips)} trip(s) for {month_str}")
                total_calculated += len(all_trips)
                total_saved += len(all_trips)
                if all_trips:
                    affected_months.append(month_str)

                current = next_month_start

            run.trips_calculated = total_calculated
            run.trips_saved = total_saved
            run.save()
            self._log(run, f"Trip phase done: calculated={total_calculated}, saved={total_saved}")

            # ----------------------------------------------------------
            # Step 3 — Rebuild TripPerformanceSummary
            # ----------------------------------------------------------
            self._log(run, "--- Step 2/3 : Rebuilding TripPerformanceSummary ---")
            all_months = list(_months_in_range(start_date, end_date))
            total_summary_vehicles = 0

            for month_str in all_months:
                updated = TripPerformanceSummaryService.build_for_month(
                    month_str, vehicle_no=vehicle_no
                )
                total_summary_vehicles += updated
                self._log(run, f"  {month_str}: {updated} vehicle(s) updated")

            run.summary_months_updated = len(all_months)
            run.summary_vehicles_updated = total_summary_vehicles
            run.save()
            self._log(run, f"Summary phase done: {len(all_months)} month(s), {total_summary_vehicles} vehicle row(s)")

            # ----------------------------------------------------------
            # Done
            # ----------------------------------------------------------
            run.status = "success"
            elapsed = round(time.time() - t0, 1)
            self._log(run, f"{'='*60}")
            self._log(run, f"Pipeline #{run.pk} completed successfully in {elapsed}s")
            self._log(run, f"{'='*60}")

        except Exception as exc:
            logger.error(f"FullPipelineRun #{run.pk} failed: {exc}", exc_info=True)
            run.status = "failed"
            run.error_message = str(exc)
            run.append_log(f"FATAL: {exc}")
            self.stdout.write(self.style.ERROR(f"Pipeline failed: {exc}"))
            raise

        finally:
            run.ended_at = timezone.now()
            run.duration_seconds = round(time.time() - t0, 2)
            run.save()
            logger.info(f"Run #{run.pk} persisted to DB. Duration: {run.duration_seconds}s")
            self.stdout.write(f"Run #{run.pk} stored in mis_full_pipeline_run. Duration: {run.duration_seconds}s")

