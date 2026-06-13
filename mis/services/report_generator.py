"""
Report Generator Service
========================
Generates Excel reports from merged trip data.
"""

import logging
from typing import List, Dict, Any
from datetime import date, datetime
import pandas as pd
from io import BytesIO
import xlsxwriter
from livetracker.vehicle_mapping import get_display_vehicle_number

logger = logging.getLogger(__name__)


class ReportGenerator:
    """Generate Excel reports from trip data."""
    
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
    
    def generate_daily_report(
        self,
        trips: List[Dict[str, Any]],
        report_date: date
    ) -> BytesIO:
        """
        Generate daily report for a specific date.
        
        Args:
            trips: List of merged trip dictionaries
            report_date: Date for the report
            
        Returns:
            BytesIO object containing Excel file
        """
        logger.info(f"Generating daily report for {report_date}")
        
        # Filter trips for this date
        daily_trips = [t for t in trips if t.get('log_date') == report_date]
        
        return self._generate_excel(daily_trips, f"Daily Report - {report_date}")
    
    def generate_weekly_report(
        self,
        trips: List[Dict[str, Any]],
        start_date: date,
        end_date: date
    ) -> BytesIO:
        """
        Generate weekly report.
        
        Args:
            trips: List of merged trip dictionaries
            start_date: Start date
            end_date: End date
            
        Returns:
            BytesIO object containing Excel file
        """
        logger.info(f"Generating weekly report: {start_date} to {end_date}")
        
        return self._generate_excel(trips, f"Weekly Report - {start_date} to {end_date}")
    
    def generate_monthly_report(
        self,
        trips: List[Dict[str, Any]],
        year: int,
        month: int
    ) -> BytesIO:
        """
        Generate monthly report.
        
        Args:
            trips: List of merged trip dictionaries
            year: Year
            month: Month (1-12)
            
        Returns:
            BytesIO object containing Excel file
        """
        logger.info(f"Generating monthly report for {year}-{month:02d}")
        
        return self._generate_excel(trips, f"Monthly Report - {year}-{month:02d}")
    
    def _generate_excel(
        self,
        trips: List[Dict[str, Any]],
        title: str
    ) -> BytesIO:
        """
        Generate Excel file from trip data.
        
        Args:
            trips: List of trip dictionaries
            title: Report title
            
        Returns:
            BytesIO object containing Excel file
        """
        if not trips:
            logger.warning("No trips to generate report")
            trips = []
        
        # Sort trips by log_date ascending before numbering
        def _sort_key(t):
            d = t.get('log_date')
            if isinstance(d, str):
                try:
                    from datetime import datetime as _dt
                    return _dt.strptime(d, "%Y-%m-%d").date()
                except Exception:
                    pass
            return d or date.min

        trips = sorted(trips, key=_sort_key)

        # Prepare data rows
        rows = []
        for idx, trip in enumerate(trips, start=1):
            row = {'sr_no': idx}
            
            for col_name, field_name in self.REPORT_COLUMNS[1:]:  # Skip Sr.No
                value = trip.get(field_name)
                
                # Apply vehicle mapping for display
                if field_name in ('vehicle_no', 'horse_no_jhulwaniya') and value:
                    try:
                        value = get_display_vehicle_number(value)
                    except Exception:
                        # Fallback to original value on any mapping error
                        pass
                
                # Format values
                from decimal import Decimal
                if value is None:
                    row[field_name] = ""
                elif isinstance(value, datetime):
                    row[field_name] = value.strftime("%Y-%m-%d %H:%M:%S")
                elif isinstance(value, date):
                    row[field_name] = value.strftime("%Y-%m-%d")
                elif isinstance(value, Decimal):
                    row[field_name] = float(value)
                else:
                    row[field_name] = value
            
            # Add calculated fields
            row['to_julwaniya'] = "Julwaniya"
            row['to_dhule'] = "Dhule"
            # Return Julwaniya columns removed
            row['closing_km_previous_trip'] = ""  # TODO: Calculate from previous trip
            row['end_soc_previous_trip'] = ""  # TODO: Calculate from previous trip
            
            rows.append(row)
        
        # Create DataFrame
        df_data = []
        for row in rows:
            df_row = {}
            for col_name, field_name in self.REPORT_COLUMNS:
                df_row[col_name] = row.get(field_name, "")
            df_data.append(df_row)
        
        df = pd.DataFrame(df_data)
        
        # Write to Excel with formatting
        output = BytesIO()
        
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, sheet_name='Trip Report', index=False)
            
            # Get workbook and worksheet objects
            workbook = writer.book
            worksheet = writer.sheets['Trip Report']
            
            # Add formats
            header_format = workbook.add_format({
                'bold': True,
                'bg_color': '#4472C4',
                'font_color': 'white',
                'border': 1,
                'text_wrap': True,
                'valign': 'vcenter',
                'align': 'center'
            })
            
            cell_format = workbook.add_format({
                'border': 1,
                'text_wrap': True,
                'valign': 'top'
            })
            
            # Format header row
            for col_num, col_name in enumerate(df.columns):
                worksheet.write(0, col_num, col_name, header_format)

            # Auto-fit column widths based on data and header
            if len(df.columns) > 0:
                for col_num, col_name in enumerate(df.columns):
                    # Calculate max content width for this column
                    try:
                        series = df[col_name].fillna("").astype(str)
                        max_content_len = int(series.map(len).max()) if not df.empty else 0
                    except Exception:
                        max_content_len = 0

                    header_len = len(str(col_name))
                    max_len = max(max_content_len, header_len)

                    # Sensible bounds and padding
                    padding = 2
                    min_width = 6 if col_num == 0 else 8
                    max_width = 40

                    # Slightly wider for datetime-like columns
                    if "Time" in col_name or "Date" in col_name:
                        min_width = max(min_width, 18)
                        max_len = max(max_len, 18)

                    # Numeric-ish columns typically need a bit more than digits
                    if ("KM" in col_name) or ("SOC" in col_name) or ("KWH" in col_name):
                        min_width = max(min_width, 10)

                    width = max(min_width, min(max_len + padding, max_width))
                    worksheet.set_column(col_num, col_num, width)
            
            # Freeze first row and column
            worksheet.freeze_panes(1, 1)
            
            # Add summary row if data exists
            if len(df) > 0:
                summary_row = len(df) + 2
                worksheet.write(summary_row, 0, "SUMMARY", header_format)
                
                # Add summary formulas
                try:
                    tonnage_load_col = df.columns.get_loc("Tonnage Load")
                    tonnage_unload_col = df.columns.get_loc("Tonnage Unload")
                    total_kwh_col = df.columns.get_loc("Total KWH")
                    
                    worksheet.write(summary_row, tonnage_load_col, 
                                  f'=SUM({xlsxwriter.utility.xl_col_to_name(tonnage_load_col)}2:{xlsxwriter.utility.xl_col_to_name(tonnage_load_col)}{len(df)+1})',
                                  cell_format)
                    worksheet.write(summary_row, tonnage_unload_col,
                                  f'=SUM({xlsxwriter.utility.xl_col_to_name(tonnage_unload_col)}2:{xlsxwriter.utility.xl_col_to_name(tonnage_unload_col)}{len(df)+1})',
                                  cell_format)
                    worksheet.write(summary_row, total_kwh_col,
                                  f'=SUM({xlsxwriter.utility.xl_col_to_name(total_kwh_col)}2:{xlsxwriter.utility.xl_col_to_name(total_kwh_col)}{len(df)+1})',
                                  cell_format)
                except Exception as e:
                    logger.warning(f"Failed to add summary formulas: {e}")
        
        output.seek(0)
        logger.info(f"Generated Excel report with {len(trips)} trips")
        return output
