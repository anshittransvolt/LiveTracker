#!/usr/bin/env python3
"""
Django Management Command: Calculate and populate delay metrics for existing trips

Usage: 
    python manage.py calculate_trip_delays --days 30        # Last 30 days
    python manage.py calculate_trip_delays --all           # All historical trips  
    python manage.py calculate_trip_delays --date 2024-01-15  # Specific date
    
Background job to populate delay data for the optimized trend graph.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db.models import Q
from datetime import datetime, timedelta
from mis.models import CalculatedTrip
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Calculate and populate delay metrics for existing trips'
    
    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, help='Calculate for last N days')
        parser.add_argument('--all', action='store_true', help='Calculate for all trips')
        parser.add_argument('--date', type=str, help='Calculate for specific date (YYYY-MM-DD)')
        parser.add_argument('--vehicle', type=str, help='Calculate for specific vehicle')
        parser.add_argument('--force', action='store_true', help='Recalculate even if delays already exist')
        parser.add_argument('--batch-size', type=int, default=100, help='Process trips in batches')
        
    def handle(self, *args, **options):
        start_time = timezone.now()
        
        # Build query filters
        filters = Q()
        
        if options['date']:
            try:
                date_obj = datetime.strptime(options['date'], '%Y-%m-%d').date()
                filters &= Q(log_date=date_obj)
                self.stdout.write(f"Calculating delays for date: {date_obj}")
            except ValueError:
                self.stdout.write(self.style.ERROR('Invalid date format. Use YYYY-MM-DD'))
                return
                
        elif options['days']:
            days = options['days']
            end_date = timezone.now().date()
            start_date = end_date - timedelta(days=days)
            filters &= Q(log_date__gte=start_date, log_date__lte=end_date)
            self.stdout.write(f"Calculating delays for last {days} days ({start_date} to {end_date})")
            
        elif options['all']:
            self.stdout.write("Calculating delays for ALL trips")
        else:
            # Default: last 7 days
            days = 7
            end_date = timezone.now().date()
            start_date = end_date - timedelta(days=days)
            filters &= Q(log_date__gte=start_date, log_date__lte=end_date)
            self.stdout.write(f"Calculating delays for last {days} days (default)")
            
        if options['vehicle']:
            filters &= Q(vehicle_no=options['vehicle'])
            self.stdout.write(f"Filtering for vehicle: {options['vehicle']}")
            
        # Filter trips that need delay calculation
        if not options['force']:
            filters &= Q(total_delay_s__isnull=True)  # Only trips without delay data
            
        # Get trips to process
        trips = CalculatedTrip.objects.filter(filters).order_by('-log_date', '-manawar_in_time')
        total_trips = trips.count()
        
        if total_trips == 0:
            self.stdout.write(self.style.WARNING('No trips found to process'))
            return
            
        self.stdout.write(f"Processing {total_trips} trips...")
        
        # Process in batches
        batch_size = options['batch_size']
        updated_count = 0
        error_count = 0
        
        for i in range(0, total_trips, batch_size):
            batch = trips[i:i + batch_size]
            self.stdout.write(f"Processing batch {i//batch_size + 1}/{(total_trips + batch_size - 1)//batch_size}...")
            
            batch_updates = []
            
            for trip in batch:
                try:
                    delay_metrics = self._calculate_trip_delays(trip)
                    
                    # Update trip with calculated delays
                    for field, value in delay_metrics.items():
                        setattr(trip, field, value)
                    
                    batch_updates.append(trip)
                    updated_count += 1
                    
                    if updated_count % 50 == 0:
                        self.stdout.write(f"Processed {updated_count}/{total_trips} trips...")
                        
                except Exception as e:
                    error_count += 1
                    logger.error(f"Error processing trip {trip.id}: {str(e)}")
                    
            # Bulk update the batch
            if batch_updates:
                CalculatedTrip.objects.bulk_update(
                    batch_updates,
                    [
                        'manawar_loading_delay_s', 'dhule_unloading_delay_s',
                        'manawar_charging_delay_s', 'dhule_charging_delay_s', 
                        'jhulwania_charging_delay_s', 'maha_border_delay_s',
                        'total_delay_s', 'ultratech_delay_s', 'driver_delay_s',
                        'manawar_to_jhulwania_duration_s', 'jhulwania_to_dhule_duration_s',
                        'dhule_to_manawar_duration_s', 'total_drive_time_s'
                    ]
                )
                
        # Summary
        duration = timezone.now() - start_time
        self.stdout.write(
            self.style.SUCCESS(
                f"Completed delay calculation:\n"
                f"  • Updated: {updated_count} trips\n"
                f"  • Errors: {error_count} trips\n"
                f"  • Duration: {duration.total_seconds():.1f} seconds\n"
                f"  • Rate: {updated_count / duration.total_seconds():.1f} trips/second"
            )
        )
        
    def _calculate_trip_delays(self, trip):
        """
        Calculate delay metrics for a single trip using the same logic as the enhanced calculator
        """
        from livetracker.alertService import alert_constants as ac
        
        # SLA thresholds (seconds) - must match timebox trend system
        PHASE_SLA = {
            'manawar_loading': ac.LOADING_DWELL_SECONDS,
            'dhule_unloading': ac.UNLOADING_DWELL_SECONDS,
            'manawar_charging': ac.CHARGING_OVER_SECONDS,
            'dhule_charging': ac.CHARGING_OVER_SECONDS,
            'jhulwania_charging': ac.CHARGING_OVER_SECONDS,
            'maha_border': ac.MAHA_BORDER_DWELL_SECONDS,
        }
        
        delay_metrics = {}
        
        # Calculate loading delay
        loading_duration_s = self._parse_duration_to_seconds(trip.manawar_loading_time)
        manawar_loading_sla = PHASE_SLA.get('manawar_loading', 0)
        delay_metrics['manawar_loading_delay_s'] = max(0, loading_duration_s - manawar_loading_sla) if manawar_loading_sla > 0 else 0
        
        # Calculate unloading delay
        unloading_duration_s = self._parse_duration_to_seconds(trip.dhule_unload_time)
        dhule_unloading_sla = PHASE_SLA.get('dhule_unloading', 0)
        delay_metrics['dhule_unloading_delay_s'] = max(0, unloading_duration_s - dhule_unloading_sla) if dhule_unloading_sla > 0 else 0
        
        # Calculate charging delays
        manawar_charging_duration_s = self._parse_duration_to_seconds(trip.dhar_charging_duration)
        manawar_charging_sla = PHASE_SLA.get('manawar_charging', 0)
        delay_metrics['manawar_charging_delay_s'] = max(0, manawar_charging_duration_s - manawar_charging_sla) if manawar_charging_sla > 0 else 0
        
        dhule_charging_duration_s = self._parse_duration_to_seconds(trip.dhule_charging_duration)
        dhule_charging_sla = PHASE_SLA.get('dhule_charging', 0)
        delay_metrics['dhule_charging_delay_s'] = max(0, dhule_charging_duration_s - dhule_charging_sla) if dhule_charging_sla > 0 else 0
        
        jhulwania_charging_duration_s = self._parse_duration_to_seconds(trip.julwaniya_charging_duration)  # Note: 'julwaniya' spelling in field name
        jhulwania_charging_sla = PHASE_SLA.get('jhulwania_charging', 0)
        delay_metrics['jhulwania_charging_delay_s'] = max(0, jhulwania_charging_duration_s - jhulwania_charging_sla) if jhulwania_charging_sla > 0 else 0
        
        # Border crossing delay (placeholder - may not be tracked)
        delay_metrics['maha_border_delay_s'] = 0
        
        # Calculate aggregate delays
        delay_metrics['total_delay_s'] = (
            delay_metrics['manawar_loading_delay_s'] +
            delay_metrics['dhule_unloading_delay_s'] +
            delay_metrics['manawar_charging_delay_s'] +
            delay_metrics['dhule_charging_delay_s'] +
            delay_metrics['jhulwania_charging_delay_s'] +
            delay_metrics['maha_border_delay_s']
        )
        
        delay_metrics['ultratech_delay_s'] = (
            delay_metrics['manawar_loading_delay_s'] +
            delay_metrics['dhule_unloading_delay_s'] +
            delay_metrics['manawar_charging_delay_s'] +
            delay_metrics['dhule_charging_delay_s']
        )
        
        delay_metrics['driver_delay_s'] = (
            delay_metrics['jhulwania_charging_delay_s'] +
            delay_metrics['maha_border_delay_s']
        )
        
        # Calculate transit durations
        delay_metrics['manawar_to_jhulwania_duration_s'] = self._parse_duration_to_seconds(trip.manawar_julwaniya_total)
        delay_metrics['jhulwania_to_dhule_duration_s'] = self._parse_duration_to_seconds(trip.julwaniya_dhule_stoppage)
        delay_metrics['dhule_to_manawar_duration_s'] = self._parse_duration_to_seconds(trip.road_time_to_dhar)
        
        delay_metrics['total_drive_time_s'] = (
            delay_metrics['manawar_to_jhulwania_duration_s'] +
            delay_metrics['jhulwania_to_dhule_duration_s'] +
            delay_metrics['dhule_to_manawar_duration_s']
        )
        
        return delay_metrics
    
    def _parse_duration_to_seconds(self, duration_str):
        """Parse HH:MM duration string to total seconds"""
        if not duration_str or duration_str in ['', '00:00', '-', None]:
            return 0
        
        try:
            if ':' in str(duration_str):
                hours, minutes = str(duration_str).split(':', 1)
                return int(hours) * 3600 + int(minutes) * 60
            else:
                return int(duration_str) * 3600
        except (ValueError, AttributeError):
            return 0