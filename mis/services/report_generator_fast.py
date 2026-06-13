"""
Report Generator Service (Optimized)
=====================================
Generates Excel reports from merged trip data - FAST version.
"""

import logging
import time
from typing import List, Dict, Any
from datetime import date, datetime, time as time_obj
from decimal import Decimal
import pandas as pd
from io import BytesIO
import xlsxwriter

logger = logging.getLogger(__name__)


def safe_decimal(val: Any) -> Any:
    """Convert Decimal to float for Excel.""" 
    if isinstance(val, Decimal):
        return float(val)
    elif val is not None:
        try:
            return float(val)
        except (ValueError, TypeError):
            pass
    return val


def time_to_string(time_val: Any) -> Any:
    """Convert time object to HH:MM string."""
    if time_val is None:
        return None
    
    try:
        if isinstance(time_val, time_obj):
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
        return time_val


class ReportGenerator:
    """Generate Excel reports from trip data (optimized for speed)."""
    
    # Define report columns in order
    REPORT_COLUMNS = [
        ("Sr.No", "sr_no"),
        ("Log Date", "log_date"),
        ("Driver ID (Start)", "driver_id"),
        ("L/R", "lr"),
        ("From", "from_location"),
        ("Trailer No (Start)", "trailer_no"),
        ("Horse No (Start)", "vehicle_no"),
        ("Trailer OEM", "trailer_oem"),
        ("Delivery No", "delivery_no"),
        ("Tonnage Load", "tonnage_load"),
        ("Closing KM of Previous Trip", "closing_km_previous_trip"),
        ("Trip Start KM", "trip_start_km"),
        ("Vehicle Out Time", "manawar_out_time"),
        ("End SOC of Previous Trip", "end_soc_previous_trip"),
        ("Start SOC", "start_soc"),
        ("Closing SOC", "closing_soc"),
        ("Charging Start Date", "dhar_charging_start_date"),
        ("Charging Start Time", "dhar_charging_start_time"),
        ("Charging End Time", "dhar_charging_end_time"),
        ("KWH", "dhar_kwh"),
        ("Dhar Charging Time", "dhar_charging_duration"),
        ("Toll Charges Paid", "toll_paid_manawar_jhulwania"),
        ("Closing SOC (After Charging)", "closing_soc"),
        ("To (Dhar to Julwaniya)", "to_julwaniya"),
        ("Driver ID (Julwaniya Trip)", "driver_id_jhulwania"),
        ("Trailer No (Julwaniya Trip)", "trailer_no_jhulwania"),
        ("Horse No (Julwaniya Trip)", "horse_no_jhulwaniya"),
        ("Julwaniya Entry Time", "julwaniya_entry_time"),
        ("Julwaniya Exit Time", "julwaniya_exit_time"),
        ("Closing KM After Reaching Julwaniya", "closing_km_julwaniya"),
        ("End SOC (At Julwaniya)", "end_soc_julwaniya"),
        ("Start SOC (At Julwaniya)", "start_soc_julwaniya"),
        ("Closing SOC (After Julwaniya Charging)", "closing_soc_julwaniya"),
        ("Charging Start Date (Julwaniya)", "julwaniya_charging_start_date"),
        ("Charging Start Time (Julwaniya)", "julwaniya_charging_start_time"),
        ("Charging End Time (Julwaniya)", "julwaniya_charging_end_time"),
        ("KWH (Julwaniya)", "julwaniya_kwh"),
        ("Julwaniya Charging Time", "julwaniya_charging_duration"),
        ("Idle Time at Julwaniya", "idle_time_julwaniya"),
        ("Start KM After Exiting Julwaniya", "start_km_after_julwaniya"),
        ("Closing KM After Reaching Dhule", "closing_km_dhule"),
        ("Toll", "toll_paid_jhulwania_dhule"),
        ("Tonnage Unload", "tonnage_unload"),
        ("To (Dhule)", "to_dhule"),
        ("Dhule Entry Time", "dhule_entry_time"),
        ("Dhule Exit Time", "dhule_exit_time"),
        ("Idle Time at Dhule", "idle_time_dhule"),
        
        ("End SOC (Dhule)", "end_soc_dhule"),
        ("Start SOC (Dhule)", "start_soc_dhule"),
        ("Closing SOC (After Dhule Charging)", "closing_soc_dhule"),
        ("Charging Start Date (Dhule)", "dhule_charging_start_date"),
        ("Charging Start Time (Dhule)", "dhule_charging_start_time"),
        ("Charging End Time (Dhule)", "dhule_charging_end_time"),
        ("KWH (Dhule)", "dhule_kwh"),
        ("Dhule Charging Time", "dhule_charging_duration"),
        
        ("Dhar Reach Date & Time", "dhar_reach_time"),
        ("Trip Closed KM", "trip_closed_km"),
        ("Total Distance (KM)", "total_distance_km"),
        ("All Station Total Charging Hours", "all_station_total_charging_hours"),
        ("Vehicle Total Trip Time", "vehicle_total_trip_time"),
        ("Total KWH", "total_kwh"),
        ("Maintenance", "maintenance"),
    ]
    
    def generate_daily_report(self, trips: List[Dict[str, Any]], start_date: Any = None) -> BytesIO:
        """Generate daily trip report."""
        return self.generate_report(trips, "Daily Trip Report")
    
    def generate_weekly_report(self, trips: List[Dict[str, Any]], start_date: Any = None, end_date: Any = None) -> BytesIO:
        """Generate weekly trip report."""
        return self.generate_report(trips, "Weekly Trip Report")
    
    def generate_monthly_report(self, trips: List[Dict[str, Any]], year: Any = None, month: Any = None) -> BytesIO:
        """Generate monthly trip report."""
        return self.generate_report(trips, "Monthly Trip Report")
    
    def generate_report(
        self,
        trips: List[Dict[str, Any]],
        title: str = "Trip Report"
    ) -> BytesIO:
        """
        Generate Excel report from trip data (optimized for speed).
        
        Args:
            trips: List of trip dictionaries
            title: Report title
            
        Returns:
            BytesIO object containing Excel file
        """
        start_time = time.time()
        logger.info(f"Starting report generation: {len(trips)} trips")
        
        if not trips:
            logger.warning("No trips to generate report")
            trips = []
        
        output = BytesIO()
        
        # Use xlsxwriter directly for maximum speed
        workbook = xlsxwriter.Workbook(output)
        worksheet = workbook.add_worksheet('Trip Report')
        
        # Define formats (minimal - for speed)
        header_fmt = workbook.add_format({
            'bold': True,
            'bg_color': '#4472C4',
            'font_color': 'white',
            'align': 'center',
            'valign': 'vcenter'
        })
        
        # Write headers and initialize max length tracker for auto-fit
        max_lens = []
        for col_num, (col_name, _) in enumerate(self.REPORT_COLUMNS):
            worksheet.write(0, col_num, col_name, header_fmt)
            max_lens.append(len(str(col_name)))
        
        # Freeze panes
        worksheet.freeze_panes(1, 0)
        
        # Write data rows (optimized - format times and decimals) and track max width
        for row_num, trip in enumerate(trips, start=1):
            for col_num, (col_name, field_name) in enumerate(self.REPORT_COLUMNS):
                value = trip.get(field_name)
                
                # Format value
                if value is None:
                    value = ""
                elif isinstance(value, datetime):
                    value = value.strftime("%Y-%m-%d %H:%M:%S")
                elif isinstance(value, date):
                    value = value.strftime("%Y-%m-%d")
                elif isinstance(value, time_obj):
                    # Convert time objects to HH:MM strings
                    value = time_to_string(value)
                elif isinstance(value, Decimal):
                    # Convert Decimal to float
                    value = safe_decimal(value)
                # Check if this is a charging time column
                elif 'Charging Start Time' in col_name or 'Charging End Time' in col_name:
                    value = time_to_string(value)
                
                # Write without format (faster)
                worksheet.write(row_num, col_num, value if value != "" else "")

                # Track maximum string length for this column
                try:
                    ln = len(str(value)) if value is not None else 0
                except Exception:
                    ln = 0
                if ln > max_lens[col_num]:
                    max_lens[col_num] = ln

        # Auto-fit column widths based on tracked max lengths
        for col_num, (col_name, _) in enumerate(self.REPORT_COLUMNS):
            padding = 2
            min_width = 6 if col_num == 0 else 8
            max_width = 40

            # Wider minimum for date/time columns
            if "Time" in col_name or "Date" in col_name:
                min_width = max(min_width, 18)
                max_lens[col_num] = max(max_lens[col_num], 18)

            # Numeric-ish columns
            if ("KM" in col_name) or ("SOC" in col_name) or ("KWH" in col_name):
                min_width = max(min_width, 10)

            width = max(min_width, min(max_lens[col_num] + padding, max_width))
            worksheet.set_column(col_num, col_num, width)
        
        # Close workbook
        workbook.close()
        
        output.seek(0)
        elapsed = time.time() - start_time
        logger.info(f"Report generated in {elapsed:.2f}s: {len(trips)} trips")
        
        return output
