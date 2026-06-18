"""
Data Sources Module

Provides multiple data source adapters for vehicle tracking:
- Telemetry API: Historical vehicle data (PRIMARY)
- TWINS API: Current/recent vehicle positions (ALTERNATIVE)

All adapters transform their respective APIs to a standardized vehicle data format
for seamless integration with existing analytics code.
"""

from .twins_adapter import (
    TwinsAPIAdapter,
    fetch_twins_vehicles,
    fetch_twins_single_vehicle,
)

from .telemetry_adapter import (
    TelemetryAPIAdapter,
    transform_telemetry_data,
    transform_single_telemetry_record,
)

from .data_source_manager import (
    DataSourceManager,
    get_all_vehicles,
    get_vehicle_data,
    get_historical_data,
    fetch_range_as_dataframe,
)

from .session_detectors import (
    detect_charging_sessions,
    detect_stoppage_sessions,
)

from .fetch_geo_utils import fetch_timebox_data_from_fetch_geo

__all__ = [
    # TWINS Adapter
    'TwinsAPIAdapter',
    'fetch_twins_vehicles',
    'fetch_twins_single_vehicle',
    
    # Telemetry Adapter
    'TelemetryAPIAdapter',
    'transform_telemetry_data',
    'transform_single_telemetry_record',
    
    # Data Source Manager
    'DataSourceManager',
    'get_all_vehicles',
    'get_vehicle_data',
    'get_historical_data',  # NEW - preferred for historical data
    'fetch_range_as_dataframe',  # NEW - for MIS and batch processing (returns pandas DataFrame)
    # Session detectors
    'detect_charging_sessions',
    'detect_stoppage_sessions',
    'fetch_timebox_data_from_fetch_geo',
]
