"""
Management command to calculate trips for yesterday and today daily.
Schedule this to run every morning via cron: 0 1 * * * /path/to/manage.py calculate_daily_trips
"""
import logging
from datetime import date, timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone

from mis.services.incremental_trip_orchestrator import IncrementalTripOrchestrator
from mis.models import CalculatedTrip

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Calculate trips for yesterday and today to cache data'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=2,
            help='Number of days to look back (default: 2 for yesterday + today)'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force recalculation even if trips already exist'
        )

    def handle(self, *args, **options):
        days_to_calc = options['days']
        force = options['force']
        
        today = date.today()
        start_date = today - timedelta(days=days_to_calc - 1)
        
        self.stdout.write(
            self.style.SUCCESS(f'Calculating trips from {start_date} to {today}...')
        )
        
        try:
            # Check if data already exists for this range
            existing_count = CalculatedTrip.objects.filter(
                log_date__gte=start_date,
                log_date__lte=today
            ).count()
            
            if existing_count > 0 and not force:
                self.stdout.write(
                    self.style.WARNING(
                        f'Found {existing_count} existing trips for this range. '
                        f'Use --force to recalculate.'
                    )
                )
                return
            
            # Calculate trips using incremental (state-based) orchestrator
            vehicle_list = IncrementalTripOrchestrator.get_known_vehicles()
            if not vehicle_list:
                self.stdout.write(self.style.WARNING('No known vehicles found in state/trips. Skipping.'))
                return

            self.stdout.write(f'Running incremental calculation for {len(vehicle_list)} vehicle(s): {start_date} to {today}...')
            inc = IncrementalTripOrchestrator()
            inc.process_date_range(
                start_date=start_date,
                end_date=today,
                vehicle_list=vehicle_list,
                save_to_db=True,
            )
            
            # Count new trips
            new_count = CalculatedTrip.objects.filter(
                log_date__gte=start_date,
                log_date__lte=today
            ).count()
            
            self.stdout.write(
                self.style.SUCCESS(
                    f'✓ Successfully calculated and cached {new_count} trips'
                )
            )
            
        except Exception as e:
            logger.error(f'Error calculating daily trips: {e}', exc_info=True)
            self.stdout.write(
                self.style.ERROR(f'✗ Error calculating trips: {str(e)}')
            )
            raise
