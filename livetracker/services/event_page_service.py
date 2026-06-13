"""
Service for fetching events from the webhook event page API.
"""

import requests
from django.conf import settings
import logging

logger = logging.getLogger(__name__)


def fetch_events(limit=50, cursor='MjAyNS0xMi0wNlQwMDowMDowMA=='):
    """
    Fetch events from the webhook event page API.
    
    Args:
        limit (int): Number of events to fetch (default: 50)
        cursor (str): Pagination cursor for fetching next page (use next_cursor from previous response)
        
    Returns:
        dict: Response with structure:
            {
                "count": int,
                "next_cursor": str,  # Use this for next page
                "results": [
                    {
                        "id": str,
                        "vendor": str,
                        "event_id": str,
                        "event_name": str,
                        "event_desc": str,
                        "vehicle_id": str,
                        "vehicle_no": str,
                        "priority": str,
                        "created_at": str
                    },
                    ...
                ]
            }
        Returns None if error occurs.
    """
    try:
        # Build URL with query parameters
        url = settings.WEBHOOK_EVENT_PAGE_URL
        params = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        
        # Prepare headers with API key
        headers = {
            "x-api-key": settings.WEBHOOK_API_KEY
        }
        
        logger.info(f"Fetching events from {url} (limit={limit}, cursor={'provided' if cursor else 'none'})")
        
        # Make request
        response = requests.get(
            url,
            params=params,
            headers=headers,
            timeout=10
        )
        response.raise_for_status()
        
        data = response.json()
        logger.info(f"Successfully fetched {data.get('count', 0)} events, next_cursor: {data.get('next_cursor', 'none')}")
        
        return data
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching events: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error fetching events: {e}")
        return None
