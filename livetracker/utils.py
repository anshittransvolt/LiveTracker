from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
import time

geolocator = Nominatim(user_agent="fleet_dashboard_app", timeout=10)


def reverse_geocode(lat, lng, retries=3):
    """Convert latitude/longitude → human-readable address safely."""
    for attempt in range(retries):
        try:
            location = geolocator.reverse((lat, lng), exactly_one=True)
            if location:
                return location.address
            return None

        except (GeocoderTimedOut, GeocoderServiceError):
            if attempt < retries - 1:
                time.sleep(1)  # wait before retry
                continue
            return None

        except Exception:
            return None
    return None
  