"""
Telemetry Fetcher Service (LEGACY - Use data_source_client instead)
==========================
Fetches vehicle telemetry data from SmartFastAPI endpoint.

DEPRECATED: Use mis.services.data_source_client.fetch_telemetry_range() instead.
This will call the centralized livetracker.data_sources via Telemetry API.
"""

import requests
import logging
from datetime import date, datetime
from typing import List, Dict, Any, Optional
from django.conf import settings
import pandas as pd

from .data_source_client import fetch_telemetry_range

logger = logging.getLogger(__name__)


class TelemetryFetcher:
    """
    Fetches vehicle telemetry data.
    
    DEPRECATED: Now delegates to centralized data_source_client which routes through
    livetracker.data_sources and Telemetry API. Kept for backward compatibility.
    """
    
    def __init__(self):
        self.base_url = settings.SMARTFASTAPI_DOMAIN
        self.access_key = settings.SMARTFASTAPI_ACCESS_KEY
        logger.warning("TelemetryFetcher is deprecated. Use data_source_client.fetch_telemetry_range() instead.")
        
    def fetch_range(
        self, 
        start_date: date, 
        end_date: date, 
        vehicle_no: Optional[str] = None
    ) -> pd.DataFrame:
        """
        Fetch telemetry data for date range.
        
        DEPRECATED: Delegates to data_source_client which uses centralized data_sources.
        
        Args:
            start_date: Start date
            end_date: End date
            vehicle_no: Optional specific vehicle number
            
        Returns:
            DataFrame with telemetry data via centralized data source
        """
        logger.info("TelemetryFetcher.fetch_range() delegating to centralized data_source_client")
        return fetch_telemetry_range(start_date, end_date, vehicle_no)
        
        # Sort by vehicle and time
        df = df.sort_values(['vehicle_no', 'last_connected']).reset_index(drop=True)
        
        return df
