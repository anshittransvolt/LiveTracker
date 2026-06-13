"""
Check the date range of existing trip data and backfill to today.

Usage:
  python manage.py check_and_backfill_trip_data  # Check & show current dates
  python manage.py check_and_backfill_trip_data --backfill  # Check & backfill to today
  python manage.py check_and_backfill_trip_data --backfill --force  # Recalculate even if exists
"""
import logging
from datetime import date, timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db.models import Max, Min

from mis.models import VehicleTripState, DailyLog, CalculatedTrip
from mis.services.incremental_trip_orchestrator import IncrementalTripOrchestrator

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Check date ranges for trip state and trip logs, optionally backfill to today'

    def add_arguments(self, parser):
        parser.add_argument(
            '--backfill',
            action='store_true',
            help='Backfill missing data until today'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force recalculation even if trips already exist'
        )
        parser.add_argument(
            '--vehicles',
            type=str,
            default=None,
            help='Comma-separated list of vehicle numbers to backfill (if not specified, all vehicles)'
        )

    def handle(self, *args, **options):
        today = date.today()
        backfill = options['backfill']
        force = options['force']
        vehicles_str = options['vehicles']

        self.stdout.write("\n" + "="*80)
        self.stdout.write("TRIP DATA STATUS REPORT")
        self.stdout.write("="*80 + "\n")

        # Check VehicleTripState dates
        vts_agg = VehicleTripState.objects.aggregate(
            min_date=Min('state_date'),
            max_date=Max('state_date')
        )
        vts_count = VehicleTripState.objects.count()
        vts_vehicles = VehicleTripState.objects.values('vehicle_no').distinct().count()

        self.stdout.write("📊 VEHICLE TRIP STATE")
        self.stdout.write("-" * 40)
        self.stdout.write(f"  Total records: {vts_count}")
        self.stdout.write(f"  Unique vehicles: {vts_vehicles}")
        if vts_agg['min_date']:
            self.stdout.write(f"  Date range: {vts_agg['min_date']} to {vts_agg['max_date']}")
        else:
            self.stdout.write(f"  Date range: No data")
        self.stdout.write("")

        # Check DailyLog dates
        dl_agg = DailyLog.objects.aggregate(
            min_date=Min('log_date'),
            max_date=Max('log_date')
        )
        dl_count = DailyLog.objects.count()

        self.stdout.write("📋 DAILY LOG")
        self.stdout.write("-" * 40)
        self.stdout.write(f"  Total records: {dl_count}")
        if dl_agg['min_date']:
            self.stdout.write(f"  Date range: {dl_agg['min_date']} to {dl_agg['max_date']}")
        else:
            self.stdout.write(f"  Date range: No data")
        self.stdout.write("")

        # Check CalculatedTrip dates
        ct_agg = CalculatedTrip.objects.aggregate(
            min_date=Min('log_date'),
            max_date=Max('log_date')
        )
        ct_count = CalculatedTrip.objects.count()
        ct_vehicles = CalculatedTrip.objects.values('vehicle_no').distinct().count()

        self.stdout.write("🚗 CALCULATED TRIP")
        self.stdout.write("-" * 40)
        self.stdout.write(f"  Total records: {ct_count}")
        self.stdout.write(f"  Unique vehicles: {ct_vehicles}")
        if ct_agg['min_date']:
            self.stdout.write(f"  Date range: {ct_agg['min_date']} to {ct_agg['max_date']}")
        else:
            self.stdout.write(f"  Date range: No data")
        self.stdout.write("")

        self.stdout.write(f"📅 TODAY'S DATE: {today}")
        self.stdout.write("="*80 + "\n")

        # Determine backfill range
        if not backfill:
            self.stdout.write(self.style.WARNING(
                "To backfill data until today, run with --backfill flag"
            ))
            return

        # Get the max date from CalculatedTrip to determine where to start backfilling
        max_trip_date = ct_agg['max_date']
        
        if max_trip_date is None:
            self.stdout.write(self.style.WARNING("⚠️  No calculated trips exist. Starting from 7 days ago."))
            start_date = today - timedelta(days=7)
        else:
            start_date = max_trip_date + timedelta(days=1)
            if start_date > today:
                self.stdout.write(self.style.SUCCESS("✓ Data is already up to date!"))
                return

        self.stdout.write(self.style.WARNING(f"\n🔄 BACKFILL RANGE: {start_date} to {today}"))
        
        # Parse vehicle filter if provided
        vehicle_filter = None
        if vehicles_str:
            vehicle_filter = [v.strip() for v in vehicles_str.split(',')]
            self.stdout.write(f"   Vehicles: {vehicle_filter}")

        self.stdout.write("")

        try:
            orchestrator = IncrementalTripOrchestrator()
            
            current_date = start_date
            total_trips = 0
            total_errors = 0

            while current_date <= today:
                self.stdout.write(f"Processing {current_date}...", ending=" ")
                
                try:
                    trips, errors = orchestrator.run_daily(
                        target_date=current_date,
                        force=force,
                        vehicle_filter=vehicle_filter
                    )
                    total_trips += trips
                    total_errors += errors
                    
                    status_msg = f"✓ {trips} trips"
                    if errors > 0:
                        status_msg += f" ({errors} errors)"
                    self.stdout.write(self.style.SUCCESS(status_msg))
                    
                except Exception as e:
                    total_errors += 1
                    self.stdout.write(self.style.ERROR(f"✗ Error: {str(e)[:60]}"))
                    logger.exception(f"Error processing {current_date}")

                current_date += timedelta(days=1)

            self.stdout.write("\n" + "="*80)
            self.stdout.write("✅ BACKFILL COMPLETE")
            self.stdout.write("="*80)
            self.stdout.write(f"  Total trips calculated: {total_trips}")
            self.stdout.write(f"  Total errors: {total_errors}")
            self.stdout.write("="*80 + "\n")

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"\n❌ Backfill failed: {str(e)}"))
            logger.exception("Backfill process failed")
            raise
