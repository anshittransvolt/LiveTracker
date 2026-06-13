from typing import Dict, List, Tuple
from datetime import datetime, timedelta
import pandas as pd

from livetracker.views import fetch_day
from mis.services.geofence_processor import GeofenceProcessor


def _rdp_simplify(points: List[Tuple[float, float]], epsilon_m: float) -> List[Tuple[float, float]]:
    # Ramer–Douglas–Peucker in equirectangular meters
    import math

    if len(points) <= 2:
        return points

    lat0 = sum(p[0] for p in points) / len(points)
    lat0_rad = math.radians(lat0)
    k = 111_320.0

    def to_xy(pt):
        return (pt[1] * k * math.cos(lat0_rad), pt[0] * k)

    def seg_dist(p, a, b):
        ax, ay = to_xy(a)
        bx, by = to_xy(b)
        px, py = to_xy(p)
        vx, vy = bx - ax, by - ay
        wx, wy = px - ax, py - ay
        vlen2 = vx * vx + vy * vy
        if vlen2 == 0:
            return math.hypot(px - ax, py - ay)
        t = max(0.0, min(1.0, (wx * vx + wy * vy) / vlen2))
        cx, cy = ax + t * vx, ay + t * vy
        return math.hypot(px - cx, py - cy)

    def rdp(seq: List[Tuple[float, float]]):
        if len(seq) <= 2:
            return seq
        a, b = seq[0], seq[-1]
        idx, max_d = -1, -1.0
        for i in range(1, len(seq) - 1):
            d = seg_dist(seq[i], a, b)
            if d > max_d:
                max_d = d
                idx = i
        if max_d > epsilon_m and idx != -1:
            left = rdp(seq[: idx + 1])
            right = rdp(seq[idx:])
            return left[:-1] + right
        else:
            return [a, b]

    return rdp(points)


def _collect_segment_points(intervals_df: pd.DataFrame, visits: List[Dict], sample_step: int = 5) -> Dict[str, List[Tuple[float, float]]]:
    seg_points: Dict[str, List[Tuple[float, float]]] = {"M_J": [], "J_D": [], "D_J": [], "J_M": [], "D_M": []}
    if not visits:
        return seg_points

    def visit_slice(v):
        return intervals_df.loc[v["start_idx"] : v["end_idx"]].copy()

    name = lambda v: v.get("cluster")
    for i in range(len(visits) - 1):
        a, b = visits[i], visits[i + 1]
        a_name, b_name = name(a), name(b)
        if a_name == b_name:
            continue
        # determine slice between a and b
        start_idx = a["end_idx"] + 1
        end_idx = b["start_idx"] - 1
        if start_idx > end_idx:
            continue
        df = intervals_df.loc[start_idx:end_idx]
        if df.empty:
            continue
        df = df[df["status"] == "Moving"].reset_index(drop=True)
        if df.empty:
            continue
        pts = []
        for j in range(0, len(df), max(1, sample_step)):
            r = df.iloc[j]
            lat = r.get("lat")
            lon = r.get("lon")
            if pd.notna(lat) and pd.notna(lon):
                pts.append((float(lat), float(lon)))
        key = None
        if a_name == "Manawar" and b_name == "Julwaniya":
            key = "M_J"
        elif a_name == "Julwaniya" and b_name == "Dhule":
            key = "J_D"
        elif a_name == "Dhule" and b_name == "Julwaniya":
            key = "D_J"
        elif a_name == "Julwaniya" and b_name == "Manawar":
            key = "J_M"
        elif a_name == "Dhule" and b_name == "Manawar":
            key = "D_M"
        if key and pts:
            seg_points[key].extend(pts)

    return seg_points


def learn_corridor(start_date: str, end_date: str, epsilon_m: float = 500.0, sample_step: int = 5, min_points: int = 50) -> Dict:
    # Aggregate across days and vehicles
    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()
    gp = GeofenceProcessor()

    agg: Dict[str, List[Tuple[float, float]]] = {"M_J": [], "J_D": [], "D_J": [], "J_M": [], "D_M": []}
    d = start
    while d < end:
        day_str = d.strftime("%Y-%m-%d")
        next_str = (d + timedelta(days=1)).strftime("%Y-%m-%d")
        data = fetch_day(None, day_str, next_str) or []
        if not data:
            d += timedelta(days=1)
            continue
        # group by vehicle
        by_vehicle: Dict[str, List[Dict]] = {}
        for rec in data:
            vn = rec.get("vehicle_no")
            if vn:
                by_vehicle.setdefault(vn, []).append(rec)
        for vn, records in by_vehicle.items():
            df = pd.DataFrame.from_records(records)
            if df.empty or "last_connected" not in df.columns:
                continue
            df = df.sort_values("last_connected").reset_index(drop=True)
            # Process
            try:
                telem = gp.process_telemetry(df)
                intervals = gp.build_intervals(telem)
                visits = gp.build_cluster_visits(intervals)
                seg_pts = _collect_segment_points(intervals, visits, sample_step=sample_step)
                for k, pts in seg_pts.items():
                    if pts:
                        agg[k].extend(pts)
            except Exception:
                continue
        d += timedelta(days=1)

    # Simplify per segment
    segments = {}
    for key, pts in agg.items():
        if len(pts) < min_points:
            segments[key] = {"polyline": [], "buffer_m": 3000}
            continue
        simp = _rdp_simplify(pts, epsilon_m=epsilon_m)
        segments[key] = {"polyline": simp, "buffer_m": 3000}

    return {"segments": segments}
