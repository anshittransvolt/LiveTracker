"""
Geofence Configuration
======================
Defines all geofence locations for trip calculation.
"""

from typing import List, Tuple
from shapely.geometry import Polygon

# Circle geofences: (name, lat, lon, radius_meters)
CIRCLE_GEOFENCES: List[Tuple[str, float, float, float]] = [
    ("Dhule Gate", 21.156063, 74.853409, 100),        # Increased from 30m to 100m
    ("Dhule unloading", 21.15111842, 74.84979354, 150), # Increased from 100m to 150m
    ("Maharashtra Border", 21.427817, 74.980463, 500),
    ("Manawar Out Area", 22.262448, 75.128085, 100),    # Increased from 70m to 100m
    ("Manawar Tarpulien", 22.271049, 75.133974, 100),   # Increased from 70m to 100m
    ("Manawar Charging Point", 22.265524, 75.127794, 100), # Increased from 70m to 100m
    ("Manawar Weighing Area", 22.269420, 75.133556, 100),  # Increased from 70m to 100m
    ("Julwaniya General Area", 21.870419, 75.214469, 150), # Added general Julwaniya coverage
]

# Polygon geofences: (name, [(lat, lon), ...])
POLYGON_GEOFENCES: List[Tuple[str, List[List[float]]]] = [
    ("Charging Fence Dhule", [
        [21.150138, 74.850055],
        [21.148732, 74.849582],
        [21.149454, 74.847823],
        [21.150652, 74.848260],
    ]),
    ("Jhulwania Charging Point", [
        [21.870919, 75.214750],
        [21.870419, 75.213876],
        [21.869145, 75.214469],
        [21.869929, 75.215546],
    ]),
    ("Manawar Loading Area", [
        [22.271683, 75.138225],
        [22.268312, 75.128871],
        [22.262503, 75.128803],
        [22.262364, 75.139468],
    ]),
]

# Cluster definitions
MANAWAR_FENCES = {
    "Manawar Out Area",
    "Manawar Tarpulien",
    "Manawar Charging Point",
    "Manawar Loading Area",
    "Manawar Weighing Area",
}

JULWANIYA_FENCES = {
    "Jhulwania Charging Point",
    "Julwaniya General Area",  # Added the new circle geofence
}

DHULE_FENCES = {
    "Dhule Gate",
    "Dhule unloading",
    "Charging Fence Dhule",
}

# Build polygon geometry objects (lon/lat order for Shapely)
POLYGON_GEOMS = []
for name, coords in POLYGON_GEOFENCES:
    poly = Polygon([(lon, lat) for lat, lon in coords])
    POLYGON_GEOMS.append((name, poly))

# Battery capacity (kWh)
BATTERY_CAPACITY_KWH = 282.0

# Maximum gap between telemetry points (minutes)
MAX_GAP_MINUTES = 120
