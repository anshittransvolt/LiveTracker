"""
Telemetry API Data Source Adapter

Fetches and transforms Telemetry API response format to standardized vehicle data format
for seamless integration with existing analytics and dashboard code.
"""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone, timedelta
from django.conf import settings

logger = logging.getLogger(__name__)


class TelemetryAPIAdapter:
    """
    Fetches and transforms Telemetry API data for vehicle analytics.
    """

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize Telemetry API adapter.

        Args:
            api_key: API key for Telemetry API authentication
                    If not provided, will use TELEMETRY_API_KEY from settings
        """
        self.api_url = getattr(settings, 'TELEMETRY_API_URL')
        self.api_key = api_key or getattr(settings, 'TELEMETRY_API_KEY')
        self.headers = {
            'x-api-key': self.api_key,
            'Content-Type': 'application/json'
        }
        self.timeout = None  # No timeout - allow API to complete

    def _transform_record(self, record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Transform single Telemetry API record to SmartFastAPI format.

        Args:
            record: Single Telemetry API data record

        Returns:
            Transformed record or None if invalid
        """
        try:
            # Extract and validate essential fields
            registration_number = record.get('registration_number', '')
            if not registration_number:
                logger.warning("Record missing registration_number")
                return None
            
            # GPS coordinates
            latitude = self._safe_float(record.get('latitude'))
            longitude = self._safe_float(record.get('longitude'))
            
            if latitude is None or longitude is None:
                logger.warning(f"Record {registration_number} missing GPS coordinates")
                return None
            
            # Validate GPS coordinates
            if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                logger.warning(f"Record {registration_number} invalid GPS: {latitude},{longitude}")
                return None
            
            # Skip (0,0) coordinates
            if latitude == 0 and longitude == 0:
                logger.debug(f"Record {registration_number} has (0,0) coordinates, skipping")
                return None
            
            # Create gps_location string
            gps_location = f"{latitude},{longitude}"
            
            # Timestamps - use gps_time (milliseconds since epoch) for accurate timestamps
            # event_datetime is just "YYYY-MM-DD", so we use gps_time as primary
            gps_time_ms = record.get('gps_time')
            last_connected = self._convert_milliseconds_to_iso(gps_time_ms) if gps_time_ms else None
            
            # Fallback to event_datetime if gps_time not available
            if not last_connected:
                event_datetime_str = record.get('event_datetime', '')
                last_connected = self._parse_event_datetime(event_datetime_str) if event_datetime_str else None
            
            if not last_connected:
                logger.warning(f"Record {registration_number} missing valid timestamp")
                return None
            
            # Battery and status
            soc = self._safe_int(record.get('soc'), 0, 100)
            battery_temp = self._safe_float(record.get('battery_temp', 0))
            speed = self._safe_float(record.get('speed', 0))
            
            # Derive vehicle status from speed and SOC
            vehicle_status = self._derive_vehicle_status(speed, soc, registration_number)
            
            # Build transformed record
            transformed = {
                # Core vehicle identification
                'vehicle_no': registration_number,
                'registration_number': registration_number,
                'vehicle_id': record.get('device_id', f"VEH{registration_number}"),
                'driver_name': f"DRI{registration_number}",
                
                # GPS fields
                'latitude': latitude,
                'longitude': longitude,
                'gps_location': gps_location,
                'gps_heading': self._safe_float(record.get('head', 0)),
                'gps_speed': speed,
                'speed': speed,
                'altitude': self._safe_float(record.get('altitude', 0)),
                
                # Battery and energy
                'soc': soc,
                'battery_temp': battery_temp,
                'battery_voltage': self._safe_float(record.get('battery_voltage')),
                
                # Status
                'vehicle_status': vehicle_status,
                
                # Timestamps
                'last_connected': last_connected,
                'gps_time': last_connected,  # Already converted to ISO above
                
                # Metadata
                'vendor': record.get('vendor', 'telemetry'),
                'device_id': record.get('device_id', f"DEV{registration_number}"),
                'spv': record.get('spv'),
                'soh': record.get('soh'),
                'charge_cycles': record.get('charge_cycles'),

                # Odometer — sourced from total_vehicle_distance (lifetime km); sparse field
                'odometer': self._safe_float(record.get('total_vehicle_distance') or record.get('odometer')),
            }
            
            return transformed
            
        except Exception as e:
            logger.error(f"Error transforming record: {e}")
            return None

    def _derive_vehicle_status(self, speed: float, soc: int, registration_number: str = None) -> str:
        """
        Derive vehicle status from speed and SOC.
        
        Status determination logic:
        1. If speed > 0 => "Move"
        2. If speed = 0 AND SOC > 0 => "Stop"
        3. Otherwise => "Offline"
        
        Note: Charging status is now detected at geofence level via proper session
        detection logic in geofence_processor._mark_charging_sessions(), not via
        point-to-point SOC comparisons.

        Args:
            speed: GPS speed in km/h
            soc: State of charge percentage
            registration_number: Vehicle registration (no longer used for charging detection)

        Returns:
            Vehicle status string: "Move", "Stop", or "Offline"
        """
        # Handle None values safely
        if speed is None:
            speed = 0
        if soc is None:
            soc = 0
        
        if speed > 0:
            return "Move"
        
        if soc > 0:
            return "Stop"
        
        return "Offline"

    @staticmethod
    def _safe_float(value: Any, default: float = None) -> Optional[float]:
        """Safely convert value to float."""
        try:
            if value is None or value == '':
                return default
            return float(value)
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _safe_int(value: Any, minimum: int = None, maximum: int = None, default: int = 0) -> int:
        """Safely convert value to int with optional bounds."""
        try:
            if value is None or value == '':
                return default
            # Handle string floats like '30.0' by converting to float first
            result = int(float(value))
            
            if minimum is not None and result < minimum:
                return minimum
            if maximum is not None and result > maximum:
                return maximum
            
            return result
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _parse_event_datetime(datetime_str: str) -> Optional[str]:
        """
        Parse event_datetime in "YYYY-MM-DD" format to ISO format with IST timezone.
        
        Args:
            datetime_str: DateTime string in "YYYY-MM-DD" format
            
        Returns:
            ISO format datetime string with IST timezone, or None if parsing fails
        """
        try:
            # Parse "YYYY-MM-DD" format
            dt = datetime.strptime(datetime_str, "%Y-%m-%d")
            # Add IST timezone (UTC+05:30)
            iso_str = dt.strftime("%Y-%m-%dT00:00:00+05:30")
            return iso_str
        except Exception as e:
            logger.warning(f"Error parsing datetime '{datetime_str}': {e}")
            return None

    @staticmethod
    def _convert_milliseconds_to_iso(milliseconds: Any) -> Optional[str]:
        """Convert milliseconds since epoch to ISO format."""
        try:
            if milliseconds is None:
                return None
            
            # Convert to seconds
            seconds = int(milliseconds) / 1000
            # Create datetime from timestamp
            dt = datetime.fromtimestamp(seconds, tz=timezone.utc)
            # Format as ISO
            return dt.isoformat()
        except Exception as e:
            logger.warning(f"Error converting milliseconds '{milliseconds}': {e}")
            return None

    def transform_batch(self, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Transform batch of Telemetry API records.

        Args:
            records: List of Telemetry API records

        Returns:
            Dictionary keyed by registration_number with transformed data
        """
        transformed = {}
        
        for record in records:
            transformed_record = self._transform_record(record)
            if not transformed_record:
                continue
            
            reg_no = transformed_record['registration_number']
            
            if reg_no not in transformed:
                transformed[reg_no] = {
                    'points': [],
                    'vehicle_data': {}
                }
            
            transformed[reg_no]['points'].append(transformed_record)
            transformed[reg_no]['vehicle_data'] = transformed_record  # Latest
        
        return transformed


# Convenience functions
def transform_telemetry_data(records: List[Dict[str, Any]], api_key: Optional[str] = None) -> Dict[str, Any]:
    """
    Convenience function to transform Telemetry API data.
    
    Args:
        records: List of Telemetry API records
        api_key: Optional API key override
        
    Returns:
        Transformed data keyed by registration_number
    """
    adapter = TelemetryAPIAdapter(api_key)
    return adapter.transform_batch(records)


def transform_single_telemetry_record(record: Dict[str, Any], api_key: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Convenience function to transform single Telemetry API record.
    
    Args:
        record: Single Telemetry API record
        api_key: Optional API key override
        
    Returns:
        Transformed record or None if invalid
    """
    adapter = TelemetryAPIAdapter(api_key)
    return adapter._transform_record(record)
