"""
FetchGeoAdapter - Fetches real-time vehicle location data from TWINS API
with automatic pagination to handle server-side chunked encoding issues.
"""

import logging
import requests
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

logger = logging.getLogger(__name__)


class FetchGeoAdapter:
    """
    Adapter for the fetch_geo TWINS API endpoint.
    
    Handles:
    - Real-time GPS location data for vehicles
    - Automatic pagination for large time windows
    - Vehicle status information (charging, yard, traveling)
    - Direct integration with timebox journey detection
    """

    BASE_URL = 'https://twins.transvolt.org/fetch_geo'
    BATCH_WINDOW_HOURS = 1  # Split into 1-hour windows to avoid server chunking issues
    TIMEOUT_SECONDS = 120

    def __init__(self, api_token: str):
        """
        Initialize the adapter with API token.
        
        Args:
            api_token: Bearer token for TWINS API authentication
        """
        self.api_token = api_token
        self.headers = {
            'Authorization': f'Bearer {api_token}',
            'Content-Type': 'application/json'
        }

    def fetch_vehicle_locations(
        self,
        vendor: str,
        spv: str,
        start_time: datetime,
        end_time: datetime,
        batch_window_hours: Optional[int] = None
    ) -> Tuple[int, Dict[str, List[Dict]]]:
        """
        Fetch vehicle GPS locations for a given time window.
        
        Automatically paginates large time windows into smaller batches
        to work around server-side chunked encoding issues.
        
        Args:
            vendor: Vendor ID (e.g., 'iplt')
            spv: SPV ID (e.g., 'ultratech')
            start_time: Start of time window (datetime)
            end_time: End of time window (datetime)
            batch_window_hours: Size of each batch in hours (default: 1)
        
        Returns:
            Tuple of (total_vehicles, vehicles_dict)
            vehicles_dict: {registration_number: [points]}
            where each point is:
            {
                'latitude': float,
                'longitude': float,
                'vehicle_status': str,  # 'charging', 'yard', 'traveling'
                'gps_time': datetime,
                'event_datetime': datetime,
                'speed': float,
                'odometer': float,
                'registration_number': str
            }
        """
        if batch_window_hours is None:
            batch_window_hours = self.BATCH_WINDOW_HOURS

        all_vehicles = defaultdict(list)
        total_vehicles = 0

        # Paginate through time windows
        current_start = start_time
        batch_num = 0

        while current_start < end_time:
            batch_num += 1
            batch_end = min(current_start + timedelta(hours=batch_window_hours), end_time)

            logger.info(
                f"Fetching batch {batch_num}: {current_start} to {batch_end} "
                f"({(batch_end - current_start).total_seconds() / 3600:.1f} hours)"
            )

            try:
                batch_vehicles = self._fetch_batch(
                    vendor=vendor,
                    spv=spv,
                    start_time=current_start,
                    end_time=batch_end
                )

                # Merge vehicle data from this batch
                if batch_vehicles:
                    for reg_no, points in batch_vehicles.items():
                        all_vehicles[reg_no].extend(points)

                logger.info(
                    f"Batch {batch_num}: {len(batch_vehicles)} vehicles, "
                    f"{sum(len(p) for p in batch_vehicles.values())} points"
                )

                total_vehicles = len(all_vehicles)

            except requests.exceptions.ChunkedEncodingError as e:
                logger.error(f"ChunkedEncodingError in batch {batch_num}: {str(e)[:100]}")
                # Continue with next batch - partial data is better than nothing
            except requests.exceptions.RequestException as e:
                logger.error(f"Request error in batch {batch_num}: {type(e).__name__}: {str(e)[:100]}")
                # Continue with next batch
            except json.JSONDecodeError as e:
                logger.error(f"JSON decode error in batch {batch_num}: {str(e)[:100]}")
                # Continue with next batch
            except Exception as e:
                logger.error(f"Unexpected error in batch {batch_num}: {type(e).__name__}: {str(e)[:100]}")
                # Continue with next batch

            current_start = batch_end

        # Sort points by timestamp for each vehicle
        for reg_no in all_vehicles:
            all_vehicles[reg_no].sort(key=lambda p: p['gps_time'])

        logger.info(
            f"Fetch complete: {total_vehicles} vehicles, "
            f"{sum(len(p) for p in all_vehicles.values())} total points"
        )

        return total_vehicles, dict(all_vehicles)

    def _fetch_batch(
        self,
        vendor: str,
        spv: str,
        start_time: datetime,
        end_time: datetime
    ) -> Dict[str, List[Dict]]:
        """
        Fetch a single batch of vehicle data.
        
        Args:
            vendor: Vendor ID
            spv: SPV ID
            start_time: Batch start time
            end_time: Batch end time
        
        Returns:
            Dictionary of vehicles with their GPS points
        """
        params = {
            'vendor': vendor,
            'spv': spv,
            'start_time': start_time.strftime('%Y-%m-%d %H:%M:%S'),
            'end_time': end_time.strftime('%Y-%m-%d %H:%M:%S')
        }

        response = requests.get(
            self.BASE_URL,
            headers=self.headers,
            params=params,
            timeout=self.TIMEOUT_SECONDS,
            stream=False
        )

        response.raise_for_status()
        data = response.json()

        # Extract vehicles from response
        vehicles = data.get('vehicles', {})
        processed_vehicles = {}

        for reg_no, points in vehicles.items():
            processed_points = []

            for point in points:
                try:
                    processed_point = {
                        'latitude': float(point.get('latitude', 0)),
                        'longitude': float(point.get('longitude', 0)),
                        'vehicle_status': self._normalize_vehicle_status(
                            point.get('vehicle_status', 'traveling')
                        ),
                        'gps_time': self._parse_datetime(point.get('gps_time')),
                        'event_datetime': self._parse_datetime(point.get('event_datetime')),
                        'speed': float(point.get('speed', 0)),
                        'odometer': float(point.get('odometer', 0)),
                        'registration_number': reg_no
                    }
                    processed_points.append(processed_point)
                except (ValueError, TypeError) as e:
                    logger.warning(f"Failed to process point for {reg_no}: {str(e)}")
                    continue

            if processed_points:
                processed_vehicles[reg_no] = processed_points

        return processed_vehicles

    @staticmethod
    def _normalize_vehicle_status(status: str) -> str:
        """
        Normalize vehicle status to standard values.
        
        Args:
            status: Raw status string from API
        
        Returns:
            Normalized status: 'charging', 'yard', or 'traveling'
        """
        status_lower = str(status).lower().strip()

        if status_lower == 'charging':
            return 'charging'
        elif status_lower in ['yard', 'manawar_yard', 'depot']:
            return 'yard'
        else:
            return 'traveling'

    @staticmethod
    def _parse_datetime(datetime_str: Optional[str]) -> datetime:
        """
        Parse datetime string from API response.
        
        Args:
            datetime_str: Datetime string (supports multiple formats and Unix timestamps)
        
        Returns:
            Parsed datetime object
        """
        if not datetime_str:
            return datetime.now()

        datetime_str = str(datetime_str).strip()

        # Try Unix timestamp first (10 or 13 digits)
        if datetime_str.isdigit():
            try:
                timestamp = int(datetime_str)
                # Unix timestamp can be in seconds or milliseconds
                if timestamp > 10000000000:  # Likely milliseconds
                    return datetime.fromtimestamp(timestamp / 1000)
                else:  # Likely seconds
                    return datetime.fromtimestamp(timestamp)
            except (ValueError, OSError):
                pass  # Not a valid Unix timestamp

        # Try multiple datetime string formats
        formats = [
            '%Y-%m-%d %H:%M:%S',
            '%Y-%m-%dT%H:%M:%S',
            '%Y-%m-%dT%H:%M:%S.%f',
            '%Y-%m-%dT%H:%M:%SZ',
        ]

        for fmt in formats:
            try:
                return datetime.strptime(datetime_str.split('.')[0], fmt)
            except ValueError:
                continue

        # If all else fails, return current time
        return datetime.now()


# Example usage
if __name__ == '__main__':
    import os
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'voltrack.settings')
    
    import django
    django.setup()
    
    from django.conf import settings

    adapter = FetchGeoAdapter(settings.TWINS_API_TOKEN)

    # Fetch data
    start = datetime(2026, 2, 6, 0, 0, 0)
    end = datetime(2026, 2, 6, 5, 0, 0)

    total_vehicles, vehicles = adapter.fetch_vehicle_locations(
        vendor='iplt',
        spv='ultratech',
        start_time=start,
        end_time=end
    )

    print(f"\n✅ Success!")
    print(f"   Total vehicles: {total_vehicles}")
    print(f"   Total points: {sum(len(p) for p in vehicles.values())}")
    print(f"\n   Sample vehicles:")
    for reg_no in list(vehicles.keys())[:5]:
        points = vehicles[reg_no]
        first_point = points[0]
        print(f"      {reg_no}: {len(points)} points")
        print(f"         Status: {first_point['vehicle_status']}")
        print(f"         First location: {first_point['latitude']}, {first_point['longitude']}")
