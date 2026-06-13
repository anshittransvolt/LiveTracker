"""
Report Formatter Service
========================
Formats trip data for Excel export with proper types and formatting.
"""

from decimal import Decimal
from datetime import time
import pandas as pd
from typing import Any, Optional


class ReportFormatter:
    """Formats trip data for Excel export."""
    
    @staticmethod
    def safe_decimal(val: Any) -> Optional[float]:
        """Convert Decimal to float."""
        try:
            if isinstance(val, Decimal):
                return float(val)
            elif val is not None:
                return float(val)
            return None
        except (ValueError, TypeError):
            return None
    
    @staticmethod
    def safe_float(val: Any) -> Optional[float]:
        """Convert value to float safely."""
        try:
            if pd.isna(val):
                return None
            return round(float(val), 3) if val else None
        except (ValueError, TypeError):
            return None
    
    @staticmethod
    def safe_datetime(dt_val: Any) -> Any:
        """Remove timezone from datetime."""
        if dt_val and hasattr(dt_val, 'replace'):
            return dt_val.replace(tzinfo=None)
        return dt_val
    
    @staticmethod
    def time_to_string(time_val: Any) -> Optional[str]:
        """Convert time object to HH:MM string."""
        if time_val is None:
            return None
        
        try:
            if isinstance(time_val, time):
                return time_val.strftime('%H:%M')
            elif isinstance(time_val, str):
                # Already a string, ensure it's HH:MM format
                if ':' in time_val:
                    parts = time_val.split(':')
                    if len(parts) >= 2:
                        return f"{parts[0]}:{parts[1]}"
                return time_val
            return str(time_val).split('.')[0] if time_val else None
        except Exception:
            return None
    
    @staticmethod
    def format_trip_row(trip: dict) -> dict:
        """
        Format a single trip row for Excel export.
        
        Converts:
        - Decimal → float
        - time → HH:MM string
        - datetime → remove timezone
        - numeric fields → properly typed
        
        Args:
            trip: Trip dictionary from database
            
        Returns:
            Formatted trip dictionary ready for Excel
        """
        return {
            'Sr.No': trip.get('id'),
            'Log Date': trip.get('log_date'),
            'Vehicle No': trip.get('vehicle_no'),
            
            # SOC Data - All areas
            'Start SOC (%)': ReportFormatter.safe_decimal(trip.get('start_soc')),
            'Closing SOC (%)': ReportFormatter.safe_decimal(trip.get('closing_soc')),
            
            # Manawar
            'Manawar In Time': ReportFormatter.safe_datetime(trip.get('manawar_in_time')),
            'Manawar Out Time': ReportFormatter.safe_datetime(trip.get('manawar_out_time')),
            'Trip Start KM': ReportFormatter.safe_decimal(trip.get('trip_start_km')),
            'Start SOC (Manawar)': ReportFormatter.safe_decimal(trip.get('start_soc')),
            'Closing SOC (Manawar)': ReportFormatter.safe_decimal(trip.get('closing_soc')),
            'Charging Start Date (Manawar)': trip.get('dhar_charging_start_date'),
            'Charging Start Time (Manawar)': ReportFormatter.time_to_string(trip.get('dhar_charging_start_time')),
            'Charging End Time (Manawar)': ReportFormatter.time_to_string(trip.get('dhar_charging_end_time')),
            'Charging Duration (Manawar)': trip.get('dhar_charging_duration'),
            'KWH (Manawar)': ReportFormatter.safe_decimal(trip.get('dhar_kwh')),
            
            # Julwaniya
            'Julwaniya Entry Time': ReportFormatter.safe_datetime(trip.get('julwaniya_entry_time')),
            'Julwaniya Exit Time': ReportFormatter.safe_datetime(trip.get('julwaniya_exit_time')),
            'Closing KM (Julwaniya)': ReportFormatter.safe_decimal(trip.get('closing_km_julwaniya')),
            'Start SOC (Julwaniya)': ReportFormatter.safe_decimal(trip.get('start_soc_julwaniya')),
            'End SOC (Julwaniya)': ReportFormatter.safe_decimal(trip.get('end_soc_julwaniya')),
            'Closing SOC (Julwaniya)': ReportFormatter.safe_decimal(trip.get('closing_soc_julwaniya')),
            'Charging Start Date (Julwaniya)': trip.get('julwaniya_charging_start_date'),
            'Charging Start Time (Julwaniya)': ReportFormatter.time_to_string(trip.get('julwaniya_charging_start_time')),
            'Charging End Time (Julwaniya)': ReportFormatter.time_to_string(trip.get('julwaniya_charging_end_time')),
            'Charging Duration (Julwaniya)': trip.get('julwaniya_charging_duration'),
            'KWH (Julwaniya)': ReportFormatter.safe_decimal(trip.get('julwaniya_kwh')),
            'Idle Time (Julwaniya)': trip.get('idle_time_julwaniya'),
            
            # Dhule
            'Dhule Entry Time': ReportFormatter.safe_datetime(trip.get('dhule_entry_time')),
            'Dhule Exit Time': ReportFormatter.safe_datetime(trip.get('dhule_exit_time')),
            'Closing KM (Dhule)': ReportFormatter.safe_decimal(trip.get('closing_km_dhule')),
            'Start SOC (Dhule)': ReportFormatter.safe_decimal(trip.get('start_soc_dhule')),
            'End SOC (Dhule)': ReportFormatter.safe_decimal(trip.get('end_soc_dhule')),
            'Closing SOC (Dhule)': ReportFormatter.safe_decimal(trip.get('closing_soc_dhule')),
            'Charging Start Date (Dhule)': trip.get('dhule_charging_start_date'),
            'Charging Start Time (Dhule)': ReportFormatter.time_to_string(trip.get('dhule_charging_start_time')),
            'Charging End Time (Dhule)': ReportFormatter.time_to_string(trip.get('dhule_charging_end_time')),
            'Charging Duration (Dhule)': trip.get('dhule_charging_duration'),
            'KWH (Dhule)': ReportFormatter.safe_decimal(trip.get('dhule_kwh')),
            'Idle Time (Dhule)': trip.get('idle_time_dhule'),
            
            # Return Julwaniya fields removed
            
            # Totals
            'Total Distance (km)': ReportFormatter.safe_decimal(trip.get('total_distance_km')),
            'Total KWH': ReportFormatter.safe_decimal(trip.get('total_kwh')),
            'Efficiency (kWh/km)': ReportFormatter.safe_decimal(trip.get('efficiency_kwh_per_km')),
            'Total Trip Time': trip.get('vehicle_total_trip_time'),
            'Dhar Reach Time': ReportFormatter.safe_datetime(trip.get('dhar_reach_time')),
            'Trip Closed KM': ReportFormatter.safe_decimal(trip.get('trip_closed_km')),
            'Total Trip KM': ReportFormatter.safe_decimal(trip.get('total_trip_km')),
        }
