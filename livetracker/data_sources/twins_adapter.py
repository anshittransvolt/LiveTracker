"""
TWINS API Data Source Adapter

Fetches and transforms TWINS API response format to standardized vehicle data format
for seamless integration with existing analytics and dashboard code.
"""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone, timedelta
import requests
from django.conf import settings
import json
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


class TwinsAPIAdapter:
    """
    Fetches and transforms TWINS API data for vehicle tracking.
    """

    def __init__(self, auth_token: Optional[str] = None):
        """
        Initialize TWINS API adapter.

        Args:
            auth_token: JWT Bearer token for TWINS API authentication
                       If not provided, will use TWINS_API_TOKEN from settings
        """
        self.api_url = getattr(settings, 'TWINS_API_URL', 'http://127.0.0.1:9000/latest_points')
        # Be resilient to base URL in settings/env; append latest_points endpoint if needed
        try:
            if isinstance(self.api_url, str):
                url = self.api_url.strip()
                if url.endswith('/') and 'latest_points' not in url:
                    self.api_url = url.rstrip('/') + '/latest_points'
        except Exception:
            pass
        # Default query param values (can be overridden per call)
        self.default_vendor = getattr(settings, 'TWINS_VENDOR', 'intangles')
        self.default_spv = getattr(settings, 'TWINS_SPV', 'ultratech')
        self.auth_token = auth_token or getattr(settings, 'TWINS_API_TOKEN', '')
        self.headers = {
            'Authorization': f'Bearer {self.auth_token}',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
        self.timeout = 60
        # Cache for tracking SOC trends per vehicle for charging detection
        self.soc_history = {}  # {registration_number: current_soc}

    def fetch_all_vehicles(self, vendor: Optional[str] = None, spv: Optional[str] = None, limit: int = None) -> Dict[str, Any]:
        """
        Fetch all vehicles data from TWINS API and transform to SmartFastAPI format.

        Args:
            vendor: Vendor filter (default from settings or 'iplt')
            spv: SPV filter (default from settings or 'ultratech')
            limit: Maximum number of vehicles to fetch (optional)

        Returns:
            Dictionary keyed by registration_number with transformed vehicle data
        """
        try:
            # /latest_points doesn't accept a spv filter and mixes all of a vendor's
            # SPVs together — fetch by vendor only and filter by spv locally below.
            params = {}
            vendor_q = vendor if vendor is not None else self.default_vendor
            spv_q = spv if spv is not None else self.default_spv
            if vendor_q:
                params['vendor'] = vendor_q
            if limit:
                params['limit'] = limit

            logger.info(f"Fetching TWINS API data: {self.api_url} with params {params}")
            
            # Use Session with retries
            session = requests.Session()
            retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[502, 503, 504], raise_on_status=False)
            adapter = HTTPAdapter(max_retries=retries)
            session.mount('http://', adapter)
            session.mount('https://', adapter)

            try:
                # Stream response to avoid IncompleteRead on large payloads
                resp = session.get(self.api_url, headers=self.headers, params=params, timeout=self.timeout, stream=True)
            except requests.exceptions.RequestException as e:
                logger.error(f"TWINS API request error: {e}")
                return {}
            
            if resp.status_code != 200:
                try:
                    body = resp.text[:500]
                except Exception:
                    body = ''
                logger.error(f"TWINS API returned status {resp.status_code}: {body}")
                return {}
            # Accumulate streamed content
            try:
                content_chunks = []
                for chunk in resp.iter_content(chunk_size=65536):
                    if chunk:
                        content_chunks.append(chunk)
                content = b''.join(content_chunks)
                raw_data = json.loads(content.decode('utf-8'))
            except Exception as e:
                logger.error(f"Failed to read/parse TWINS API response: {e}")
                return {}
            logger.info(f"Received TWINS API response (type: {type(raw_data).__name__})")
            
            # Handle both list and dict responses
            spv_upper = (spv_q or '').strip().upper()
            if isinstance(raw_data, dict):
                # If response is {'vehicles': {'reg_no': [...]}}
                vehicles_dict = raw_data.get('vehicles', {})
                if isinstance(vehicles_dict, dict):
                    # Flatten to list, keeping only points matching the requested spv
                    # (a vendor's /latest_points response mixes all its SPVs together)
                    all_points = []
                    for reg_no, points in vehicles_dict.items():
                        if not isinstance(points, list):
                            continue
                        if spv_upper:
                            points = [p for p in points if (p.get('spv') or '').strip().upper() == spv_upper]
                        all_points.extend(points)
                    raw_data = all_points
                else:
                    raw_data = [raw_data]
            elif not isinstance(raw_data, list):
                raw_data = [raw_data]
            
            # Transform and group by registration_number
            transformed_data = self._transform_batch(raw_data)
            grouped_data = self._group_by_vehicle(transformed_data)
            
            logger.info(f"Successfully transformed {len(grouped_data)} vehicles")
            return grouped_data

        except requests.exceptions.Timeout:
            logger.error("TWINS API request timeout")
            return {}
        except requests.exceptions.ConnectionError as e:
            logger.error(f"TWINS API connection error: {e}")
            return {}
        except requests.exceptions.RequestException as e:
            logger.error(f"TWINS API request error: {e}")
            return {}
        except Exception as e:
            logger.error(f"Error fetching TWINS API data: {e}", exc_info=True)
            return {}

    def fetch_single_vehicle(self, registration_number: str) -> List[Dict[str, Any]]:
        """
        Fetch single vehicle data from TWINS API.
        (Note: TWINS API may not support per-vehicle filtering, returns fetch_combined output)

        Args:
            registration_number: Vehicle registration number

        Returns:
            List of transformed data points for the vehicle
        """
        try:
            all_vehicles = self.fetch_all_vehicles()
            
            if registration_number in all_vehicles:
                return all_vehicles[registration_number].get('points', [])
            else:
                logger.warning(f"Vehicle {registration_number} not found in TWINS API response")
                return []

        except Exception as e:
            logger.error(f"Error fetching single vehicle {registration_number}: {e}")
            return []

    def _transform_batch(self, raw_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Transform batch of TWINS API records to SmartFastAPI format.

        Args:
            raw_data: List of raw TWINS API records

        Returns:
            List of transformed records
        """
        transformed = []
        null_gps_vehicles = set()

        for record in raw_data:
            try:
                transformed_record = self._transform_record(record)
                if transformed_record:
                    transformed.append(transformed_record)
                else:
                    reg = record.get('registration_number', 'unknown')
                    null_gps_vehicles.add(reg)
            except Exception as e:
                logger.warning(f"Error transforming record: {e}")
                continue

        # Only report vehicles that had NO valid points at all (not those that merely
        # had some null-GPS historical points alongside valid ones).
        valid_reg_nos = {r.get('registration_number') for r in transformed}
        truly_skipped = null_gps_vehicles - valid_reg_nos

        logger.info(f"Unique vehicles with valid GPS: {len(valid_reg_nos)}")
        if truly_skipped:
            logger.warning(
                f"{len(truly_skipped)} vehicle(s) with no valid GPS in any point: "
                f"{', '.join(sorted(truly_skipped))}"
            )

        return transformed

    def _transform_record(self, record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Transform single TWINS API record to SmartFastAPI format.

        Args:
            record: Single TWINS API data record

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
                logger.debug(f"Record {registration_number} missing GPS coordinates")
                return None
            
            # Create gps_location string
            gps_location = f"{latitude},{longitude}"
            
            # Timestamps
            event_datetime = record.get('event_datetime', '')
            last_connected = self._parse_datetime(event_datetime) if event_datetime else None
            
            gps_time_ms = record.get('gps_time')
            gps_time = self._convert_milliseconds_to_iso(gps_time_ms) if gps_time_ms else last_connected
            
            # If no last_connected, use gps_time
            if not last_connected:
                last_connected = gps_time
            
            if not last_connected:
                logger.debug(f"Record {registration_number} missing timestamp")
                return None
            
            # Battery and status
            soc = self._safe_int(record.get('soc', 0), 0, 100)
            battery_temp = self._safe_float(record.get('battery_temp', 0))
            speed = self._safe_float(record.get('speed', 0))
            
            # Derive vehicle status from speed, SOC, and charging trend
            vehicle_status = self._derive_vehicle_status(speed, soc, registration_number)
            
            # Build transformed record
            transformed = {
                # Core vehicle identification
                'vehicle_no': registration_number,
                'registration_number': registration_number,
                'vehicle_id': record.get('device_id', ''),
                'driver_name': f"DRI{registration_number}",
                
                # GPS fields
                'latitude': latitude,
                'longitude': longitude,
                'gps_location': gps_location,
                'gps_heading': self._safe_float(record.get('head', 0)),
                'gps_speed': speed,
                'speed': speed,
                
                # Battery and energy
                'soc': soc,
                'battery_temp': battery_temp,
                'battery_voltage': self._safe_float(record.get('battery_voltage')),
                
                # Status
                'vehicle_status': vehicle_status,
                
                # Timestamps
                'last_connected': last_connected,
                'gps_time': gps_time,
                
                # Additional metadata
                'altitude': self._safe_float(record.get('altitude')),
                'satellites': self._safe_int(record.get('satellites', 0)),
                'accuracy_level': self._safe_int(record.get('accuracy_level', 0)),
                'vendor': record.get('vendor', ''),
                'device_id': record.get('device_id', ''),
                'odometer': self._safe_float(record.get('odometer')),
                'account_name': record.get('account_name', ''),
            }
            
            return transformed

        except Exception as e:
            logger.error(f"Error transforming record {record.get('registration_number', 'unknown')}: {e}")
            return None

    def _group_by_vehicle(self, transformed_data: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """
        Group transformed records by registration_number (matching SmartFastAPI format).

        Args:
            transformed_data: List of transformed records

        Returns:
            Dictionary keyed by registration_number with 'points' array
        """
        grouped = {}
        
        for record in transformed_data:
            reg_no = record.get('registration_number', '')
            
            if reg_no not in grouped:
                grouped[reg_no] = {
                    'registration_number': reg_no,
                    'points': []
                }
            
            grouped[reg_no]['points'].append(record)
        
        # Sort points by last_connected (newest first, matching SmartFastAPI)
        for vehicle in grouped.values():
            try:
                vehicle['points'].sort(
                    key=lambda p: p.get('last_connected', '') or '',
                    reverse=True
                )
            except Exception as e:
                logger.warning(f"Error sorting points: {e}")
        
        return grouped

    def _is_charging(self, registration_number: str, current_soc: int) -> bool:
        """
        Detect if vehicle is charging based on SOC trend.
        
        A vehicle is considered charging if current SOC is greater than
        the previously recorded SOC (SOC is increasing along the points).
        
        Args:
            registration_number: Vehicle registration number
            current_soc: Current state of charge percentage
            
        Returns:
            True if vehicle is charging, False otherwise
        """
        try:
            if registration_number not in self.soc_history:
                # First time seeing this vehicle, store and can't compare
                self.soc_history[registration_number] = current_soc
                return False
            
            previous_soc = self.soc_history[registration_number]
            self.soc_history[registration_number] = current_soc
            
            # Vehicle is charging if SOC is increasing
            is_charging = current_soc > previous_soc
            if is_charging:
                logger.debug(f"Vehicle {registration_number} charging: SOC {previous_soc}% -> {current_soc}%")
            return is_charging
        except Exception as e:
            logger.warning(f"Error checking charging status for {registration_number}: {e}")
            return False

    def _derive_vehicle_status(self, speed: float, soc: int, registration_number: str = None) -> str:
        """
        Derive vehicle status from speed and SOC.
        
        Status determination logic:
        1. If speed > 0 => "Move"
        2. If speed = 0 AND SOC increasing => "Charging"
        3. If speed = 0 AND SOC > 0 => "Stop"
        4. Otherwise => "Offline"

        Args:
            speed: GPS speed in km/h
            soc: State of charge percentage
            registration_number: Vehicle registration for charging detection

        Returns:
            Vehicle status string: "Move", "Charging", "Stop", or "Offline"
        """
        # If moving, it's definitely in motion
        if speed > 0:
            return "Move"
        
        # Vehicle is stationary (speed = 0)
        if registration_number and self._is_charging(registration_number, soc):
            return "Charging"
        
        # Has power but not moving and not charging
        if soc > 0:
            return "Stop"
        
        # No power, offline
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
            result = int(value)
            
            if minimum is not None and result < minimum:
                return minimum
            if maximum is not None and result > maximum:
                return maximum
            
            return result
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _parse_datetime(datetime_str: str) -> Optional[str]:
        """
        Parse datetime string and return ISO format with timezone.

        Supports:
        - ISO format: "2026-01-30T10:31:50+05:30"
        - Custom format: "2026-01-30 10:31:50"

        Args:
            datetime_str: Datetime string to parse

        Returns:
            ISO format string with +05:30 timezone, or None if parsing fails
        """
        if not datetime_str or not isinstance(datetime_str, str):
            return None
        
        try:
            # Try ISO format first
            if 'T' in datetime_str:
                dt = datetime.fromisoformat(datetime_str.replace('Z', '+00:00'))
            else:
                # Try custom format: "2026-01-30 10:31:50"
                dt = datetime.strptime(datetime_str.strip(), "%Y-%m-%d %H:%M:%S")
            
            # Convert to ISO with IST timezone (+05:30)
            if dt.tzinfo is None:
                # Assume IST if no timezone
                dt = dt.replace(tzinfo=timezone.utc).astimezone(
                    timezone(timedelta(hours=5, minutes=30))
                )
            
            return dt.isoformat()
        
        except Exception as e:
            logger.warning(f"Error parsing datetime '{datetime_str}': {e}")
            return None

    @staticmethod
    def _convert_milliseconds_to_iso(timestamp_ms: Any) -> Optional[str]:
        """
        Convert millisecond timestamp to ISO format string.

        Args:
            timestamp_ms: Timestamp in milliseconds

        Returns:
            ISO format string or None if conversion fails
        """
        try:
            if timestamp_ms is None:
                return None
            
            # Convert milliseconds to seconds
            timestamp_sec = int(timestamp_ms) / 1000.0
            dt = datetime.fromtimestamp(timestamp_sec, tz=timezone.utc)
            
            # Convert to IST (+05:30)
            ist = timezone(timedelta(hours=5, minutes=30))
            dt_ist = dt.astimezone(ist)
            
            return dt_ist.isoformat()
        
        except Exception as e:
            logger.warning(f"Error converting timestamp {timestamp_ms}: {e}")
            return None


# Convenience function for quick access
def fetch_twins_vehicles(vendor: str = 'intangles', limit: int = None) -> Dict[str, Any]:
    """
    Fetch vehicles from TWINS API and return in SmartFastAPI format.

    Args:
        vendor: Vendor filter
        limit: Maximum vehicles to fetch

    Returns:
        Dictionary of vehicles keyed by registration_number
    """
    adapter = TwinsAPIAdapter()
    return adapter.fetch_all_vehicles(vendor=vendor, limit=limit)


def fetch_twins_single_vehicle(registration_number: str) -> List[Dict[str, Any]]:
    """
    Fetch single vehicle from TWINS API.

    Args:
        registration_number: Vehicle registration number

    Returns:
        List of data points for the vehicle
    """
    adapter = TwinsAPIAdapter()
    return adapter.fetch_single_vehicle(registration_number)
