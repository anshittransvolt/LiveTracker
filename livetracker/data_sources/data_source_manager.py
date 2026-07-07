"""
Integration layer for TWINS API and Telemetry API in livetracker views.

Provides drop-in replacement functions for vehicle data calls.
Supports switching between data sources transparently.

Data Source Priority:
1. Telemetry API - Historical vehicle data (PRIMARY - for playback/analytics)
2. TWINS API - Current/recent vehicle positions (ALTERNATIVE)

SmartFastAPI support has been removed (deprecated/non-functional).
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from django.conf import settings
from .twins_adapter import TwinsAPIAdapter
from .telemetry_adapter import TelemetryAPIAdapter
from .fetch_geo_adapter import FetchGeoAdapter

logger = logging.getLogger(__name__)


class DataSourceManager:
    """
    Manager to switch between TWINS API and Telemetry API data sources.
    
    Telemetry API is the primary source for historical data.
    TWINS API provides current/recent data as alternative.
    """
    
    # Configuration (loaded from settings/env)
    USE_TWINS_API = getattr(settings, 'USE_TWINS_API', False)
    USE_TELEMETRY_API = getattr(settings, 'USE_TELEMETRY_API', True)
    TELEMETRY_API_URL = getattr(settings, 'TELEMETRY_API_URL')
    TELEMETRY_API_KEY = getattr(settings, 'TELEMETRY_API_KEY')
    
    @staticmethod
    def fetch_all_vehicles() -> Dict[str, Any]:
        """
        Fetch all vehicles from available sources.
        
        Returns:
            Dictionary of vehicles keyed by registration_number
        """
        try:
            if DataSourceManager.USE_TWINS_API:
                logger.info("Fetching all vehicles from TWINS API")
                adapter = TwinsAPIAdapter()
                return adapter.fetch_all_vehicles()
            else:
                logger.info("TWINS API not enabled. Use Telemetry API for specific vehicle data.")
                return {}
        
        except Exception as e:
            logger.error(f"Error fetching all vehicles from TWINS: {e}")
            return {}
    
    @staticmethod
    def _fetch_iplt_historical_data(registration_number: str, start_date: str, end_date: str, spv: str) -> Dict[str, Any]:
        """
        Fetch and merge location + BMS data for iplt vendor.

        iplt exposes data via two separate endpoints:
          - /location  — GPS position, speed, gps_time
          - /bms       — SOC, voltage, current, temperatures, gps_time

        We fetch both concurrently and merge on nearest gps_time using a
        two-pointer approach, matching each location point to its closest BMS
        record.

        Returns:
            Dict with 'points' key containing merged, transformed data points.
        """
        import requests
        import concurrent.futures
        from datetime import datetime, timezone

        api_base = getattr(settings, 'VOLTRACK_API_BASE_URL', '').rstrip('/')
        api_token = getattr(settings, 'VOLTRACK_API_TOKEN', '') or getattr(settings, 'TELEMETRY_API_KEY', '')
        headers = {'x-api-key': api_token} if api_token else {}

        common_params = {
            'registration_number': registration_number,
            'vendor': 'iplt',
            'spv': spv,
            'start_date': start_date,
            'end_date': end_date,
        }

        def _get(endpoint):
            url = f"{api_base}/{endpoint}"
            resp = requests.get(url, params=common_params, headers=headers, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else data.get('data', [])

        # Fetch location and BMS in parallel
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            loc_future = pool.submit(_get, 'location')
            bms_future = pool.submit(_get, 'bms')
            try:
                loc_raw = loc_future.result()
            except Exception as exc:
                logger.warning(f"iplt /location fetch failed for {registration_number}: {exc}")
                loc_raw = []
            try:
                bms_raw = bms_future.result()
            except Exception as exc:
                logger.warning(f"iplt /bms fetch failed for {registration_number}: {exc}")
                bms_raw = []

        if not loc_raw:
            logger.debug(f"iplt: no location data for {registration_number}")
            return {'points': []}

        def _parse_ts(value):
            """Parse gps_time (seconds or ms epoch, or ISO string) → epoch seconds float."""
            if value is None:
                return None
            try:
                v = float(value)
                # Heuristic: timestamps > 1e12 are milliseconds; <= 1e12 are seconds
                # Year 2001+ in ms  = 978307200000 (>1e12 only for ms)
                # Year 2286  in sec = ~1e13 (safe upper bound for seconds)
                return v / 1000.0 if v > 1e12 else v
            except (ValueError, TypeError):
                pass
            try:
                # ISO string
                for fmt in ('%Y-%m-%dT%H:%M:%S%z', '%Y-%m-%dT%H:%M:%SZ', '%Y-%m-%d %H:%M:%S'):
                    try:
                        dt = datetime.strptime(str(value), fmt)
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        return dt.timestamp()
                    except ValueError:
                        continue
            except Exception:
                pass
            return None

        def _to_iso(ts_seconds):
            if ts_seconds is None:
                return None
            return datetime.fromtimestamp(ts_seconds, tz=timezone.utc).isoformat()

        def _safe_float(v, default=None):
            try:
                return float(v) if v is not None and v != '' else default
            except (ValueError, TypeError):
                return default

        def _safe_int(v, lo=None, hi=None, default=0):
            try:
                r = int(float(v))
                if lo is not None and r < lo:
                    return lo
                if hi is not None and r > hi:
                    return hi
                return r
            except (ValueError, TypeError):
                return default

        # Parse and sort location points
        loc_points = []
        for r in loc_raw:
            ts = _parse_ts(r.get('gps_time'))
            lat = _safe_float(r.get('latitude'))
            lng = _safe_float(r.get('longitude'))
            if ts is None or lat is None or lng is None:
                continue
            if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                continue
            if lat == 0.0 and lng == 0.0:
                continue
            loc_points.append({'ts': ts, 'rec': r, 'lat': lat, 'lng': lng})
        loc_points.sort(key=lambda x: x['ts'])

        # Parse and sort BMS points
        bms_points = []
        for r in bms_raw:
            ts = _parse_ts(r.get('gps_time'))
            if ts is None:
                continue
            bms_points.append({'ts': ts, 'rec': r})
        bms_points.sort(key=lambda x: x['ts'])

        # Two-pointer merge: for each loc point find nearest BMS record
        bms_ptr = 0
        merged = []
        for loc in loc_points:
            while (
                bms_ptr < len(bms_points) - 1 and
                abs(bms_points[bms_ptr + 1]['ts'] - loc['ts']) <= abs(bms_points[bms_ptr]['ts'] - loc['ts'])
            ):
                bms_ptr += 1

            loc_rec = loc['rec']
            bms_rec = bms_points[bms_ptr]['rec'] if bms_points else {}

            speed = _safe_float(loc_rec.get('speed'), 0)
            soc = _safe_int(bms_rec.get('soc') or bms_rec.get('state_of_charge'), 0, 100)
            current = _safe_float(bms_rec.get('current') or bms_rec.get('pack_current'))

            if speed and speed > 0:
                status = 'Move'
            elif current is not None and current > 0:
                # Positive current = charging (battery pack convention: charging is positive)
                status = 'Charging'
            elif soc and soc > 0:
                status = 'Stop'
            else:
                status = 'Offline'

            ts_iso = _to_iso(loc['ts'])
            merged.append({
                'vehicle_no': registration_number,
                'registration_number': registration_number,
                'vehicle_id': loc_rec.get('device_id', f'VEH{registration_number}'),
                'driver_name': f'DRI{registration_number}',
                'latitude': loc['lat'],
                'longitude': loc['lng'],
                'gps_location': f"{loc['lat']},{loc['lng']}",
                'gps_heading': _safe_float(loc_rec.get('head') or loc_rec.get('heading'), 0),
                'gps_speed': speed,
                'speed': speed,
                'altitude': _safe_float(loc_rec.get('altitude'), 0),
                'soc': soc,
                'soh': _safe_float(bms_rec.get('soh') or bms_rec.get('state_of_health')),
                'battery_temp': _safe_float(
                    bms_rec.get('cell_temperature_highest') or
                    bms_rec.get('temperature_highest') or
                    bms_rec.get('temp_highest') or
                    bms_rec.get('battery_temp')
                ),
                'temp_lowest': _safe_float(
                    bms_rec.get('cell_temperature_lowest') or
                    bms_rec.get('temperature_lowest') or
                    bms_rec.get('temp_lowest')
                ),
                'battery_voltage': _safe_float(bms_rec.get('voltage') or bms_rec.get('pack_voltage')),
                'current': _safe_float(bms_rec.get('current') or bms_rec.get('pack_current')),
                'vehicle_status': status,
                'last_connected': ts_iso,
                'gps_time': ts_iso,
                'vendor': 'iplt',
                'device_id': loc_rec.get('device_id', f'DEV{registration_number}'),
                'spv': loc_rec.get('spv', spv),
                'odometer': _safe_float(loc_rec.get('total_vehicle_distance') or loc_rec.get('odometer')),
            })

        logger.info(f"iplt merge: {len(loc_points)} loc + {len(bms_points)} bms → {len(merged)} points for {registration_number}")
        return {'points': merged}

    @staticmethod
    def fetch_historical_data(registration_number: str, start_date: str = None, end_date: str = None, spv: str = None, vendor: str = None) -> Dict[str, Any]:
        """
        Fetch historical vehicle data from Telemetry API.
        
        PRIMARY method for historical/playback data and analytics.
        
        Args:
            registration_number: Vehicle registration number
            start_date: Start date in YYYY-MM-DD format (optional, defaults to today)
            end_date: End date in YYYY-MM-DD format (optional, defaults to today)
            spv: Supplier name (optional, defaults from settings)
            vendor: Vendor name (optional, defaults to 'intangles')
        
        Returns:
            Dict with 'points' key containing transformed vehicle data points
        """
        try:
            logger.info(f"Fetching historical data for {registration_number} from Telemetry API")
            
            if not DataSourceManager.USE_TELEMETRY_API:
                logger.warning("Telemetry API not enabled")
                return {'points': []}
            
            if not DataSourceManager.TELEMETRY_API_URL:
                logger.warning("Telemetry API URL not configured")
                return {'points': []}
            
            # Key is optional (some test servers don't require auth)
            adapter = TelemetryAPIAdapter()
            
            try:
                # Fetch and transform data
                import requests
                from datetime import datetime
                
                # Use provided dates or default to today
                if not start_date:
                    start_date = datetime.now().strftime('%Y-%m-%d')
                if not end_date:
                    end_date = datetime.now().strftime('%Y-%m-%d')
                
                # Get defaults from settings if not provided
                if not spv:
                    spv = getattr(settings, 'TELEMETRY_SPV', 'ULTRATECH')
                if not vendor:
                    vendor = 'intangles'

                # iplt uses separate /location + /bms endpoints; merge them here
                if vendor == 'iplt':
                    return DataSourceManager._fetch_iplt_historical_data(
                        registration_number=registration_number,
                        start_date=start_date,
                        end_date=end_date,
                        spv=spv,
                    )
                
                # API parameters (based on real Telemetry API at localhost:8888)
                params = {
                    'registration_number': registration_number,
                    'start_date': start_date,
                    'end_date': end_date,
                    'spv': spv,
                    'vendor': vendor,
                }
                
                headers = {}
                if DataSourceManager.TELEMETRY_API_KEY:
                    headers['x-api-key'] = DataSourceManager.TELEMETRY_API_KEY
                
                # Paginate through all pages using cursor-based pagination.
                # API returns {"data": [...], "pagination": {"has_more": bool, "next_cursor": "<ms_ts>"}}
                all_records = []
                cursor = None
                page = 0

                while True:
                    page += 1
                    page_params = dict(params)
                    if cursor:
                        page_params['cursor'] = cursor

                    logger.debug(f"Calling Telemetry API page {page}, params: {page_params}")
                    response = requests.get(
                        DataSourceManager.TELEMETRY_API_URL,
                        params=page_params,
                        headers=headers,
                        timeout=None
                    )

                    if response.status_code != 200:
                        logger.warning(f"Telemetry API returned status {response.status_code} on page {page}")
                        break

                    response_data = response.json()

                    # Handle two response formats:
                    # 1. Direct array: [record1, record2, ...]
                    # 2. Object with data key: {data: [...], pagination: {...}, ...}
                    if isinstance(response_data, list):
                        all_records.extend(response_data)
                        break  # No pagination info — assume single page
                    elif isinstance(response_data, dict) and 'data' in response_data:
                        page_records = response_data.get('data', [])
                        all_records.extend(page_records)
                        logger.info(f"Page {page}: {len(page_records)} records (total so far: {len(all_records)})")

                        pagination = response_data.get('pagination', {})
                        if pagination.get('has_more') and pagination.get('next_cursor'):
                            cursor = pagination['next_cursor']
                        else:
                            break  # No more pages
                    else:
                        logger.warning(f"Unexpected API response format: {type(response_data)}")
                        break

                if all_records:
                    batch_result = adapter.transform_batch(all_records)
                    logger.info(f"Successfully transformed {len(all_records)} records for {registration_number}")

                    if registration_number in batch_result:
                        return batch_result[registration_number]
                    else:
                        return {'points': []}
                else:
                    logger.debug(f"Telemetry API returned empty data for {registration_number}")
                    return {'points': []}
                    
            except requests.exceptions.ConnectionError:
                logger.warning(f"Cannot connect to Telemetry API at {DataSourceManager.TELEMETRY_API_URL}")
                return {'points': []}
            except requests.exceptions.Timeout:
                logger.warning("Telemetry API request timeout")
                return {'points': []}
            
        except Exception as e:
            logger.error(f"Error fetching historical data for {registration_number}: {e}")
            return {'points': []}
    
    @staticmethod
    def fetch_single_vehicle(registration_number: str) -> List[Dict[str, Any]]:
        """
        Fetch single vehicle data - uses Telemetry API for historical by default.
        
        Args:
            registration_number: Vehicle registration number
        
        Returns:
            List of data points for the vehicle
        """
        try:
            logger.info(f"Fetching vehicle data for {registration_number}")
            
            # Try Telemetry API first (historical data)
            if DataSourceManager.USE_TELEMETRY_API:
                logger.debug(f"Using Telemetry API for {registration_number}")
                points = DataSourceManager.fetch_historical_data(registration_number)
                if points:
                    return points
            
            # Fallback to TWINS if Telemetry fails or not enabled
            if DataSourceManager.USE_TWINS_API:
                logger.debug(f"Falling back to TWINS API for {registration_number}")
                adapter = TwinsAPIAdapter()
                points = adapter.fetch_single_vehicle(registration_number)
                return points if points else []
            
            logger.warning(f"No data source configured for {registration_number}")
            return []
        
        except Exception as e:
            logger.error(f"Error fetching vehicle {registration_number}: {e}")
            return []
    
    @staticmethod
    def fetch_fetch_geo_data(
        start_time: datetime,
        end_time: datetime,
        vendor: str = None,
        spv: str = None,
        batch_window_hours: int = 1
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Fetch real-time vehicle location data from TWINS fetch_geo API with automatic pagination.
        
        Uses FetchGeoAdapter with intelligent time windowing to handle server-side
        chunked encoding limitations. Splits large time windows into smaller batches
        to ensure complete data retrieval.
        
        Args:
            start_time: Start of time window (datetime object)
            end_time: End of time window (datetime object)
            vendor: Vendor ID (default from settings: 'iplt')
            spv: SPV ID (default from settings: 'ultratech')
            batch_window_hours: Size of each batch window in hours (default: 1)
                Smaller windows = safer but slower
                Larger windows = faster but may fail on large datasets
        
        Returns:
            Dict[registration_number] = List[points]
            Each point is: {
                'latitude': float,
                'longitude': float,
                'vehicle_status': str ('charging', 'yard', 'traveling'),
                'gps_time': datetime,
                'event_datetime': datetime,
                'speed': float,
                'odometer': float,
                'registration_number': str
            }
        
        Example:
            >>> from datetime import datetime, timedelta
            >>> start = datetime(2026, 2, 6, 0, 0, 0)
            >>> end = datetime(2026, 2, 6, 5, 0, 0)
            >>> data = DataSourceManager.fetch_fetch_geo_data(start, end)
            >>> vehicles = data.keys()  # Get all vehicles with data
            >>> first_vehicle = list(vehicles)[0]
            >>> points = data[first_vehicle]  # Get all GPS points for vehicle
        """
        try:
            # Get defaults from settings if not provided
            if not vendor:
                vendor = getattr(settings, 'TWINS_API_VENDOR', 'iplt')
            if not spv:
                spv = getattr(settings, 'TWINS_API_SPV', 'ultratech')
            
            # Get API token
            api_token = getattr(settings, 'TWINS_API_TOKEN')
            if not api_token:
                logger.error("TWINS_API_TOKEN not configured in settings")
                return {}
            
            logger.info(
                f"Fetching fetch_geo data: {vendor}/{spv} "
                f"from {start_time} to {end_time} "
                f"({(end_time - start_time).total_seconds() / 3600:.1f} hours) "
                f"with {batch_window_hours}-hour batches"
            )
            
            # Create adapter with pagination
            adapter = FetchGeoAdapter(api_token)
            
            # Fetch with automatic pagination
            total_vehicles, vehicles_data = adapter.fetch_vehicle_locations(
                vendor=vendor,
                spv=spv,
                start_time=start_time,
                end_time=end_time,
                batch_window_hours=batch_window_hours
            )
            
            logger.info(
                f"Successfully fetched {total_vehicles} vehicles with "
                f"{sum(len(p) for p in vehicles_data.values())} total GPS points"
            )
            
            return vehicles_data
            
        except Exception as e:
            logger.error(f"Error fetching from fetch_geo API: {type(e).__name__}: {str(e)}")
            return {}
    
    @staticmethod
    def fetch_fetch_geo_current(
        hours_back: int = 6,
        vendor: str = None,
        spv: str = None,
        batch_window_hours: int = 1
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Convenience method to fetch recent vehicle data (last N hours).
        
        Args:
            hours_back: How many hours back from now to fetch (default: 6)
            vendor: Vendor ID (default from settings)
            spv: SPV ID (default from settings)
            batch_window_hours: Size of each batch window in hours
        
        Returns:
            Dict[registration_number] = List[points]
        """
        now = datetime.now()
        start_time = now - timedelta(hours=hours_back)
        end_time = now
        
        logger.info(f"Fetching last {hours_back} hours of data: {start_time} to {end_time}")
        
        return DataSourceManager.fetch_fetch_geo_data(
            start_time=start_time,
            end_time=end_time,
            vendor=vendor,
            spv=spv,
            batch_window_hours=batch_window_hours
        )


# Convenience functions for quick integration
def get_all_vehicles() -> Dict[str, Any]:
    """
    Get all vehicles (primarily for TWINS current data).
    
    Returns:
        Dictionary of vehicles keyed by registration_number
    """
    return DataSourceManager.fetch_all_vehicles()


def get_vehicle_data(registration_number: str) -> List[Dict[str, Any]]:
    """
    Get vehicle data - uses Telemetry API for historical by default.
    
    Args:
        registration_number: Vehicle registration number
    
    Returns:
        List of transformed historical data points
    """
    return DataSourceManager.fetch_single_vehicle(registration_number)


def get_historical_data(registration_number: str, date: str = None) -> List[Dict[str, Any]]:
    """
    Get historical vehicle data from Telemetry API.
    
    Preferred method for playback and analytics data.
    
    Args:
        registration_number: Vehicle registration number
        date: Date in YYYY-MM-DD format (optional)
    
    Returns:
        List of transformed historical data points
    """
    return DataSourceManager.fetch_historical_data(registration_number, date)


def fetch_range_as_dataframe(
    start_date: str,
    end_date: str,
    vehicle_no: str = None,
    spv: str = None,
    vendor: str = None
):
    """
    Fetch historical vehicle data for a date range and return as pandas DataFrame.
    
    This is the unified interface for MIS and other batch processing to fetch telemetry
    via the centralized data source (Telemetry API through DataSourceManager).
    
    Args:
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        vehicle_no: Optional specific vehicle registration number
        spv: Supplier name (optional, defaults from settings)
        vendor: Vendor name (optional, defaults to 'intangles')
    
    Returns:
        pandas DataFrame with columns: vehicle_no, vehicle_id, soc, battery_temp, 
                                       gps_speed, gps_location, vehicle_status, 
                                       gps_time, last_connected, etc.
                                       Sorted by vehicle_no, then gps_time ascending.
    """
    import pandas as pd
    from datetime import datetime
    
    logger = logging.getLogger(__name__)
    
    try:
        # Determine whether the caller pinned a specific vendor or wants auto-routing.
        # Auto-routing = intangles first, iplt as fallback for missing vehicles.
        explicit_vendor = vendor  # None means "auto"

        def _fetch_with_fallback(reg: str) -> list:
            """Try intangles; fall back to iplt if no data returned."""
            if explicit_vendor:
                # Caller pinned a vendor — use it directly, no fallback.
                r = DataSourceManager.fetch_historical_data(
                    registration_number=reg,
                    start_date=start_date, end_date=end_date,
                    spv=spv, vendor=explicit_vendor,
                )
                return r.get('points', []) if isinstance(r, dict) else []

            # Auto-routing: intangles primary → iplt fallback
            r = DataSourceManager.fetch_historical_data(
                registration_number=reg,
                start_date=start_date, end_date=end_date,
                spv=spv, vendor='intangles',
            )
            pts = r.get('points', []) if isinstance(r, dict) else []
            if pts:
                logger.debug(f"{reg}: {len(pts)} points from intangles")
                return pts

            logger.info(f"{reg}: no intangles data, trying iplt fallback")
            r = DataSourceManager.fetch_historical_data(
                registration_number=reg,
                start_date=start_date, end_date=end_date,
                spv=spv, vendor='iplt',
            )
            pts = r.get('points', []) if isinstance(r, dict) else []
            if pts:
                logger.info(f"{reg}: {len(pts)} points from iplt fallback")
            return pts

        # If vehicle_no specified, fetch for that vehicle
        if vehicle_no:
            logger.info(f"Fetching range {start_date} to {end_date} for vehicle {vehicle_no}")
            points = _fetch_with_fallback(vehicle_no)

            if not points:
                logger.info(f"No points fetched for {vehicle_no}")
                return pd.DataFrame()

            # Convert list of dicts to DataFrame
            df = pd.DataFrame(points)
            logger.info(f"Fetched {len(df)} points for {vehicle_no}")

        else:
            # Fetch all vehicles for date range using known fleet list
            from voltrack.vendor_config import KNOWN_FLEET
            logger.info(f"Fetching range {start_date} to {end_date} for all {len(KNOWN_FLEET)} fleet vehicles")
            all_dfs = []
            for reg in KNOWN_FLEET:
                v_points = _fetch_with_fallback(reg)
                if v_points:
                    all_dfs.append(pd.DataFrame(v_points))
            if not all_dfs:
                logger.warning("No data found for any fleet vehicle")
                return pd.DataFrame()
            df = pd.concat(all_dfs, ignore_index=True)
        
        if df.empty:
            return df
        
        # Ensure proper column types and names for MIS compatibility
        # MIS expects: vehicle_no, vehicle_id, soc, battery_temp, gps_speed, gps_location, 
        #              vehicle_status, last_connected, lat, lon AND odometer fields for geofencing
        
        # Map/rename columns if needed (usually already correct from adapter)
        if 'registration_number' in df.columns:
            df['vehicle_no'] = df['registration_number']
        
        if 'gps_speed' not in df.columns and 'speed' in df.columns:
            df['gps_speed'] = df['speed']
        
        # Split gps_location into lat/lon (required by geofence_processor)
        if 'gps_location' in df.columns:
            df['gps_location'] = df['gps_location'].astype(str).str.strip()
            gps_split = df['gps_location'].str.split(',', expand=True)
            if len(gps_split.columns) >= 2:
                df['lat'] = pd.to_numeric(gps_split[0], errors='coerce')
                df['lon'] = pd.to_numeric(gps_split[1], errors='coerce')
            else:
                df['lat'] = None
                df['lon'] = None
        else:
            df['lat'] = None
            df['lon'] = None
        
        # Add odometer fields if missing (required by geofence processor for interval building)
        # total_vehicle_distance from API is mapped to 'odometer' by the adapter.
        # build_intervals() renames 'end_odometer' → 'odometer', so we must not keep
        # a separate 'odometer' column alongside 'end_odometer' — that would produce
        # duplicate columns after the rename.
        if 'odometer' in df.columns:
            if 'end_odometer' not in df.columns:
                df['end_odometer'] = df['odometer']
            else:
                # fill end_odometer where missing from odometer column
                df['end_odometer'] = df['end_odometer'].fillna(df['odometer'])
            # Drop the raw 'odometer' column so build_intervals rename is unambiguous
            df = df.drop(columns=['odometer'])
        else:
            if 'end_odometer' not in df.columns:
                df['end_odometer'] = None
        if 'start_odometer' not in df.columns:
            df['start_odometer'] = None
        
        # Ensure timestamps are datetime objects (not strings) for MIS geofence_processor
        # MIS needs datetime objects for arithmetic operations like (end_ts - last_connected)
        if 'gps_time' in df.columns:
            df['gps_time'] = pd.to_datetime(df['gps_time'], utc=True)
        
        if 'last_connected' in df.columns:
            df['last_connected'] = pd.to_datetime(df['last_connected'], utc=True)
        else:
            # For backward compatibility, also set last_connected = gps_time
            if 'gps_time' in df.columns:
                df['last_connected'] = df['gps_time']
        
        # Sort by vehicle_no and gps_time ascending
        if 'gps_time' in df.columns:
            df = df.sort_values(['vehicle_no', 'gps_time']).reset_index(drop=True)

        # Normalize vehicle_status values to what MIS expects.
        # Both the intangles telemetry adapter and iplt adapter emit 'Move',
        # but MIS geofence_processor and trip_calculator check for 'Moving'.
        if 'vehicle_status' in df.columns:
            df['vehicle_status'] = df['vehicle_status'].replace({'Move': 'Moving'})

        logger.info(f"Returning DataFrame with {len(df)} rows, {len(df.columns)} columns")
        return df
        
    except Exception as e:
        logger.error(f"Error fetching range as DataFrame: {e}")
        return pd.DataFrame()
    
    @staticmethod
    def fetch_fetch_geo_data(
        start_time: datetime,
        end_time: datetime,
        vendor: str = None,
        spv: str = None,
        batch_window_hours: int = 1
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Fetch real-time vehicle location data from TWINS fetch_geo API with automatic pagination.
        
        Uses FetchGeoAdapter with intelligent time windowing to handle server-side
        chunked encoding limitations. Splits large time windows into smaller batches
        to ensure complete data retrieval.
        
        Args:
            start_time: Start of time window (datetime object)
            end_time: End of time window (datetime object)
            vendor: Vendor ID (default from settings: 'iplt')
            spv: SPV ID (default from settings: 'ultratech')
            batch_window_hours: Size of each batch window in hours (default: 1)
                Smaller windows = safer but slower
                Larger windows = faster but may fail on large datasets
        
        Returns:
            Dict[registration_number] = List[points]
            Each point is: {
                'latitude': float,
                'longitude': float,
                'vehicle_status': str ('charging', 'yard', 'traveling'),
                'gps_time': datetime,
                'event_datetime': datetime,
                'speed': float,
                'odometer': float,
                'registration_number': str
            }
        
        Example:
            >>> from datetime import datetime, timedelta
            >>> start = datetime(2026, 2, 6, 0, 0, 0)
            >>> end = datetime(2026, 2, 6, 5, 0, 0)
            >>> data = DataSourceManager.fetch_fetch_geo_data(start, end)
            >>> vehicles = data.keys()  # Get all vehicles with data
            >>> first_vehicle = list(vehicles)[0]
            >>> points = data[first_vehicle]  # Get all GPS points for vehicle
        """
        try:
            # Get defaults from settings if not provided
            if not vendor:
                vendor = getattr(settings, 'TWINS_API_VENDOR', 'iplt')
            if not spv:
                spv = getattr(settings, 'TWINS_API_SPV', 'ultratech')
            
            # Get API token
            api_token = getattr(settings, 'TWINS_API_TOKEN')
            if not api_token:
                logger.error("TWINS_API_TOKEN not configured in settings")
                return {}
            
            logger.info(
                f"Fetching fetch_geo data: {vendor}/{spv} "
                f"from {start_time} to {end_time} "
                f"({(end_time - start_time).total_seconds() / 3600:.1f} hours) "
                f"with {batch_window_hours}-hour batches"
            )
            
            # Create adapter with pagination
            adapter = FetchGeoAdapter(api_token)
            
            # Fetch with automatic pagination
            total_vehicles, vehicles_data = adapter.fetch_vehicle_locations(
                vendor=vendor,
                spv=spv,
                start_time=start_time,
                end_time=end_time,
                batch_window_hours=batch_window_hours
            )
            
            logger.info(
                f"Successfully fetched {total_vehicles} vehicles with "
                f"{sum(len(p) for p in vehicles_data.values())} total GPS points"
            )
            
            return vehicles_data
            
        except Exception as e:
            logger.error(f"Error fetching from fetch_geo API: {type(e).__name__}: {str(e)}")
            return {}
    
    @staticmethod
    def fetch_fetch_geo_current(
        hours_back: int = 6,
        vendor: str = None,
        spv: str = None,
        batch_window_hours: int = 1
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Convenience method to fetch recent vehicle data (last N hours).
        
        Args:
            hours_back: How many hours back from now to fetch (default: 6)
            vendor: Vendor ID (default from settings)
            spv: SPV ID (default from settings)
            batch_window_hours: Size of each batch window in hours
        
        Returns:
            Dict[registration_number] = List[points]
        """
        now = datetime.now()
        start_time = now - timedelta(hours=hours_back)
        end_time = now
        
        logger.info(f"Fetching last {hours_back} hours of data: {start_time} to {end_time}")
        
        return DataSourceManager.fetch_fetch_geo_data(
            start_time=start_time,
            end_time=end_time,
            vendor=vendor,
            spv=spv,
            batch_window_hours=batch_window_hours
        )
