"""Reverse geocoding helpers (wrapper around geopy.Nominatim).

This module centralises reverse geocoding so it can be cached or rate-limited
in one place.
"""

import time
import logging
from typing import Optional
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError

logger = logging.getLogger(__name__)
geolocator = Nominatim(user_agent="fleet_dashboard_app", timeout=10)


def reverse_geocode(lat: float, lng: float, retries: int = 1) -> Optional[str]:
    """Convert latitude/longitude to human-readable address.

    Returns None on failure. Retries transient geocoder errors once.
    Catches all network/connection errors gracefully.
    """
    for attempt in range(retries):
        try:
            location = geolocator.reverse((lat, lng), exactly_one=True)
            if location:
                return location.address
            return None

        except (GeocoderTimedOut, GeocoderServiceError) as e:
            if attempt < retries - 1:
                time.sleep(1)
                continue
            logger.warning(f"Geocoding service error for ({lat}, {lng}): {e}")
            return None
        except Exception as e:
            # Catch all network errors (ConnectionError, URLError, etc.) silently
            # This includes "Network is unreachable" errors
            logger.debug(f"Geocoding failed for ({lat}, {lng}): {type(e).__name__}")
            return None
    return None
