from typing import List, Tuple, Dict, Optional
import math
import pandas as pd


def _to_xy_m(lat: float, lon: float, lat0_rad: float) -> Tuple[float, float]:
    # Equirectangular projection in meters (good for small areas)
    # 1 deg lat ~ 111_320 m; 1 deg lon ~ 111_320 * cos(lat)
    k = 111_320.0
    x = lon * k * math.cos(lat0_rad)
    y = lat * k
    return x, y


def _point_to_segment_distance_m(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    # Distance from P to segment AB in 2D
    vx, vy = bx - ax, by - ay
    wx, wy = px - ax, py - ay
    vlen2 = vx * vx + vy * vy
    if vlen2 == 0:
        dx, dy = px - ax, py - ay
        return math.hypot(dx, dy)
    t = max(0.0, min(1.0, (wx * vx + wy * vy) / vlen2))
    cx, cy = ax + t * vx, ay + t * vy
    return math.hypot(px - cx, py - cy)


def point_to_polyline_distance_m(lat: float, lon: float, polyline: List[Tuple[float, float]]) -> float:
    if not polyline or len(polyline) == 1:
        return float("inf")
    lat0 = sum(p[0] for p in polyline) / len(polyline)
    lat0_rad = math.radians(lat0)
    px, py = _to_xy_m(lat, lon, lat0_rad)
    min_d = float("inf")
    prev = None
    for pt in polyline:
        if prev is None:
            prev = pt
            continue
        ax, ay = _to_xy_m(prev[0], prev[1], lat0_rad)
        bx, by = _to_xy_m(pt[0], pt[1], lat0_rad)
        d = _point_to_segment_distance_m(px, py, ax, ay, bx, by)
        if d < min_d:
            min_d = d
        prev = pt
    return min_d


def evaluate_segment_deviation(
    df: pd.DataFrame,
    polyline: List[Tuple[float, float]],
    buffer_m: float,
    require_cols: Tuple[str, str] = ("lat", "lon"),
) -> Dict[str, Optional[float]]:
    if df is None or df.empty or not polyline:
        return {
            "points": 0,
            "violations": 0,
            "duration_s": 0.0,
            "max_distance_m": 0.0,
        }
    lat_col, lon_col = require_cols
    violations = 0
    points = 0
    duration_s = 0.0
    max_d = 0.0
    for _, r in df.iterrows():
        lat = r.get(lat_col)
        lon = r.get(lon_col)
        if pd.isna(lat) or pd.isna(lon):
            continue
        d = point_to_polyline_distance_m(float(lat), float(lon), polyline)
        points += 1
        if d > max_d:
            max_d = d
        if d > buffer_m:
            violations += 1
            try:
                dur = float(r.get("duration_s") or 0.0)
            except Exception:
                dur = 0.0
            duration_s += dur
    return {
        "points": points,
        "violations": violations,
        "duration_s": duration_s,
        "max_distance_m": max_d,
    }
