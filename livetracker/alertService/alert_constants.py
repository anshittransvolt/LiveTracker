"""Constants and geofence definitions for the alert service.

This file contains configuration thresholds, SLA values and the geofence
definitions (circle and polygon lists) used by the alerting logic.
"""

from typing import List, Tuple

# -----------------
# Configuration
# -----------------
DEBOUNCE_SECONDS = 60
API_INTERVAL_SECONDS = 60
FEED_GAP_SECONDS = 3 * API_INTERVAL_SECONDS  # 180s
UNPLANNED_STOP_SECONDS = 10 * 60  # 10 mins
CHARGING_OVER_SECONDS = 90 * 60  # 90 mins
CHARGING_FULL_STUCK_SECONDS = 5 * 60  # 5 mins
MAHA_BORDER_DWELL_SECONDS = 45 * 60
LOADING_DWELL_SECONDS = 20 * 60
TARE_DWELL_SECONDS = 5 * 60
GROSS_DWELL_SECONDS = 10 * 60
TARPULIN_DWELL_SECONDS = 10 * 60
UNLOADING_DWELL_SECONDS = 15 * 60
manawar_yard = 0
jhulwania_yard = 0
dhule_yard = 0

# Transit SLA config (seconds)
MANAWAR_TO_JHULWANIA_TARGET = 170 * 60  # 170min
MANAWAR_TO_JHULWANIA_TOL = 15 * 60  # 15min
MANAWAR_TO_JHULWANIA_MIN = MANAWAR_TO_JHULWANIA_TARGET - MANAWAR_TO_JHULWANIA_TOL
MANAWAR_TO_JHULWANIA_MAX = MANAWAR_TO_JHULWANIA_TARGET + MANAWAR_TO_JHULWANIA_TOL

JHULWANIA_TO_DHULE_TARGET = 195 * 60
JHULWANIA_TO_DHULE_TOL = 15 * 60
JHULWANIA_TO_DHULE_MIN = JHULWANIA_TO_DHULE_TARGET - JHULWANIA_TO_DHULE_TOL
JHULWANIA_TO_DHULE_MAX = JHULWANIA_TO_DHULE_TARGET + JHULWANIA_TO_DHULE_TOL

# -----------------
# Geofence data (circle and polygon lists)
# -----------------
# Circles: (name, lat, lon, radius_m)
CIRCLE_GEOFENCES: List[Tuple[str, float, float, float]] = [
    ("Dhule Gate", 21.156063, 74.853409, 30),
    ("Dhule Circle Geofence", 21.15111842, 74.84979354, 100),
    ("Maha Border", 21.427817, 74.980463, 500),
    ("D1 Jhulwania (20 m)", 21.871537, 75.215380, 50),
    ("D2 Jhulwania (20 m)", 21.870432, 75.213483, 50),
    ("Manawar Out Area", 22.262448, 75.128085, 50),
    ("Tarpulien", 22.271049, 75.133974, 30),
    ("Charging Point", 22.265636, 75.127046, 100),
    ("Loading Area", 22.267011, 75.135545, 100),
    ("Weighing Area", 22.269420, 75.133556, 50),
    ("Dharampuri", 22.152785, 75.341519, 150),
    ("Dabhashi", 21.265904, 74.847418, 150),
]

# Polygons: (name, [ [lat,lon], ... ])
POLYGON_GEOFENCES = [
    (
        "Charging Fence Dhule (Outlined)",
        [
            [21.150138, 74.850055],
            [21.148732, 74.849582],
            [21.149454, 74.847823],
            [21.150652, 74.848260],
        ],
    ),
    (
        "Jhulwania Charging Point (Outlined)",
        [
            [21.870919, 75.214750],
            [21.870419, 75.213876],
            [21.869145, 75.214469],
            [21.869929, 75.215546],
        ],
    ),
]

# Helper groups for mapping
MANAWAR_GEOFENCE_NAMES = {
    "Charging Point",
    "Loading Area",
    "Weighing Area",
    "Tarpulien",
}
MAHA_BORDER_NAME = "Maha Border"
D1_JHULWANIA = "D1 Jhulwania (50 m)"
D2_JHULWANIA = "D2 Jhulwania (50 m)"
MANAWAR_OUT = "Manawar Out Area"
DHULE_GATE = "Dhule Gate"
DHULE_UNLOADING = "Dhule Circle Geofence"
