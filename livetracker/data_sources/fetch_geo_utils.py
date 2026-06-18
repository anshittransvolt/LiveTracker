"""
Utility: fetch GPS track data from the fetch_geo endpoint and normalize it
into a timebox-compatible point format.

Used by roster (active vehicles report) and vehicle history processing.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def fetch_timebox_data_from_fetch_geo(
    start_time: datetime = None,
    end_time: datetime = None,
    hours_back: int = 6,
    batch_window_hours: int = 1,
) -> dict:
    """
    Fetch vehicle GPS data via fetch_geo and normalize to timebox-compatible format.

    Returns:
        Dict[registration_number] -> list of point dicts with keys:
        latitude, longitude, vehicle_status, gps_time, event_datetime,
        speed, odometer, registration_number, last_connected, gps_location
    """
    from .data_source_manager import DataSourceManager

    try:
        if start_time is None or end_time is None:
            end_time = datetime.now()
            start_time = end_time - timedelta(hours=hours_back)

        logger.info(
            f"Fetching fetch_geo data: {start_time} → {end_time} "
            f"({(end_time - start_time).total_seconds() / 3600:.1f}h, {batch_window_hours}h batches)"
        )

        vehicles_data = DataSourceManager.fetch_fetch_geo_data(
            start_time=start_time,
            end_time=end_time,
            batch_window_hours=batch_window_hours,
        )

        result = {}
        for reg_no, points in vehicles_data.items():
            result[reg_no] = [
                {
                    "latitude": p.get("latitude"),
                    "longitude": p.get("longitude"),
                    "vehicle_status": p.get("vehicle_status", "traveling"),
                    "gps_time": p.get("gps_time"),
                    "event_datetime": p.get("event_datetime"),
                    "speed": p.get("speed", 0),
                    "odometer": p.get("odometer", 0),
                    "registration_number": reg_no,
                    "last_connected": p.get("gps_time"),
                    "gps_location": f"{p.get('latitude', 0)},{p.get('longitude', 0)}",
                }
                for p in points
            ]

        logger.info(
            f"fetch_geo: {len(result)} vehicles, "
            f"{sum(len(v) for v in result.values())} total points"
        )
        return result

    except Exception as exc:
        logger.error(f"fetch_timebox_data_from_fetch_geo failed: {type(exc).__name__}: {exc}")
        return {}
