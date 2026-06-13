"""
Manual Entry Merger - Fixed DateTime Handling
"""
import logging
from datetime import datetime, date, time
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


def normalize_vehicle_no(value: Any) -> str:
    """
    Normalize vehicle/horse numbers to a canonical format used for matching.

    Rules:
    - Uppercase
    - Remove all non-alphanumeric characters (spaces, hyphens, dots, etc.)
    - Return empty string if value is falsy
    """
    if value is None:
        return ""
    try:
        s = str(value).upper()
        import re
        return re.sub(r"[^A-Z0-9]", "", s)
    except Exception:
        return ""


def safe_datetime_convert(value, field_name: str = "field"):
    """
    Safely convert value to datetime, handling both strings and datetime objects.
    
    Args:
        value: String, datetime, or None
        field_name: Name of field for logging
        
    Returns:
        datetime object or None
    """
    if value is None:
        return None
    
    # If already a datetime object, return as-is
    if isinstance(value, datetime):
        return value
    
    # If it's a string, parse it
    if isinstance(value, str):
        try:
            # Try ISO format first
            return datetime.fromisoformat(value)
        except ValueError:
            try:
                # Try common datetime formats (including day-first variants)
                for fmt in [
                    '%Y-%m-%d %H:%M:%S',
                    '%Y-%m-%d %H:%M:%S.%f',
                    '%Y-%m-%dT%H:%M:%S',
                    '%Y-%m-%dT%H:%M:%S.%f',
                    '%d-%m-%Y %H:%M:%S',
                    '%d/%m/%Y %H:%M:%S',
                    '%d-%m-%Y %H:%M',
                    '%d/%m/%Y %H:%M',
                ]:
                    try:
                        return datetime.strptime(value, fmt)
                    except ValueError:
                        continue
                logger.error(f"Could not parse datetime string for {field_name}: {value}")
                return None
            except Exception as e:
                logger.error(f"Error parsing {field_name}: {e}")
                return None
    
    logger.warning(f"Unexpected type for {field_name}: {type(value)}")
    return None


def safe_date_convert(value, field_name: str = "field"):
    """
    Safely convert value to date.
    
    Args:
        value: String, date, datetime, or None
        field_name: Name of field for logging
        
    Returns:
        date object or None
    """
    if value is None:
        return None
    
    # If already a date object, return as-is
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    
    # If it's a datetime, extract date
    if isinstance(value, datetime):
        return value.date()
    
    # If it's a string, parse it
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            try:
                # Try common date-only formats first
                for fmt in [
                    '%d-%m-%Y', '%d/%m/%Y', '%d.%m.%Y',
                    '%Y-%m-%d', '%Y/%m/%d', '%Y.%m.%d'
                ]:
                    try:
                        return datetime.strptime(value, fmt).date()
                    except ValueError:
                        continue
                # Try parsing as datetime, then extract date
                dt = safe_datetime_convert(value, field_name)
                return dt.date() if dt else None
            except Exception as e:
                logger.error(f"Error parsing date for {field_name}: {e}")
                return None
    
    logger.warning(f"Unexpected type for {field_name}: {type(value)}")
    return None


def safe_time_convert(value, field_name: str = "field"):
    """
    Safely convert value to time.
    
    Args:
        value: String, time, datetime, or None
        field_name: Name of field for logging
        
    Returns:
        time object or None
    """
    if value is None:
        return None
    
    # If already a time object, return as-is
    if isinstance(value, time):
        return value
    
    # If it's a datetime, extract time
    if isinstance(value, datetime):
        return value.time()
    
    # If it's a string, parse it
    if isinstance(value, str):
        try:
            # Try parsing as time directly
            for fmt in ['%H:%M:%S', '%H:%M:%S.%f', '%H:%M']:
                try:
                    return datetime.strptime(value, fmt).time()
                except ValueError:
                    continue
            # Try parsing as datetime first, then extract time
            dt = safe_datetime_convert(value, field_name)
            return dt.time() if dt else None
        except Exception as e:
            logger.error(f"Error parsing time for {field_name}: {e}")
            return None
    
    logger.warning(f"Unexpected type for {field_name}: {type(value)}")
    return None


class ManualEntryMerger:
    """Merge calculated trips with manual entries and handle database operations."""
    def import_daily_logs_from_excel(self, excel_path: str, sheet_name: str | None = None, dry_run: bool = False) -> int:
        """Import manual DailyLog entries from an Excel file.
        Matches and upserts by (horse_no, log_date).

        Expected columns (case-insensitive, flexible names supported):
        - Log Date
        - Horse No
        - Trailer No
        - Driver ID
        - LR
        - From
        - Trailer OEM
        - Delivery No
        - Tonnage Load
        - Tonnage Unload
        - Toll Paid (Manawar to Jhulwania)
        - Toll Paid (Jhulwania to Dhule)
        - Maintenance
        """
        import pandas as pd
        from decimal import Decimal
        from ..models import DailyLog

        try:
            df = pd.read_excel(excel_path, sheet_name=sheet_name) if sheet_name else pd.read_excel(excel_path)
        except Exception as e:
            logger.error(f"Failed to read Excel '{excel_path}': {e}")
            return 0

        # Normalize column names
        colmap = {c.strip().lower(): c for c in df.columns}

        def get(col_names: list):
            for name in col_names:
                key = name.lower()
                if key in colmap:
                    return df[colmap[key]]
            return None

        # Required keys
        log_date_series = get(['Log Date','Date'])
        horse_no_series = get(['Horse No','Vehicle No','Horse'])
        if log_date_series is None or horse_no_series is None:
            logger.error("Excel must contain 'Log Date' and 'Horse No' columns")
            return 0

        # Optional fields
        trailer_no_series = get(['Trailer No'])
        driver_id_series = get(['Driver ID'])
        # Jhulwania optional variants
        driver_id_j_series = get(['Driver ID (Jhulwania)','Driver Id(Jhulwania to Dhule)','Driver ID Jhulwania'])
        trailer_no_j_series = get(['Trailer No (Jhulwania)','Trailer No.(Jhulwania to Dhule)','Trailer No Jhulwania'])
        horse_no_j_series = get(['Horse No (Jhulwania)','Horse No(Jhulwania to Dhule)','Horse No Jhulwania'])

        lr_series = get(['LR','L/R'])
        from_series = get(['From'])
        trailer_oem_series = get(['Trailer OEM'])
        delivery_no_series = get(['Delivery No'])
        tonnage_load_series = get(['Tonnage Load'])
        tonnage_unload_series = get(['Tonnage Unload'])
        toll_mj_series = get(['Toll Paid (Manawar to Jhulwania)','Toll Paid Manawar Jhulwania'])
        toll_jd_series = get(['Toll Paid (Jhulwania to Dhule)','Toll Paid Jhulwania Dhule'])
        maintenance_series = get(['Maintenance','Remarks'])

        saved = 0
        for idx in range(len(df)):
            log_date_val = log_date_series.iloc[idx] if log_date_series is not None else None
            horse_no_val = horse_no_series.iloc[idx] if horse_no_series is not None else None
            if pd.isna(log_date_val) or pd.isna(horse_no_val):
                continue

            log_date_obj = safe_date_convert(log_date_val, 'log_date')
            horse_no_clean = normalize_vehicle_no(horse_no_val)

            # Auto-fill From/To as needed (From defaults to Manawar)
            from_val = None if from_series is None else from_series.iloc[idx]
            if from_series is None or (hasattr(pd, 'isna') and pd.isna(from_val)) or from_val in [None, '']:
                from_val = 'Manawar'

            defaults = {
                'trailer_no': None if trailer_no_series is None else trailer_no_series.iloc[idx],
                'driver_id': None if driver_id_series is None else driver_id_series.iloc[idx],
                'lr': None if lr_series is None else lr_series.iloc[idx],
                'from_location': from_val,
                'trailer_oem': None if trailer_oem_series is None else trailer_oem_series.iloc[idx],
                'delivery_no': None if delivery_no_series is None else delivery_no_series.iloc[idx],
                'maintenance': None if maintenance_series is None else maintenance_series.iloc[idx],
            }

            # Jhulwania fields
            if driver_id_j_series is not None:
                defaults['driver_id_jhulwania'] = driver_id_j_series.iloc[idx]
            if trailer_no_j_series is not None:
                defaults['trailer_no_jhulwania'] = trailer_no_j_series.iloc[idx]
            if horse_no_j_series is not None:
                defaults['horse_no_jhulwania'] = normalize_vehicle_no(horse_no_j_series.iloc[idx])

            # Decimal fields safe conversion
            def to_decimal(series, idx):
                if series is None:
                    return None
                val = series.iloc[idx]
                if pd.isna(val) or val is None:
                    return None
                try:
                    return Decimal(str(val).strip())
                except Exception:
                    return None

            defaults['tonnage_load'] = to_decimal(tonnage_load_series, idx)
            defaults['tonnage_unload'] = to_decimal(tonnage_unload_series, idx)
            defaults['toll_paid_manawar_jhulwania'] = to_decimal(toll_mj_series, idx)
            defaults['toll_paid_jhulwania_dhule'] = to_decimal(toll_jd_series, idx)

            if dry_run:
                saved += 1
            else:
                try:
                    DailyLog.objects.update_or_create(
                        log_date=log_date_obj,
                        horse_no=horse_no_clean,
                        defaults=defaults,
                    )
                    saved += 1
                except Exception as e:
                    logger.error(f"Failed upsert DailyLog (horse_no={horse_no_clean}, log_date={log_date_obj}): {e}")
                    continue

        action = "Parsed" if dry_run else "Imported"
        logger.info(f"{action} {saved} daily logs from {excel_path}{' (dry-run)' if dry_run else ''}")
        return saved
    
    def save_calculated_trips(self, calculated_trips: List[Dict[str, Any]]) -> int:
        """
        Save calculated trips to database with proper datetime handling.
        
        Args:
            calculated_trips: List of trip dictionaries
            
        Returns:
            Number of trips saved
        """
        from ..models import CalculatedTrip
        
        saved_count = 0
        affected_months: set = set()
        
        for trip in calculated_trips:
            try:
                vehicle_no = normalize_vehicle_no(trip.get('vehicle_no', ''))
                
                # Convert all datetime fields safely
                trip_data = {
                    'vehicle_no': vehicle_no,
                    'log_date': safe_date_convert(trip.get('log_date'), 'log_date'),
                    
                    # Manawar fields
                    'manawar_in_time': safe_datetime_convert(trip.get('manawar_in_time'), 'manawar_in_time'),
                    'manawar_out_time': safe_datetime_convert(trip.get('manawar_out_time'), 'manawar_out_time'),
                    'vehicle_out_time': safe_datetime_convert(trip.get('vehicle_out_time'), 'vehicle_out_time'),
                    'dhar_charging_duration': trip.get('dhar_charging_duration'),
                    'dhar_charging_start_date': safe_date_convert(trip.get('dhar_charging_start_date'), 'dhar_charging_start_date'),
                    'dhar_charging_start_time': safe_time_convert(trip.get('dhar_charging_start_time'), 'dhar_charging_start_time'),
                    'dhar_charging_end_time': safe_time_convert(trip.get('dhar_charging_end_time'), 'dhar_charging_end_time'),
                    'dhar_kwh': trip.get('dhar_kwh'),
                    'manawar_loading_time': trip.get('manawar_loading_time'),
                    
                    # Road: Manawar -> Julwaniya
                    'manawar_julwaniya_stoppage': trip.get('manawar_julwaniya_stoppage'),
                    'manawar_julwaniya_moving': trip.get('manawar_julwaniya_moving'),
                    'manawar_julwaniya_total': trip.get('manawar_julwaniya_total'),
                    
                    # Julwaniya fields
                    'julwaniya_entry_time': safe_datetime_convert(trip.get('julwaniya_entry_time'), 'julwaniya_entry_time'),
                    'julwaniya_exit_time': safe_datetime_convert(trip.get('julwaniya_exit_time'), 'julwaniya_exit_time'),
                    'julwaniya_charging_duration': trip.get('julwaniya_charging_duration'),
                    'julwaniya_charging_start_date': safe_date_convert(trip.get('julwaniya_charging_start_date'), 'julwaniya_charging_start_date'),
                    'julwaniya_charging_start_time': safe_time_convert(trip.get('julwaniya_charging_start_time'), 'julwaniya_charging_start_time'),
                    'julwaniya_charging_end_time': safe_time_convert(trip.get('julwaniya_charging_end_time'), 'julwaniya_charging_end_time'),
                    'julwaniya_kwh': trip.get('julwaniya_kwh'),
                    'idle_time_julwaniya': trip.get('idle_time_julwaniya'),
                    
                    # Road: Julwaniya -> Dhule
                    'julwaniya_dhule_stoppage': trip.get('julwaniya_dhule_stoppage'),
                    
                    # Dhule fields
                    'dhule_entry_time': safe_datetime_convert(trip.get('dhule_entry_time'), 'dhule_entry_time'),
                    'dhule_exit_time': safe_datetime_convert(trip.get('dhule_exit_time'), 'dhule_exit_time'),
                    'dhule_charging_duration': trip.get('dhule_charging_duration'),
                    'dhule_charging_start_date': safe_date_convert(trip.get('dhule_charging_start_date'), 'dhule_charging_start_date'),
                    'dhule_charging_start_time': safe_time_convert(trip.get('dhule_charging_start_time'), 'dhule_charging_start_time'),
                    'dhule_charging_end_time': safe_time_convert(trip.get('dhule_charging_end_time'), 'dhule_charging_end_time'),
                    'dhule_kwh': trip.get('dhule_kwh'),
                    'idle_time_dhule': trip.get('idle_time_dhule'),
                    
                    # Return journey
                    'dhar_reach_time': safe_datetime_convert(trip.get('dhar_reach_time'), 'dhar_reach_time'),
                    'dhar_reach_date': safe_date_convert(trip.get('dhar_reach_date'), 'dhar_reach_date'),
                    
                    # Totals
                    'vehicle_total_trip_time': trip.get('vehicle_total_trip_time'),
                    'all_station_total_charging_hours': trip.get('all_station_total_charging_hours'),
                    'total_distance_km': trip.get('total_distance_km'),
                    'total_kwh': trip.get('total_kwh'),
                    'efficiency_kwh_per_km': trip.get('efficiency_kwh_per_km'),
                    'total_trip_km': trip.get('total_trip_km'),

                    # Per-trip performance metrics (seconds)
                    'trip_duration_s': trip.get('trip_duration_s'),
                    'plant_area_time_s': trip.get('plant_area_time_s'),
                    'plant_area_stop_time_s': trip.get('plant_area_stop_time_s'),
                    'plant_area_move_time_s': trip.get('plant_area_move_time_s'),
                    'loading_stop_time_s': trip.get('loading_stop_time_s'),
                    'unloading_stop_time_s': trip.get('unloading_stop_time_s'),
                    'charging_area_time_s': trip.get('charging_area_time_s'),
                    'plugged_time_s': trip.get('plugged_time_s'),
                    'charging_area_stop_time_s': trip.get('charging_area_stop_time_s'),
                    'charging_area_move_time_s': trip.get('charging_area_move_time_s'),
                    'unplanned_stoppage_time_s': trip.get('unplanned_stoppage_time_s'),
                    'gained_soc': trip.get('gained_soc'),
                    
                    # SOC and odometer
                    'start_soc': trip.get('start_soc'),
                    'closing_soc': trip.get('closing_soc'),
                    'trip_start_km': trip.get('trip_start_km'),
                    'trip_closed_km': trip.get('trip_closed_km'),
                    'closing_km_julwaniya': trip.get('closing_km_julwaniya'),
                    'end_soc_julwaniya': trip.get('end_soc_julwaniya'),
                    'start_soc_julwaniya': trip.get('start_soc_julwaniya'),
                    'closing_soc_julwaniya': trip.get('closing_soc_julwaniya'),
                    'start_km_after_julwaniya': trip.get('start_km_after_julwaniya'),
                    'closing_km_dhule': trip.get('closing_km_dhule'),
                    'end_soc_dhule': trip.get('end_soc_dhule'),
                    'start_soc_dhule': trip.get('start_soc_dhule'),
                    'closing_soc_dhule': trip.get('closing_soc_dhule'),
                }
                

                # Remove None values to avoid overwriting existing data
                trip_data = {k: v for k, v in trip_data.items() if v is not None}

                # Convert string values to Decimal for DecimalFields
                from decimal import Decimal, InvalidOperation
                decimal_fields = [
                    'start_soc', 'trip_start_km', 'closing_soc', 'dhar_kwh', 'closing_km_julwaniya',
                    'end_soc_julwaniya', 'start_soc_julwaniya', 'closing_soc_julwaniya', 'julwaniya_kwh',
                    'start_km_after_julwaniya', 'closing_km_dhule', 'end_soc_dhule', 'start_soc_dhule',
                    'closing_soc_dhule', 'dhule_kwh', 'trip_closed_km',
                    'total_distance_km', 'total_kwh', 'efficiency_kwh_per_km', 'total_trip_km',
                    'trip_duration_s', 'plant_area_time_s', 'plant_area_stop_time_s', 'plant_area_move_time_s',
                    'loading_stop_time_s', 'unloading_stop_time_s', 'charging_area_time_s', 'plugged_time_s',
                    'charging_area_stop_time_s', 'charging_area_move_time_s', 'unplanned_stoppage_time_s',
                    'gained_soc',
                ]
                for field in decimal_fields:
                    if field in trip_data:
                        val = trip_data[field]
                        if isinstance(val, str):
                            # Remove all types of quotes and keep only valid decimal characters
                            val_clean = val
                            for ch in ['“', '”', '‘', '’', '"', "'"]:
                                val_clean = val_clean.replace(ch, '')
                            val_clean = val_clean.strip()
                            # Remove any non-numeric, non-dot, non-minus characters
                            import re
                            val_clean = re.sub(r'[^0-9.\-]', '', val_clean)
                            logger.debug(f"Decimal conversion debug: field={field}, raw='{val}', cleaned='{val_clean}', type(raw)={type(val)}")
                            try:
                                trip_data[field] = Decimal(val_clean)
                            except InvalidOperation:
                                logger.error(f"Invalid decimal value for {field}: {val} (cleaned: {val_clean}) [type: {type(val)}]")
                                import traceback
                                logger.error(traceback.format_exc())
                                trip_data[field] = None

                # Use update_or_create to avoid duplicates
                # Unique identifier: vehicle_no + manawar_in_time
                if trip_data.get('vehicle_no') and trip_data.get('manawar_in_time'):
                    obj, created = CalculatedTrip.objects.update_or_create(
                        vehicle_no=trip_data['vehicle_no'],
                        manawar_in_time=trip_data['manawar_in_time'],
                        defaults=trip_data
                    )
                    saved_count += 1
                    # Track affected months for summary refresh
                    ld = trip_data.get('log_date')
                    if ld:
                        from datetime import date as _date
                        if hasattr(ld, 'strftime'):
                            affected_months.add(ld.strftime('%Y-%m'))
                    if created:
                        logger.debug(f"Created new trip for {vehicle_no}")
                    else:
                        logger.debug(f"Updated existing trip for {vehicle_no}")
                else:
                    logger.warning(f"Skipping trip without vehicle_no or manawar_in_time: {trip}")
                    
            except Exception as e:
                logger.error(f"Failed to save trip for {trip.get('vehicle_no', 'UNKNOWN')}: {e}")
                continue
        
        logger.info(f"Saved {saved_count} trips to database")

        # Refresh TripPerformanceSummary for every affected month
        if affected_months:
            try:
                from .trip_performance_summary_service import TripPerformanceSummaryService
                for month in affected_months:
                    updated = TripPerformanceSummaryService.build_for_month(month)
                    logger.info(f"[PerfSummary] Refreshed {updated} vehicle(s) for {month}")
            except Exception as _ps_err:
                logger.warning(f"[PerfSummary] Failed to refresh summaries: {_ps_err}")

        return saved_count

    def _save_trips_no_summary(self, calculated_trips: List[Dict[str, Any]]) -> int:
        """
        Same as save_calculated_trips but skips the automatic TripPerformanceSummary
        refresh. Used by run_full_pipeline which does a single bulk refresh at the end.
        """
        import sys
        # Temporarily suppress the summary call by setting a flag the normal method reads.
        # Simplest approach: just reuse save_calculated_trips but swap out the summary import.
        original = None
        try:
            from . import trip_performance_summary_service as _tps_mod
            original = _tps_mod.TripPerformanceSummaryService.build_for_month
            _tps_mod.TripPerformanceSummaryService.build_for_month = staticmethod(lambda *a, **kw: 0)
            return self.save_calculated_trips(calculated_trips)
        finally:
            if original is not None:
                from . import trip_performance_summary_service as _tps_mod
                _tps_mod.TripPerformanceSummaryService.build_for_month = original

    def merge_trips_with_logs(
        self,
        calculated_trips: List[Dict[str, Any]],
        start_date: date,
        end_date: date
    ) -> List[Dict[str, Any]]:
        """
        Merge calculated trips with manual log entries.
        
        Args:
            calculated_trips: List of calculated trip dicts
            start_date: Start date for logs
            end_date: End date for logs
            
        Returns:
            Merged trip list
        """
        from ..models import DailyLog
        
        # Get manual logs from database
        manual_logs = DailyLog.objects.filter(
            log_date__gte=start_date,
            log_date__lte=end_date
        ).values()
        
        # Create lookup dictionary for manual entries
        manual_dict = {}
        for log in manual_logs:
            horse = normalize_vehicle_no(log.get('horse_no'))
            key = (horse, log['log_date'])
            manual_dict[key] = log
        
        # Merge
        merged = []
        for trip in calculated_trips:
            vehicle_no = normalize_vehicle_no(trip.get('vehicle_no', ''))
            log_date = trip.get('log_date')
            
            # Convert log_date if needed
            if isinstance(log_date, str):
                log_date = safe_date_convert(log_date, 'log_date')
            elif isinstance(log_date, datetime):
                log_date = log_date.date()
            
            # Look up manual entry
            key = (vehicle_no, log_date)
            manual_entry = manual_dict.get(key, {})
            
            # Merge: calculated data takes precedence, but include manual fields
            merged_trip = {**manual_entry, **trip}
            merged.append(merged_trip)
        
        logger.info(f"Merged {len(merged)} trips with manual entries")
        return merged