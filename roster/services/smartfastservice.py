import requests
import logging
import os
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


def fetch_vehicles_for_date(target_date):
    """
    Fetch vehicle data for a specific date using the SmartFast API
    
    Args:
        target_date: A date object representing the target date
    
    Returns:
        List of vehicle records for the specified date
    """
    load_dotenv()
    API_DOMAIN = os.getenv("SMARTFASTAPI_DOMAIN")
    API_KEY = os.getenv("SMARTFASTAPI_ACCESS_KEY")
    
    url = f"{API_DOMAIN}/vehicleiplt/range"
    params = {
        "start_date": target_date.strftime("%Y-%m-%d"),
        "end_date": target_date.strftime("%Y-%m-%d")
    }
    
    headers = {}
    if API_KEY:
        headers["x-api-key"] = API_KEY
    
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        logger.info(f"Fetched {len(data) if isinstance(data, list) else 0} records for {target_date}")
        return data if isinstance(data, list) else []
    except requests.exceptions.RequestException as e:
        logger.error(f"API request error for {target_date}: {e}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error fetching data for {target_date}: {e}")
        return []
