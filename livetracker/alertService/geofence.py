"""Geofence helper functions.

Contains geospatial helpers used to test whether a given lat/lon lies inside
configured circular or polygon geofences.
"""

from math import radians, sin, cos, sqrt, asin
from typing import Optional

from .alert_constants import CIRCLE_GEOFENCES, POLYGON_GEOFENCES


def haversine_m(lat1, lon1, lat2, lon2):
    """Return distance in meters between two lat/lon points."""
    R = 6371000.0
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    c = 2 * asin(min(1, sqrt(a)))
    return R * c


def point_in_circle(lat, lon, center_lat, center_lon, radius_m):
    return haversine_m(lat, lon, center_lat, center_lon) <= radius_m + 1e-6


def point_in_polygon(lat, lon, polygon):
    # ray casting algorithm
    x = lon
    y = lat
    inside = False
    n = len(polygon)
    for i in range(n):
        lat_i, lon_i = polygon[i]
        lat_j, lon_j = polygon[(i + 1) % n]
        xi, xj = lon_i, lon_j
        yi, yj = lat_i, lat_j
        intersect = ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi
        )
        if intersect:
            inside = not inside
    return inside


def point_in_geofences(lat: float, lon: float) -> Optional[str]:
    """Return the first geofence name that contains the point, or None."""
    # Priority: circles first (explicit names), then polygons
    for name, c_lat, c_lon, radius in CIRCLE_GEOFENCES:
        if point_in_circle(lat, lon, c_lat, c_lon, radius):
            return name
    for name, polygon in POLYGON_GEOFENCES:
        if point_in_polygon(lat, lon, polygon):
            return name
    return None
