"""
Route Corridor Configuration
============================
Lightweight loader for corridor polylines and buffer thresholds used to detect
route deviation along M→J, J→D, and D→M segments.

Provide a JSON file path via environment or settings (DJANGO) with the schema
documented below. Minimal defaults are provided if no file is configured.

Environment/Settings:
- Env var: CORRIDOR_CONFIG_PATH=/path/to/corridor_config.json
- Django settings: settings.CORRIDOR_CONFIG_PATH

JSON Schema (example):
{
  "segments": {
    "M_J": {
      "polyline": [[lat, lon], [lat, lon], ...],
      "buffer_m": 3000
    },
    "J_D": {
      "polyline": [[lat, lon], ...],
      "buffer_m": 3000
    },
    "D_M": {
      "polyline": [[lat, lon], ...],
      "buffer_m": 3000
    }
  }
}

Notes:
- Use 10–50 points per segment; more points give a closer corridor fit.
- Tune buffer_m per segment (typical 2000–5000 m).
"""

from dataclasses import dataclass
from typing import List, Tuple, Dict, Optional
import json
import os

try:
    from django.conf import settings
except Exception:
    settings = None  # allows use outside Django if needed


@dataclass
class CorridorSegment:
    name: str
    polyline: List[Tuple[float, float]]  # [(lat, lon), ...]
    buffer_m: int


@dataclass
class CorridorConfig:
    segments: Dict[str, CorridorSegment]

    def get(self, key: str) -> Optional[CorridorSegment]:
        return self.segments.get(key)


def _read_config_path() -> Optional[str]:
    # Priority: Django settings -> ENV var -> default file in repo
    if settings and hasattr(settings, "CORRIDOR_CONFIG_PATH"):
        return getattr(settings, "CORRIDOR_CONFIG_PATH")
    env_path = os.getenv("CORRIDOR_CONFIG_PATH")
    if env_path:
        return env_path
    # default relative path (can be overridden)
    default_path = os.path.join(os.path.dirname(__file__), "corridor_config.json")
    if os.path.exists(default_path):
        return default_path
    return None


def load_corridor() -> CorridorConfig:
    path = _read_config_path()
    if not path:
        # Provide minimal empty config with sensible defaults
        return CorridorConfig(
            segments={
                "M_J": CorridorSegment("M_J", [], 3000),
                "J_D": CorridorSegment("J_D", [], 3000),
                "D_M": CorridorSegment("D_M", [], 3000),
            }
        )

    try:
        with open(path, "r") as f:
            data = json.load(f)
        raw_segments = data.get("segments") or {}
        segments: Dict[str, CorridorSegment] = {}
        for key in ["M_J", "J_D", "D_M"]:
            seg = raw_segments.get(key) or {}
            poly = seg.get("polyline") or []
            buf = int(seg.get("buffer_m") or 3000)
            # Normalize tuples
            poly_norm: List[Tuple[float, float]] = [
                (float(p[0]), float(p[1])) for p in poly if isinstance(p, (list, tuple)) and len(p) == 2
            ]
            segments[key] = CorridorSegment(name=key, polyline=poly_norm, buffer_m=buf)
        return CorridorConfig(segments=segments)
    except Exception:
        # Fallback to empty segments if file is invalid
        return CorridorConfig(
            segments={
                "M_J": CorridorSegment("M_J", [], 3000),
                "J_D": CorridorSegment("J_D", [], 3000),
                "D_M": CorridorSegment("D_M", [], 3000),
            }
        )
