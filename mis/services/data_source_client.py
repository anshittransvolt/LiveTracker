"""
MIS Data Source Client
======================
Unified interface for MIS to fetch telemetry data from the centralized data_sources module
(which routes through Telemetry API via DataSourceManager).

This replaces direct calls to TelemetryFetcher and SmartFastAPI, making data source
changes transparent to MIS business logic.
"""

import logging
from datetime import date, datetime
from typing import Optional
import pandas as pd

from livetracker.data_sources import fetch_range_as_dataframe

logger = logging.getLogger(__name__)


def fetch_telemetry_range(
    start_date: date,
    end_date: date,
    vehicle_no: Optional[str] = None
) -> pd.DataFrame:
    """
    Fetch telemetry data for a date range from centralized data_sources.
    
    MIS entry point to replace TelemetryFetcher.fetch_range().
    
    Args:
        start_date: Start date
        end_date: End date
        vehicle_no: Optional specific vehicle registration number
        
    Returns:
        pandas DataFrame with telemetry data, sorted by vehicle_no and gps_time (ascending)
        Columns: vehicle_no, vehicle_id, soc, battery_temp, gps_speed, gps_location,
                 vehicle_status, gps_time, last_connected, etc.
    """
    try:
        start_str = start_date.strftime("%Y-%m-%d") if isinstance(start_date, date) else str(start_date)
        end_str = end_date.strftime("%Y-%m-%d") if isinstance(end_date, date) else str(end_date)
        
        logger.info(f"Fetching telemetry: {start_str} to {end_str}, vehicle: {vehicle_no or 'all'}")
        
        df = fetch_range_as_dataframe(
            start_date=start_str,
            end_date=end_str,
            vehicle_no=vehicle_no
        )
        
        if df.empty:
            logger.warning(f"No telemetry data for {start_str} to {end_str}, vehicle: {vehicle_no or 'all'}")
        else:
            logger.info(f"Fetched {len(df)} telemetry records")
        
        return df
        
    except Exception as e:
        logger.error(f"Failed to fetch telemetry: {e}")
        raise Exception(f"Failed to fetch telemetry data: {str(e)}")
