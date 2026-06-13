import logging
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple

logger = logging.getLogger(__name__)

# Geofence constants and helper functions (inlined to avoid route_timeline dependency)

# Geofence definitions
MANAWAR_CHARGING = (22.265636, 75.127046, 100)  # lat, lon, radius (meters)
JHULWANIA_CHARGING_POLY = [
    (21.870919, 75.214750),
    (21.870419, 75.213876),
    (21.869145, 75.214469),
    (21.869929, 75.215546),
]
DHULE_CHARGING_POLY = [
    (21.150138, 74.850055),
    (21.148732, 74.849582),
    (21.149454, 74.847823),
    (21.150652, 74.848260),
]
MAHA_BORDER = (21.427817, 74.980463, 500)

# Loading/unloading geofences
MANAWAR_LOADING_POLY = [
    (22.271683, 75.138225),
    (22.268312, 75.128871),
    (22.262503, 75.128803),
    (22.262364, 75.139468),
]
DHULE_UNLOADING = (21.15111842, 74.84979354, 100)

def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    # approximate radius of earth in meters
    R = 6371000
    from math import radians, sin, cos, sqrt, atan2
    phi1 = radians(lat1)
    phi2 = radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c

def _point_in_circle(lat: float, lon: float, center_lat: float, center_lon: float, radius_m: float) -> bool:
    try:
        return _haversine_m(lat, lon, center_lat, center_lon) <= radius_m
    except Exception:
        return False

def _point_in_polygon(lat: float, lon: float, polygon_points: List[Tuple[float, float]]) -> bool:
    # Ray casting algorithm for point-in-polygon
    x = lon
    y = lat
    inside = False
    n = len(polygon_points)
    for i in range(n):
        yi, xi = polygon_points[i]
        yj, xj = polygon_points[(i + 1) % n]
        intersect = ((xi > x) != (xj > x)) and (
            y < (yj - yi) * (x - xi) / (xj - xi + 1e-15) + yi
        )
        if intersect:
            inside = not inside
    return inside

def parse_gps_location(gps_location: str) -> Tuple[float, float]:
    lat, lon = map(float, (gps_location or '').split(","))
    return lat, lon

def get_geofence_status(lat: float, lon: float, vehicle_status: str) -> str:
    s = (vehicle_status or "").lower()
    # Loading/unloading geofences
    if _point_in_polygon(lat, lon, MANAWAR_LOADING_POLY):
        return 'manawar_loading'
    if _point_in_circle(lat, lon, *DHULE_UNLOADING):
        return 'dhule_unloading'
    if _point_in_circle(lat, lon, *MANAWAR_CHARGING):
        return 'manawar_charging' if s == 'charging' else 'manawar_yard'
    if _point_in_polygon(lat, lon, JHULWANIA_CHARGING_POLY):
        return 'jhulwania_charging' if s == 'charging' else 'jhulwania_yard'
    if _point_in_polygon(lat, lon, DHULE_CHARGING_POLY):
        return 'dhule_charging' if s == 'charging' else 'dhule_yard'
    if _point_in_circle(lat, lon, *MAHA_BORDER):
        return 'maha_border'
    # If not in any geofence, use vehicle_status as fallback
    if s == 'charging':
        return 'charging_unknown'
    elif s == 'yard':
        return 'yard_unknown'
    else:
        return 'transit'

def _zone_from_phase(phase: str) -> str:
    # Normalize the phase down to a zone name
    if not phase:
        return 'unknown'
    p = phase.lower()
    if 'manawar' in p:
        return 'manawar'
    if 'jhulwania' in p:
        return 'jhulwania'
    if 'dhule' in p:
        return 'dhule'
    if 'maha' in p or 'mahaborder' in p or 'maha_border' in p:
        return 'maha_border'
    return 'unknown'

# Clusters allowed unordered at endpoints
MANAWAR_CLUSTER = {"manawar_loading", "manawar_yard", "manawar_charging"}
DHULE_CLUSTER = {"dhule_unloading", "dhule_yard", "dhule_charging"}

ClusterName = str  # "manawar" | "jhulwania" | "dhule" | "maha_border" | "other"


def _record_to_phase(rec: Dict[str, Any]) -> Optional[str]:
    try:
        # Prefer separate lat/lon fields (fetch_geo / fetch_combined format)
        _lat = rec.get("latitude")
        _lon = rec.get("longitude")
        if _lat is not None and _lon is not None:
            lat = float(_lat)
            lon = float(_lon)
        else:
            # Fallback: parse gps_location string
            gps_loc = rec.get("gps_location") or ""
            if not gps_loc or gps_loc == "0,0":
                return None
            lat, lon = parse_gps_location(gps_loc)
        if lat == 0.0 and lon == 0.0:
            return None
    except Exception as e:
        logger.debug(f"Failed to parse GPS location: {rec}, error: {e}")
        return None
    try:
        status = rec.get("vehicle_status", "")
        phase = get_geofence_status(lat, lon, status)
        return phase
    except Exception as e:
        logger.debug(f"Failed to get geofence status for lat={lat}, lon={lon}, status={status}: {e}")
        return None


def _build_intervals(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Build contiguous intervals of same phase from telemetry records.
    Each interval: {phase, start, end, duration_seconds}
    """
    if not records:
        return []
    # Sort by time
    try:
        records = sorted(records, key=lambda r: r.get("last_connected", ""))
    except Exception:
        pass
    
    intervals: List[Dict[str, Any]] = []
    current_phase = None
    start_dt: Optional[datetime] = None
    last_dt: Optional[datetime] = None
    phases_found = []
    
    for rec in records:
        ts_str = rec.get("last_connected")
        try:
            # Handle different datetime formats:
            # ISO format (e.g. "2026-02-05T09:52:03Z" or "2026-02-05T09:52:03+00:00")
            # Space-separated format (e.g. "2026-02-05 09:52:03")
            if isinstance(ts_str, str):
                if 'T' in ts_str or '+' in ts_str:
                    dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                else:
                    dt = datetime.fromisoformat(ts_str)
            else:
                dt = ts_str
        except Exception:
            continue
        
        phase = _record_to_phase(rec)
        if phase is None:
            continue
        
        phases_found.append(phase)
        if current_phase is None:
            current_phase = phase
            start_dt = dt
            last_dt = dt
            continue
        if phase == current_phase:
            last_dt = dt
            continue
        # close previous interval
        if current_phase is not None and start_dt is not None and last_dt is not None:
            intervals.append({
                "phase": current_phase,
                "start": start_dt.isoformat(),
                "end": last_dt.isoformat(),
                "duration_seconds": int((last_dt - start_dt).total_seconds()),
            })
        # open new interval
        current_phase = phase
        start_dt = dt
        last_dt = dt
    # close tail
    if current_phase is not None and start_dt is not None and last_dt is not None:
        intervals.append({
            "phase": current_phase,
            "start": start_dt.isoformat(),
            "end": last_dt.isoformat(),
            "duration_seconds": int((last_dt - start_dt).total_seconds()),
        })
    
    return intervals


def _cluster_name(phase: str) -> ClusterName:
    z = _zone_from_phase(phase)
    return z


def _build_cluster_visits(intervals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Aggregate consecutive intervals by cluster (zone). A visit comprises
    contiguous intervals with the same cluster.
    visit: {cluster, start, end, start_idx, end_idx}
    """
    visits: List[Dict[str, Any]] = []
    current_cluster: Optional[ClusterName] = None
    start: Optional[str] = None
    start_idx: Optional[int] = None
    for idx, itv in enumerate(intervals):
        phase = itv.get("phase", "")
        cluster = _cluster_name(phase)
        if cluster == "unknown":
            continue
        if current_cluster is None:
            current_cluster = cluster
            start = itv.get("start")
            start_idx = idx
            end = itv.get("end")
            continue
        if cluster == current_cluster:
            end = itv.get("end")
            continue
        # close previous visit
        if current_cluster is not None and start is not None:
            visits.append({
                "cluster": current_cluster.capitalize() if isinstance(current_cluster, str) else current_cluster,
                "start": start,
                "end": end,
                "start_idx": start_idx,
                "end_idx": idx - 1,
            })
        # open new visit
        current_cluster = cluster
        start = itv.get("start")
        start_idx = idx
        end = itv.get("end")
    # tail
    if current_cluster is not None and start is not None:
        visits.append({
            "cluster": current_cluster.capitalize() if isinstance(current_cluster, str) else current_cluster,
            "start": start,
            "end": end,
            "start_idx": start_idx,
            "end_idx": len(intervals) - 1,
        })
    return visits


def _detect_trips(visits: List[Dict[str, Any]]) -> List[Tuple[int, int, str]]:
    """
    Detect complete trips based on cluster flow with shuttle tolerance:
    - Forward: Manawar → Jhulwania → Dhule
    - Return: shuttle loops between Jhulwania/Dhule → Manawar
    Returns list of tuples (start_visit_idx, end_visit_idx, direction)
    """
    trips: List[Tuple[int, int, str]] = []
    i = 0
    n = len(visits)
    while i < n:
        if visits[i]["cluster"] != "Manawar":
            i += 1
            continue
        j = i + 1
        if j >= n or visits[j]["cluster"] != "Jhulwania":
            i += 1
            continue
        j += 1
        if j >= n or visits[j]["cluster"] != "Dhule":
            i += 1
            continue
        # forward complete, scan for return Manawar
        last_loc = "Dhule"
        while j < n:
            c = visits[j]["cluster"]
            if c == "Manawar":
                trips.append((i, j, "dhar_to_dhule"))
                i = j  # next search starts at return Manawar
                break
            elif c in ("Dhule", "Jhulwania"):
                last_loc = c
                j += 1
                continue
            else:
                # Unknown cluster breaks scanning
                i += 1
                break
        else:
            # Ran out of visits without return Manawar
            i += 1
    return trips


def _build_phases_from_intervals(intervals: List[Dict[str, Any]], direction: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Convert intervals into UI phases with durations.
    We keep cluster dwells and derive transit phases between consecutive clusters.
    If no cluster dwells are found, include transit phases as fallback.
    Gap-filling is intentionally not performed here.
    """
    phases: List[Dict[str, Any]] = []
    # Add dwell intervals directly (skip generic 'transit' dwell initially)
    for itv in intervals:
        phase = itv.get("phase", "")
        if not phase or phase == "transit":
            continue
        phases.append({
            "phase": phase,
            "start": itv.get("start"),
            "end": itv.get("end"),
            "duration_seconds": itv.get("duration_seconds"),
        })
    
    # If no cluster dwells found, use transit phases as fallback
    if not phases:
        for itv in intervals:
            phase = itv.get("phase", "")
            if phase == "transit":
                phases.append({
                    "phase": phase,
                    "start": itv.get("start"),
                    "end": itv.get("end"),
                    "duration_seconds": itv.get("duration_seconds"),
                })
    
    # Derive transits between consecutive cluster dwells
    # Sort by start
    try:
        phases.sort(key=lambda x: x.get("start", ""))
    except Exception:
        pass
    # Helper to normalize transit names to canonical UI keys using direction
    def normalize_transit(c1: str, c2: str, dirn: Optional[str]) -> str:
        if dirn == 'dhar_to_dhule':
            if c1 == 'manawar' and c2 in ('jhulwania', 'maha_border', 'dhule'):
                return 'manawar_to_jhulwania'
            if c1 == 'jhulwania' and c2 in ('maha_border', 'dhule'):
                return 'jhulwania_to_maha_border'
            if c1 == 'maha_border' and c2 == 'dhule':
                return 'maha_border_to_dhule'
        elif dirn == 'dhule_to_dhar':
            if c1 == 'dhule' and c2 in ('maha_border', 'jhulwania', 'manawar'):
                return 'dhule_to_maha_border'
            if c1 == 'maha_border' and c2 in ('jhulwania', 'manawar'):
                return 'maha_border_to_jhulwania'
            if c1 == 'jhulwania' and c2 == 'manawar':
                return 'jhulwania_to_manawar'
        # Fallback to raw pair
        return f"{c1}_to_{c2}"

    # Insert transits between cluster dwells (skip if we're using transit as fallback)
    if len(phases) > 1 and all(p.get('phase') != 'transit' for p in phases):
        i = 0
        while i < len(phases) - 1:
            p1 = phases[i]
            p2 = phases[i + 1]
            c1 = _zone_from_phase(p1.get("phase", ""))
            c2 = _zone_from_phase(p2.get("phase", ""))
            if c1 not in ("unknown", None) and c2 not in ("unknown", None) and c1 != c2:
                # Transit name
                transit = normalize_transit(c1, c2, direction)
                # Use end of p1 and start of p2
                try:
                    t1 = datetime.fromisoformat((p1.get("end") or p1.get("start")).replace("Z", "+00:00"))
                    t2 = datetime.fromisoformat((p2.get("start") or p2.get("end")).replace("Z", "+00:00"))
                    dur = max(0, int((t2 - t1).total_seconds()))
                    phases.insert(i + 1, {
                        "phase": transit,
                        "start": t1.isoformat(),
                        "end": t2.isoformat(),
                        "duration_seconds": dur,
                    })
                    i += 2
                    continue
                except Exception:
                    pass
            i += 1
    return phases


def build_timebox_for_vehicle(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Build timebox for a single vehicle from multi-day records.
    - Uses 2-day lookback (records provided should already be multi-day).
    - Segments trips and sets direction for the latest trip segment.
    - Phases include dwell and derived transits; no gap-filling.
    - Trip duration shows M→D (forward) or D→M (return) time for the latest complete trip; otherwise current segment duration.
    """
    intervals = _build_intervals(records)
    visits = _build_cluster_visits(intervals)
    trips = _detect_trips(visits)

    # Determine direction for latest trip or current segment
    direction = None
    latest_trip_duration_sec = None
    current_trip_duration_sec = None
    latest_trip_drive_sec = None
    current_trip_drive_sec = None
    if trips:
        start_idx, end_idx, direction = trips[-1]
        # One-way trip duration: departure Manawar ENTRY (loading start) → return Manawar ENTRY
        # Includes loading time at source so trip clock starts when vehicle arrives to load.
        try:
            m1_in = datetime.fromisoformat(visits[start_idx]["start"].replace("Z", "+00:00"))
            m2_in = datetime.fromisoformat(visits[end_idx]["start"].replace("Z", "+00:00"))
            latest_trip_duration_sec = max(0, int((m2_in - m1_in).total_seconds()))
        except Exception:
            latest_trip_duration_sec = None
    else:
        # If no complete trip, infer direction by recent cluster order.
        # Priority 1: recent pair heuristic
        if len(visits) >= 2:
            if visits[-2]["cluster"] == "Manawar" and visits[-1]["cluster"] == "Jhulwania":
                direction = "dhar_to_dhule"
            elif visits[-2]["cluster"] in ("Dhule", "Maha_border") and visits[-1]["cluster"] in ("Maha_border", "Jhulwania", "Manawar"):
                direction = "dhule_to_dhar"
        if direction is None:
            # Priority 2: if Dhule was visited and there is ANY cluster visit after it,
            # the vehicle has left Dhule and is on the return leg.
            dhule_indices = [i for i, v in enumerate(visits) if v["cluster"] == "Dhule"]
            if dhule_indices:
                last_dhule_idx = dhule_indices[-1]
                if last_dhule_idx < len(visits) - 1:
                    direction = "dhule_to_dhar"  # Something came after Dhule → return
                else:
                    direction = "dhar_to_dhule"  # Still at Dhule
            elif visits:
                # Priority 3: first/last cluster
                first = visits[0]["cluster"]
                last = visits[-1]["cluster"]
                if first == "Manawar" and last in ("Jhulwania", "Dhule", "Maha_border"):
                    direction = "dhar_to_dhule"
                elif first in ("Dhule", "Jhulwania") and last in ("Maha_border", "Jhulwania", "Manawar"):
                    direction = "dhule_to_dhar"
                else:
                    direction = "dhar_to_dhule"
            else:
                direction = "dhar_to_dhule"

    # ── Source-cluster anchors ──────────────────────────────────────────────────
    # current_segment_start_ts = entry into source cluster (loading/unloading start)
    # current_segment_end_ts   = exit from source cluster (when driving began)
    # Source cluster: Manawar for dhar_to_dhule, Dhule for dhule_to_dhar.
    # When a dhule_to_dhar vehicle returns to Manawar, _detect_trips flips direction to
    # dhar_to_dhule and the anchor becomes the new Manawar entry → trip clock never resets to 0.
    current_segment_start_ts = None
    current_segment_end_ts = None
    if visits:
        _src = 'Manawar' if direction == 'dhar_to_dhule' else 'Dhule'
        for _v in reversed(visits):
            if _v['cluster'] == _src:
                current_segment_start_ts = _v.get('start')
                current_segment_end_ts = _v.get('end')
                break

    # ── Shared latest-telemetry timestamp ────────────────────────────────────────
    last_ts = None
    try:
        if records:
            _latest_str = max((r.get("last_connected") or "" for r in records), default="")
            if _latest_str:
                last_ts = datetime.fromisoformat(_latest_str.replace("Z", "+00:00"))
    except Exception:
        last_ts = None
    if last_ts is None:
        last_ts = datetime.now()

    # ── current_trip_duration_sec ─────────────────────────────────────────────────
    # One-way trip elapsed time: source-cluster ENTRY → latest telemetry.
    # Includes loading/unloading dwell at source so the clock starts the moment
    # the vehicle arrives (not when it departs).
    try:
        if current_segment_start_ts:
            _seg_start = datetime.fromisoformat(current_segment_start_ts.replace("Z", "+00:00"))
            current_trip_duration_sec = max(0, int((last_ts - _seg_start).total_seconds()))
    except Exception:
        current_trip_duration_sec = None

    phases = _build_phases_from_intervals(intervals, direction)

    # Helper: sum moving (drive) seconds from raw telemetry between start_dt and end_dt
    def _sum_moving_seconds(recs: List[Dict[str, Any]], start_dt: Optional[datetime], end_dt: Optional[datetime]) -> Optional[int]:
        if start_dt is None or end_dt is None:
            return None
        # Sort by timestamp
        try:
            recs = sorted(recs, key=lambda r: r.get("last_connected", ""))
        except Exception:
            pass
        total = 0
        for i in range(len(recs) - 1):
            r1 = recs[i]
            r2 = recs[i + 1]
            try:
                t1 = datetime.fromisoformat((r1.get("last_connected") or "").replace("Z", "+00:00"))
                t2 = datetime.fromisoformat((r2.get("last_connected") or "").replace("Z", "+00:00"))
            except Exception:
                continue
            if not t1 or not t2 or t2 <= t1:
                continue
            status = (r1.get("vehicle_status") or "").strip().lower()
            # Consider only intervals where the vehicle was moving
            # Accept both "moving" (legacy) and "move" (Twins/Telemetry adapters)
            if status not in ("moving", "move"):
                continue
            # Overlap the [t1, t2] segment with [start_dt, end_dt]
            s = max(start_dt, t1)
            e = min(end_dt, t2)
            if e > s:
                total += int((e - s).total_seconds())
        return total

    # Compute drive time (moving-only) for latest completed trip
    try:
        if trips:
            start_idx, end_idx, _dir = trips[-1]
            m1_out = datetime.fromisoformat(visits[start_idx]["end"].replace("Z", "+00:00"))
            m2_in = datetime.fromisoformat(visits[end_idx]["start"].replace("Z", "+00:00"))
            latest_trip_drive_sec = _sum_moving_seconds(records, m1_out, m2_in)
    except Exception:
        latest_trip_drive_sec = None

    # ── current_trip_drive_sec ──────────────────────────────────────────────────
    # Moving-only seconds from source-cluster EXIT to latest telemetry.
    # (Vehicle is not driving while loading/unloading at source, so drive clock
    # starts from when the vehicle left the source cluster.)
    try:
        if current_segment_end_ts:
            _seg_end = datetime.fromisoformat(current_segment_end_ts.replace("Z", "+00:00"))
            current_trip_drive_sec = _sum_moving_seconds(records, _seg_end, last_ts)
    except Exception:
        current_trip_drive_sec = None

    return {
        "direction": direction,
        "timeline": phases,
        "latest_trip_duration_seconds": latest_trip_duration_sec,
        "current_trip_duration_seconds": current_trip_duration_sec,
        "latest_trip_drive_seconds": latest_trip_drive_sec,
        "current_trip_drive_seconds": current_trip_drive_sec,
        "current_segment_start_ts": current_segment_start_ts,
    }


def build_timebox_for_all(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build timebox for all vehicles from multi-day data keyed by vehicle number.

    Accepts both of the following input formats per vehicle key:
    - List[Dict]: direct list of telemetry records
    - Dict with 'points': {'points': List[Dict], ...} as returned by DataSourceManager/Twins/Telemetry adapters
    """
    results: Dict[str, Any] = {}
    for vehicle_no, records in data.items():
        # Normalize records to a list of points
        normalized_records: List[Dict[str, Any]] = []
        try:
            if isinstance(records, list):
                normalized_records = records
            elif isinstance(records, dict):
                pts = records.get('points')
                if isinstance(pts, list):
                    normalized_records = pts
            # If neither, leave as empty
        except Exception:
            normalized_records = []

        if not normalized_records:
            results[vehicle_no] = {"direction": None, "timeline": []}
            continue
        try:
            results[vehicle_no] = build_timebox_for_vehicle(normalized_records)
        except Exception as e:
            logger.error(f"Timebox error for {vehicle_no}: {e}")
            results[vehicle_no] = {"direction": None, "timeline": []}
    return results
