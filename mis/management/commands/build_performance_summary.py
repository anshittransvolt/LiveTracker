"""
Management command to build monthly trip performance summaries.

Examples:
  Build for a single month:
    python manage.py build_performance_summary --month 2026-03

  Build for a date range:
    python manage.py build_performance_summary --start-month 2026-01 --end-month 2026-03

  Rebuild for a specific vehicle:
    python manage.py build_performance_summary --month 2026-03 --vehicle MH15GB0001

  Build for all months present in CalculatedTrip:
    python manage.py build_performance_summary --all
"""
import logging
from django.core.management.base import BaseCommand, CommandError

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Build/refresh TripPerformanceSummary for one or more months"

    def add_arguments(self, parser):
        parser.add_argument(
            "--month",
            type=str,
            help="Month to process in YYYY-MM format, e.g. 2026-03",
        )
        parser.add_argument(
            "--start-month",
            dest="start_month",
            type=str,
            help="Start of range (YYYY-MM) when processing multiple months",
        )
        parser.add_argument(
            "--end-month",
            dest="end_month",
            type=str,
            help="End of range (YYYY-MM, inclusive) when processing multiple months",
        )
        parser.add_argument(
            "--vehicle",
            type=str,
            default=None,
            help="Optional: restrict rebuild to a single vehicle number",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Rebuild summaries for every month that has CalculatedTrip data",
        )

    def handle(self, *args, **options):
        from mis.models import CalculatedTrip
        from mis.services.trip_performance_summary_service import TripPerformanceSummaryService

        vehicle = options.get("vehicle")
        month = options.get("month")
        start_month = options.get("start_month")
        end_month = options.get("end_month")
        do_all = options.get("all")

        total = 0

        if do_all:
            # Discover all distinct months from the DB
            months = (
                CalculatedTrip.objects
                .values_list("log_date", flat=True)
                .distinct()
                .order_by("log_date")
            )
            month_set = sorted({d.strftime("%Y-%m") for d in months if d})
            if not month_set:
                self.stdout.write(self.style.WARNING("No CalculatedTrip data found."))
                return
            self.stdout.write(f"Building summaries for {len(month_set)} month(s): {', '.join(month_set)}")
            for m in month_set:
                count = TripPerformanceSummaryService.build_for_month(m, vehicle_no=vehicle)
                self.stdout.write(f"  {m}: {count} vehicle(s) updated")
                total += count

        elif month:
            self.stdout.write(f"Building summary for {month}" + (f" / {vehicle}" if vehicle else ""))
            total = TripPerformanceSummaryService.build_for_month(month, vehicle_no=vehicle)

        elif start_month and end_month:
            self.stdout.write(f"Building summaries for {start_month} → {end_month}" + (f" / {vehicle}" if vehicle else ""))
            total = TripPerformanceSummaryService.build_for_date_range(
                start_month, end_month, vehicle_no=vehicle
            )

        else:
            raise CommandError(
                "Specify one of: --month YYYY-MM, --start-month / --end-month, or --all"
            )

        self.stdout.write(self.style.SUCCESS(f"Done. {total} summary row(s) created/updated."))
