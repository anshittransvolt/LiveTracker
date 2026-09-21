"""
Route Master
============
Identifies frequently-driven routes for a project by pulling recent GPS
history for its fleet from the TWINS `fetch_geo` endpoint, grouping each
vehicle's daily path into a "vehicle-day" trace, and clustering traces that
cover the same ground (via a coarse grid-cell signature + Jaccard overlap)
into named "frequent routes" — the same pattern already known to exist for
Ultratech's fixed mine-jetty-depot run, computed here instead of by eyeballing
the map.

Entry point: build_route_master(spv='NAGPUR', days=7) -> dict, which also
caches its result (read back cheaply via get_cached_route_master).
"""

from __future__ import annotations

import hashlib
import logging
import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone as dt_timezone
from typing import Any, Dict, List, Optional, Tuple

import pytz
import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

_IST = pytz.timezone("Asia/Kolkata")

CACHE_TTL = 60 * 60 * 26  # slightly over a day, so a daily cron refresh always beats it
GEOCODE_CACHE_TIMEOUT = 86400  # matches views.reverse_geocode's cache lifetime

# India bounding box — cheap sanity filter for garbage GPS fixes (0,0 etc.)
_LAT_RANGE = (6.0, 38.0)
_LON_RANGE = (68.0, 98.0)


def _resolve_project(spv_key: Optional[str]) -> Tuple[str, str]:
    """Map a project key to its (vendor, spv) pair, mirroring views._resolve_twins_project."""
    mapping = {
        "ULTRATECH": (getattr(settings, "TWINS_VENDOR", "intangles"), getattr(settings, "TWINS_SPV", "ultratech")),
        "UMT": (getattr(settings, "TWINS_UMT_VENDOR", "intangles"), getattr(settings, "TWINS_UMT_SPV", "UMT")),
        "MBMT": (getattr(settings, "TWINS_MBMT_VENDOR", "intangles"), getattr(settings, "TWINS_MBMT_SPV", "MBMT")),
        "NAGPUR": (getattr(settings, "TWINS_NAGPUR_VENDOR", "eka"), getattr(settings, "TWINS_NAGPUR_SPV", "nagpur")),
        "VECV": (getattr(settings, "TWINS_VECV_VENDOR", "intangles"), getattr(settings, "TWINS_VECV_SPV", "VECV")),
        "STAR_CEMENT": (getattr(settings, "TWINS_STAR_CEMENT_VENDOR", "propel"), getattr(settings, "TWINS_STAR_CEMENT_SPV", "STAR_CEMENT")),
        "JM_BAXI": (getattr(settings, "TWINS_JM_BAXI_VENDOR", "eim"), getattr(settings, "TWINS_JM_BAXI_SPV", "JM_BAXI")),
        "GTI": (getattr(settings, "TWINS_GTI_VENDOR", "eim"), getattr(settings, "TWINS_GTI_SPV", "GTI")),
    }
    key = (spv_key or "NAGPUR").strip().upper()
    return mapping.get(key, mapping["NAGPUR"])


def _cache_key(spv: str, days: int) -> str:
    return f"route_master:{spv.strip().upper()}:{days}"


def get_cached_route_master(spv: str = "NAGPUR", days: int = 7) -> Optional[Dict[str, Any]]:
    return cache.get(_cache_key(spv, days))


# ---------------------------------------------------------------------------
# Fleet + GPS history fetching
# ---------------------------------------------------------------------------

def get_fleet_vehicles(vendor: str, spv: str) -> List[str]:
    """Registration numbers currently reporting for this project (cached 1h)."""
    cache_key = f"route_master_vehicles:{vendor}:{spv}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    url = f"{settings.TWINS_API_URL.rstrip('/')}/latest_points"
    params = {"vendor": vendor, "limit": 5}
    resp = requests.get(
        url,
        headers={"Authorization": f"Bearer {settings.TWINS_API_TOKEN}"},
        params=params,
        timeout=30,
    )
    resp.raise_for_status()
    vehicles_raw = resp.json().get("vehicles", {}) or {}

    spv_upper = spv.strip().upper()
    result = sorted(
        reg
        for reg, pts in vehicles_raw.items()
        if isinstance(pts, list) and pts and (pts[0].get("spv") or "").strip().upper() == spv_upper
    )
    cache.set(cache_key, result, 3600)
    return result


def fetch_vehicle_day_points(reg: str, date_str: str, vendor: str, spv: str) -> List[Dict[str, Any]]:
    """Raw fetch_geo points for one vehicle over one IST calendar day, paginated."""
    url = f"{settings.TWINS_API_URL.rstrip('/')}/fetch_geo"
    headers = {"Authorization": f"Bearer {settings.TWINS_API_TOKEN}"}
    all_points: List[Dict[str, Any]] = []
    cursor = None

    for _ in range(5):  # safety cap — a single day should never need this many 5000-row pages
        params = {
            "vendor": vendor,
            "page_size": 5000,
            "registration_number": reg,
            "start_time": f"{date_str}T00:00:00",
            "end_time": f"{date_str}T23:59:59",
        }
        if vendor != "eim":  # eim's fetch_geo rejects its own spv value (upstream quirk)
            params["spv"] = spv
        if cursor:
            params["cursor"] = cursor

        resp = None
        for attempt in range(4):  # handles the API's rate limiting under concurrent load
            try:
                resp = requests.get(url, headers=headers, params=params, timeout=30)
            except requests.RequestException as e:
                logger.warning(f"fetch_geo request error for {reg} on {date_str}: {e}")
                resp = None
                break
            if resp.status_code == 429 or resp.status_code >= 500:
                wait_s = float(resp.headers.get("Retry-After") or (2 ** attempt))
                time.sleep(min(wait_s, 20.0))
                continue
            break

        if resp is None:
            break
        try:
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.warning(f"fetch_geo failed for {reg} on {date_str}: {e}")
            break

        data = resp.json()
        pts = (data.get("vehicles") or {}).get(reg) or []
        all_points.extend(pts)

        if data.get("has_more") and data.get("next_cursor"):
            cursor = data["next_cursor"]
        else:
            break

    return all_points


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _to_xy(lat: float, lon: float, lat0: float) -> Tuple[float, float]:
    m_per_deg_lat = 111320.0
    m_per_deg_lon = 111320.0 * math.cos(math.radians(lat0))
    return (lon * m_per_deg_lon, lat * m_per_deg_lat)


def douglas_peucker(points: List[Dict[str, Any]], epsilon_m: float = 25.0) -> List[Dict[str, Any]]:
    """Iterative (non-recursive) Douglas-Peucker simplification."""
    n = len(points)
    if n < 3:
        return points

    lat0 = points[0]["lat"]
    xy = [_to_xy(p["lat"], p["lon"], lat0) for p in points]
    keep = [False] * n
    keep[0] = keep[n - 1] = True
    stack = [(0, n - 1)]

    while stack:
        start, end = stack.pop()
        if end <= start + 1:
            continue
        x1, y1 = xy[start]
        x2, y2 = xy[end]
        dx, dy = x2 - x1, y2 - y1
        norm = math.hypot(dx, dy) or 1e-9
        max_d, idx = -1.0, -1
        for i in range(start + 1, end):
            x0, y0 = xy[i]
            d = abs(dy * x0 - dx * y0 + x2 * y1 - y2 * x1) / norm
            if d > max_d:
                max_d, idx = d, i
        if max_d > epsilon_m:
            keep[idx] = True
            stack.append((start, idx))
            stack.append((idx, end))

    return [points[i] for i in range(n) if keep[i]]


def _dedupe_stationary(points: List[Dict[str, Any]], min_move_m: float = 15.0) -> List[Dict[str, Any]]:
    if not points:
        return []
    out = [points[0]]
    for p in points[1:]:
        if haversine_m(out[-1]["lat"], out[-1]["lon"], p["lat"], p["lon"]) >= min_move_m:
            out.append(p)
    return out


def grid_signature(points: List[Dict[str, Any]], cell_size_m: float = 220.0) -> frozenset:
    """Coarse grid-cell fingerprint of the ground a path covers, for route matching."""
    if not points:
        return frozenset()
    lat0 = points[0]["lat"]
    m_per_deg_lat = 111320.0
    m_per_deg_lon = 111320.0 * math.cos(math.radians(lat0))
    cells = set()
    for p in points:
        cx = int((p["lat"] * m_per_deg_lat) // cell_size_m)
        cy = int((p["lon"] * m_per_deg_lon) // cell_size_m)
        cells.add((cx, cy))
    return frozenset(cells)


def jaccard(a: frozenset, b: frozenset) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter == 0:
        return 0.0
    return inter / len(a | b)


def path_distance_km(points: List[Dict[str, Any]]) -> float:
    total = 0.0
    for i in range(1, len(points)):
        total += haversine_m(points[i - 1]["lat"], points[i - 1]["lon"], points[i]["lat"], points[i]["lon"])
    return total / 1000.0


# ---------------------------------------------------------------------------
# Point parsing + per vehicle-day record
# ---------------------------------------------------------------------------

def _parse_gps_time(gps_time: Any, event_datetime: Any) -> Optional[datetime]:
    if gps_time is not None:
        try:
            ts = float(gps_time)
            if ts > 10_000_000_000:  # milliseconds
                ts /= 1000.0
            return datetime.fromtimestamp(ts, tz=dt_timezone.utc).astimezone(_IST)
        except (TypeError, ValueError, OSError):
            pass
    if event_datetime:
        try:
            naive = datetime.strptime(str(event_datetime)[:19], "%Y-%m-%d %H:%M:%S")
            return _IST.localize(naive)
        except ValueError:
            return None
    return None


def _clean_points(raw_points: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    cleaned = []
    for p in raw_points:
        try:
            lat = float(p.get("latitude"))
            lon = float(p.get("longitude"))
        except (TypeError, ValueError):
            continue
        if lat == 0 and lon == 0:
            continue
        if not (_LAT_RANGE[0] <= lat <= _LAT_RANGE[1] and _LON_RANGE[0] <= lon <= _LON_RANGE[1]):
            continue
        ts = _parse_gps_time(p.get("gps_time"), p.get("event_datetime"))
        if ts is None:
            continue
        cleaned.append({"lat": lat, "lon": lon, "ts": ts})
    cleaned.sort(key=lambda x: x["ts"])
    return cleaned


def build_vehicle_day_record(reg: str, date_str: str, raw_points: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    cleaned = _clean_points(raw_points)
    if len(cleaned) < 15:
        return None

    distance_km = path_distance_km(cleaned)
    if distance_km < 2.0:  # barely moved — not a "route", just a parked/idle day
        return None

    deduped = _dedupe_stationary(cleaned, min_move_m=15.0)
    signature = grid_signature(deduped)
    simplified = douglas_peucker(deduped, epsilon_m=25.0)

    return {
        "id": f"{reg}|{date_str}",
        "vehicle_no": reg,
        "date": date_str,
        "start_time": cleaned[0]["ts"].isoformat(),
        "end_time": cleaned[-1]["ts"].isoformat(),
        "distance_km": round(distance_km, 1),
        "point_count": len(cleaned),
        "signature": signature,
        "polyline": [[round(p["lat"], 5), round(p["lon"], 5)] for p in simplified],
    }


# ---------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------

class _UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def cluster_records(records: List[Dict[str, Any]], jaccard_threshold: float = 0.45) -> List[List[Dict[str, Any]]]:
    n = len(records)
    uf = _UnionFind(n)
    for i in range(n):
        sig_i = records[i]["signature"]
        if not sig_i:
            continue
        for j in range(i + 1, n):
            sig_j = records[j]["signature"]
            if not sig_j:
                continue
            if jaccard(sig_i, sig_j) >= jaccard_threshold:
                uf.union(i, j)

    groups: Dict[int, List[Dict[str, Any]]] = {}
    for i in range(n):
        groups.setdefault(uf.find(i), []).append(records[i])
    return list(groups.values())


# ---------------------------------------------------------------------------
# Reverse geocoding for route labels (shares the cache used by /api/geocode/)
# ---------------------------------------------------------------------------

_last_geocode_ts = 0.0


def _geocode_cached(lat: float, lon: float) -> str:
    global _last_geocode_ts

    cache_key = f"geocode_{round(lat, 4)}_{round(lon, 4)}"
    cached = cache.get(cache_key)
    if cached and cached.get("address"):
        return cached["address"]

    elapsed = time.time() - _last_geocode_ts
    if elapsed < 1.0:  # Nominatim's usage policy: max 1 request/second
        time.sleep(1.0 - elapsed)
    _last_geocode_ts = time.time()

    try:
        resp = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={"format": "json", "lat": lat, "lon": lon, "zoom": 16, "addressdetails": 1},
            headers={"Accept": "application/json", "User-Agent": "LiveTracker"},
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            address = data.get("display_name")
            if address:
                cache.set(cache_key, {"success": True, "address": address, "full_data": data}, GEOCODE_CACHE_TIMEOUT)
                return address
    except requests.RequestException as e:
        logger.warning(f"Reverse geocode failed for {lat},{lon}: {e}")

    return f"{lat:.4f}, {lon:.4f}"


def _short_address(lat: float, lon: float) -> str:
    full = _geocode_cached(lat, lon)
    parts = [p.strip() for p in full.split(",")]
    return ", ".join(parts[:2]) if len(parts) >= 2 else full


def _label_route(polyline: List[List[float]]) -> str:
    if not polyline:
        return "Unknown route"
    start_lat, start_lon = polyline[0]
    end_lat, end_lon = polyline[-1]
    return f"{_short_address(start_lat, start_lon)} → {_short_address(end_lat, end_lon)}"


# ---------------------------------------------------------------------------
# Daily snapshot store
# ---------------------------------------------------------------------------
#
# The TWINS fetch_geo endpoint only retains ~1 day of GPS history (confirmed
# on both the Nagpur/eka and Ultratech/intangles fleets — a platform limit,
# not project-specific), so "the last 7 days" can't be pulled retroactively.
# Instead each day's vehicle-day records are ingested once (idempotently,
# since re-fetching an already-ingested date can't return anything new) and
# kept here; build_route_master clusters over whatever has accumulated so
# far. Run ingest daily (via compute_frequent_routes in cron) and real
# day-over-day route repetition emerges over the following days/weeks.

SNAPSHOT_TTL = 60 * 60 * 24 * 45  # keep ~45 days of daily snapshots


def _snapshot_key(spv: str, date_str: str) -> str:
    return f"route_master_snapshot:{spv.strip().upper()}:{date_str}"


def ingest_daily_snapshot(
    spv: str = "NAGPUR",
    date_str: Optional[str] = None,
    max_vehicles: Optional[int] = None,
    workers: int = 6,
    force: bool = False,
) -> int:
    """Fetch + store one day's vehicle-day path records. Returns the count stored.

    Idempotent by default: skips the fetch entirely if that date is already
    in the store, since the vendor API won't have anything new for a date
    that's already aged out of its own retention window.
    """
    vendor, spv_api = _resolve_project(spv)
    if date_str is None:
        date_str = (datetime.now(_IST).date() - timedelta(days=1)).isoformat()

    key = _snapshot_key(spv, date_str)
    if not force:
        existing = cache.get(key)
        if existing is not None:
            return len(existing)

    vehicles = get_fleet_vehicles(vendor, spv_api)
    if max_vehicles:
        vehicles = vehicles[:max_vehicles]

    records: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_reg = {
            executor.submit(fetch_vehicle_day_points, reg, date_str, vendor, spv_api): reg for reg in vehicles
        }
        for future in as_completed(future_to_reg):
            reg = future_to_reg[future]
            try:
                raw = future.result()
            except Exception as e:
                logger.warning(f"Route master ingest failed for {reg} on {date_str}: {e}")
                continue
            if not raw:
                continue
            record = build_vehicle_day_record(reg, date_str, raw)
            if record:
                records.append(record)

    cache.set(key, records, SNAPSHOT_TTL)
    logger.info(f"Route master: ingested {len(records)} vehicle-day records for {spv} on {date_str}")
    return len(records)


def _load_snapshots(spv: str, days: int) -> Tuple[List[Dict[str, Any]], List[str]]:
    today = datetime.now(_IST).date()
    dates = [(today - timedelta(days=i)).isoformat() for i in range(1, days + 1)]
    records: List[Dict[str, Any]] = []
    for d in dates:
        snapshot = cache.get(_snapshot_key(spv, d))
        if snapshot:
            records.extend(snapshot)
    return records, dates


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def build_route_master(
    spv: str = "NAGPUR",
    days: int = 7,
    max_vehicles: Optional[int] = None,
    min_occurrences: int = 3,
    jaccard_threshold: float = 0.45,
    workers: int = 6,
    force_reingest_latest: bool = False,
) -> Dict[str, Any]:
    # Make sure the most recent fetchable day is captured before clustering —
    # cheap/no-op if a cron run already ingested it today.
    ingest_daily_snapshot(spv, max_vehicles=max_vehicles, workers=workers, force=force_reingest_latest)

    records, dates = _load_snapshots(spv, days)
    days_with_snapshots = sum(1 for d in dates if cache.get(_snapshot_key(spv, d)) is not None)

    vendor, spv_api = _resolve_project(spv)
    vehicles = get_fleet_vehicles(vendor, spv_api)
    if max_vehicles:
        vehicles = vehicles[:max_vehicles]

    clusters = cluster_records(records, jaccard_threshold=jaccard_threshold)

    routes = []
    for cluster in clusters:
        if len(cluster) < min_occurrences:
            continue
        cluster.sort(key=lambda r: r["point_count"], reverse=True)
        representative = cluster[0]
        vehicle_set = sorted({r["vehicle_no"] for r in cluster})
        trips = sorted(
            (
                {
                    "vehicle_no": r["vehicle_no"],
                    "date": r["date"],
                    "start_time": r["start_time"],
                    "end_time": r["end_time"],
                    "distance_km": r["distance_km"],
                }
                for r in cluster
            ),
            key=lambda t: (t["date"], t["vehicle_no"]),
        )
        routes.append(
            {
                "route_id": hashlib.md5(representative["id"].encode()).hexdigest()[:10],
                "label": _label_route(representative["polyline"]),
                "polyline": representative["polyline"],
                "vehicle_count": len(vehicle_set),
                "trip_count": len(cluster),
                "avg_distance_km": round(sum(r["distance_km"] for r in cluster) / len(cluster), 1),
                "trips": trips,
            }
        )

    routes.sort(key=lambda r: r["trip_count"], reverse=True)

    result = {
        "spv": spv.strip().upper(),
        "generated_at": datetime.now(_IST).isoformat(),
        "days_analyzed": days,
        "days_with_snapshots": days_with_snapshots,
        "vehicles_analyzed": len(vehicles),
        "vehicle_days_with_data": len(records),
        "routes": routes,
    }
    cache.set(_cache_key(spv, days), result, CACHE_TTL)
    return result
