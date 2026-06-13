import numpy as np
import pandas as pd
from math import radians, cos, sin, asin, sqrt


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate the great circle distance in meters between two points
    on the earth (specified in decimal degrees).

    Args:
        lat1: Latitude of first point in decimal degrees
        lon1: Longitude of first point in decimal degrees
        lat2: Latitude of second point in decimal degrees
        lon2: Longitude of second point in decimal degrees

    Returns:
        Distance in meters between the two points
    """
    # Convert decimal degrees to radians
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])

    # Haversine formula
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    c = 2 * asin(sqrt(a))

    # Radius of earth in meters
    r = 6371000
    return c * r


def compute_segment_distances(
    sub: pd.DataFrame, lat_col="lat", lon_col="lng"
) -> pd.Series:
    """
    Compute Haversine distances (in kilometers) between consecutive GPS points
    within a sub-DataFrame (typically for a single vehicle and day).

    Args:
        sub: A pandas DataFrame slice containing telemetry data for a specific
             vehicle and day, sorted by time. It must contain 'lat' and 'lng' columns.
        lat_col: The name of the latitude column. Defaults to 'lat'.
        lon_col: The name of the longitude column. Defaults to 'lng'.

    Returns:
        A pandas Series of the same length as the input sub-DataFrame, where
        each element represents the Haversine distance in kilometers from the
        previous point. The first element is always 0.0. NaN values in lat/lng
        will result in 0.0 distance for that segment.
    """
    n = len(sub)
    seg = np.zeros(n, dtype=float)
    for i in range(1, n):
        lat1, lon1 = sub.iloc[i - 1][lat_col], sub.iloc[i - 1][lon_col]
        lat2, lon2 = sub.iloc[i][lat_col], sub.iloc[i][lon_col]
        # Check if both current and previous points have valid coordinates before calculating distance.
        if pd.notna(lat1) and pd.notna(lon1) and pd.notna(lat2) and pd.notna(lon2):
            seg[i] = (
                haversine_m(lat1, lon1, lat2, lon2) / 1000.0
            )  # Convert meters to kilometers
    return pd.Series(seg, index=sub.index)


def parse_gps_location(gps_location: str) -> tuple:
    """
    Parse GPS location string in format "lat,lng" to tuple of floats.

    Args:
        gps_location: String in format "21.87020,75.21392"

    Returns:
        Tuple of (latitude, longitude) as floats
    """
    try:
        lat_str, lng_str = gps_location.split(",")
        return float(lat_str.strip()), float(lng_str.strip())
    except (ValueError, AttributeError):
        return None, None


def calculate_trip_analytics(vehicle_data: list) -> dict:
    """
    Calculate trip analytics from vehicle telemetry data.

    Args:
        vehicle_data: List of vehicle data dictionaries (in descending time order - newest first)
                     with structure:
                     {
                       "vehicle_id": 36077,
                       "vehicle_no": "MH18BZ2873",
                       "gps_location": "21.87020,75.21392",
                       "soc": 55,
                       "vehicle_status": "Stop",
                       "last_connected": "2025-11-05T18:25:00+05:30",
                       "driver_name": "DRI36077"
                     }

    Returns:
        Dictionary with trip analytics including total distance, average SOC, etc.
    """
    if not vehicle_data:
        return {
            "total_distance": 0.0,
            "average_soc": 0.0,
            "status_summary": {},
            "total_points": 0,
        }

    # Convert to DataFrame for easier processing
    df_data = []
    for point in vehicle_data:
        lat, lng = parse_gps_location(point.get("gps_location", ""))
        if lat is not None and lng is not None:
            df_data.append(
                {
                    "lat": lat,
                    "lng": lng,
                    "soc": point.get("soc", 0),
                    "vehicle_status": point.get("vehicle_status", "Unknown"),
                    "last_connected": point.get("last_connected", ""),
                }
            )

    if not df_data:
        return {
            "total_distance": 0.0,
            "average_soc": 0.0,
            "status_summary": {},
            "total_points": 0,
        }

    df = pd.DataFrame(df_data)

    # IMPORTANT: Reverse the data so it's in chronological order (oldest first)
    # This is needed because the API returns data in descending order (newest first)
    # but distance calculations require consecutive points in time order
    df = df.iloc[::-1].reset_index(drop=True)

    # Calculate distances between consecutive points in time order
    distances = compute_segment_distances(df, lat_col="lat", lon_col="lng")
    total_distance = distances.sum()

    # Calculate average SOC
    average_soc = df["soc"].mean()

    # Status summary
    status_counts = df["vehicle_status"].value_counts().to_dict()

    return {
        "total_distance": round(total_distance, 2),
        "average_soc": round(average_soc, 1),
        "status_summary": status_counts,
        "total_points": len(df_data),
    }
