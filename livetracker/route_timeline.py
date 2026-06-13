"""
Deprecated module: route_timeline

This legacy implementation has been replaced by the timebox engine.
Runtime code has been migrated to use `livetracker.timebox` exclusively.

To avoid breaking imports in any leftover scripts, we provide minimal
shim exports that delegate to `livetracker.timebox` where appropriate.
"""

import logging

logger = logging.getLogger(__name__)

try:
    from .timebox import parse_gps_location, get_geofence_status, _zone_from_phase
except Exception:
    # If timebox is unavailable for some reason, define no-op shims
    def parse_gps_location(gps_location):
        try:
            lat, lon = map(float, (gps_location or '').split(','))
            return lat, lon
        except Exception:
            return 0.0, 0.0

    def get_geofence_status(lat, lon, vehicle_status):
        return 'transit'

    def _zone_from_phase(phase: str) -> str:
        p = (phase or '').lower()
        if 'manawar' in p:
            return 'manawar'
        if 'jhulwania' in p:
            return 'jhulwania'
        if 'dhule' in p:
            return 'dhule'
        if 'maha' in p or 'mahaborder' in p or 'maha_border' in p:
            return 'maha_border'
        return 'unknown'


def process_vehicle_journey(*args, **kwargs):
    """
    Legacy entry point no longer supported. Use timebox builder instead:
    `from livetracker.timebox import build_timebox_for_vehicle`.
    """
    raise NotImplementedError("route_timeline.process_vehicle_journey has been removed. Use timebox.")


def point_in_circle(lat, lon, center_lat, center_lon, radius_m):
    try:
        return haversine_m(lat, lon, center_lat, center_lon) <= radius_m
    except Exception:
        return False


def point_in_polygon(lat, lon, polygon_points):
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

def fetch_vehicle_data(source_url):
    try:
        headers = {}
        if SMARTFASTAPI_ACCESS_KEY:
            headers['x-api-key'] = SMARTFASTAPI_ACCESS_KEY
        
        r = requests.get(source_url, headers=headers, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        raise RuntimeError(f"Failed to fetch vehicle data from {source_url}: {exc}")

def parse_gps_location(gps_location):
    lat, lon = map(float, gps_location.split(","))
    return lat, lon

def get_geofence_status(lat, lon, vehicle_status):
    s = (vehicle_status or "").lower()
    # Loading/unloading geofences
    if point_in_polygon(lat, lon, MANAWAR_LOADING_POLY):
        return 'manawar_loading'
    if point_in_circle(lat, lon, *DHULE_UNLOADING):
        return 'dhule_unloading'
    if point_in_circle(lat, lon, *MANAWAR_CHARGING):
        return 'manawar_charging' if s == 'charging' else 'manawar_yard'
    if point_in_polygon(lat, lon, JHULWANIA_CHARGING_POLY):
        return 'jhulwania_charging' if s == 'charging' else 'jhulwania_yard'
    if point_in_polygon(lat, lon, DHULE_CHARGING_POLY):
        return 'dhule_charging' if s == 'charging' else 'dhule_yard'
    if point_in_circle(lat, lon, *MAHA_BORDER):
        return 'maha_border'
    return 'transit'

def determine_direction(records):
    """
    Determine route direction based on comprehensive analysis of GPS records and historical patterns.
    Enhanced to handle both real-time GPS data and historical journey patterns.
    
    Dhar to Dhule: manawar -> jhulwania -> maha_border -> dhule
    Dhule to Dhar: dhule -> maha_border -> jhulwania -> manawar
    """
    from datetime import datetime, timedelta
    
    # Build chronologically sorted sequence with phases and directional info
    phase_timestamps = []
    
    # Process all records to get a comprehensive journey view
    for rec in records:
        try:
            lat, lon = parse_gps_location(rec.get('gps_location') or '')
            timestamp_str = rec.get('last_connected', '')
            if not timestamp_str:
                continue
            
            timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            phase = get_geofence_status(lat, lon, rec.get('vehicle_status', ''))
            zone = _zone_from_phase(phase)
            
            if zone != 'unknown':
                phase_timestamps.append((timestamp, zone, phase))
        except Exception:
            continue
    
    # If we don't have enough GPS zone data, try to infer from the data patterns
    if len(phase_timestamps) < 3:
        # Look for patterns in the raw data that might indicate direction
        recent_zones = []
        older_zones = []
        
        # Split data into recent (last 24 hours) and older
        now = datetime.now().replace(tzinfo=phase_timestamps[0][0].tzinfo if phase_timestamps else None)
        cutoff_time = now - timedelta(hours=24)
        
        for timestamp, zone, phase in phase_timestamps:
            if timestamp > cutoff_time:
                recent_zones.append(zone)
            else:
                older_zones.append(zone)
        
        # If we have historical data, use it for direction detection
        if older_zones and recent_zones:
            first_historical = older_zones[0] if older_zones else None
            last_recent = recent_zones[-1] if recent_zones else None
            
            # Strong direction indicators from historical progression
            if first_historical == 'dhule' and last_recent == 'manawar':
                return 'dhule_to_dhar'
            elif first_historical == 'manawar' and last_recent == 'dhule':
                return 'dhar_to_dhule'
        
        # If still insufficient data, return a more intelligent default
        if not phase_timestamps:
            return 'dhule_to_dhar'  # Changed from dhar_to_dhule as dhule_to_dhar seems more common
    
    # Sort by timestamp to get chronological order
    phase_timestamps.sort(key=lambda x: x[0])
    
    # Extract unique zones and look for directional transitions
    zones_visited = []
    directional_indicators = []
    
    for timestamp, zone, phase in phase_timestamps:
        # Collect unique zones
        if not zones_visited or zones_visited[-1] != zone:
            zones_visited.append(zone)
        
        # Look for directional phase indicators
        phase_lower = phase.lower()
        if 'to_' in phase_lower:
            directional_indicators.append(phase_lower)
    
    # Analyze directional indicators first (most reliable)
    dhar_direction_score = 0
    dhule_direction_score = 0
    
    for direction_phase in directional_indicators:
        # Dhar to Dhule indicators
        if 'manawar_to_jhulwania' in direction_phase or 'jhulwania_to_maha' in direction_phase or 'maha_border_to_dhule' in direction_phase:
            dhar_direction_score += 2
        # Dhule to Dhar indicators  
        elif 'dhule_to_maha' in direction_phase or 'maha_border_to_jhulwania' in direction_phase or 'jhulwania_to_manawar' in direction_phase:
            dhule_direction_score += 2
    
    # If we have strong directional indicators, use them
    if dhar_direction_score > dhule_direction_score and dhar_direction_score > 0:
        # Debug logging
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"🧭 DIRECTION: dhar_to_dhule (directional score: {dhar_direction_score} vs {dhule_direction_score}, indicators: {directional_indicators})")
        return 'dhar_to_dhule'
    elif dhule_direction_score > dhar_direction_score and dhule_direction_score > 0:
        # Debug logging
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"🧭 DIRECTION: dhule_to_dhar (directional score: {dhule_direction_score} vs {dhar_direction_score}, indicators: {directional_indicators})")
        return 'dhule_to_dhar'
    
    # Fallback to zone sequence analysis
    dhar_to_dhule_order = ['manawar', 'jhulwania', 'maha_border', 'dhule']
    dhule_to_dhar_order = ['dhule', 'maha_border', 'jhulwania', 'manawar']
    
    def calculate_sequence_score(zones, expected_order):
        if not zones:
            return 0
        
        score = 0
        last_index = -1
        
        for zone in zones:
            if zone in expected_order:
                current_index = expected_order.index(zone)
                if current_index > last_index:
                    score += 1
                    last_index = current_index
                else:
                    # Less penalty for out-of-order (vehicles can backtrack)
                    score -= 0.2
        
        # Bonus for starting/ending at correct zones
        if zones and zones[0] == expected_order[0]:
            score += 1
        if zones and len(zones) > 1 and zones[-1] == expected_order[-1]:
            score += 1
        
        return score
    
    dhar_score = calculate_sequence_score(zones_visited, dhar_to_dhule_order)
    dhule_score = calculate_sequence_score(zones_visited, dhule_to_dhar_order)
    
    # Choose direction with higher score
    if dhar_score > dhule_score:
        # Debug logging
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"🧭 DIRECTION: dhar_to_dhule (zone sequence score: {dhar_score} vs {dhule_score}, zones: {zones_visited})")
        return 'dhar_to_dhule'
    elif dhule_score > dhar_score:
        # Debug logging
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"🧭 DIRECTION: dhule_to_dhar (zone sequence score: {dhule_score} vs {dhar_score}, zones: {zones_visited})")
        return 'dhule_to_dhar'
    
    # Final tie-breaker: use first and last zones with better logic
    if zones_visited:
        first = zones_visited[0]
        last = zones_visited[-1] if len(zones_visited) > 1 else first
        
        # Strong indicators for direction
        if first == 'manawar' and last == 'dhule':
            return 'dhar_to_dhule'
        elif first == 'dhule' and last == 'manawar':
            return 'dhule_to_dhar'
        # Weaker indicators
        elif first == 'manawar':
            return 'dhar_to_dhule'
        elif first == 'dhule':
            return 'dhule_to_dhar'
        elif last == 'dhule':
            return 'dhar_to_dhule'
        elif last == 'manawar':
            return 'dhule_to_dhar'
    
    return 'dhar_to_dhule'  # Default

def determine_direction_from_timeline(timeline):
    """
    Determine direction based on processed timeline phases.
    This analyzes the sequence of phases to detect route direction.
    """
    if not timeline:
        return None
    
    # Extract zone sequence from timeline phases
    zones_in_timeline = []
    directional_phases = []
    
    for entry in timeline:
        phase = entry.get('phase', '').lower()
        
        # Extract zone
        zone = _zone_from_phase(phase)
        if zone != 'unknown' and (not zones_in_timeline or zones_in_timeline[-1] != zone):
            zones_in_timeline.append(zone)
        
        # Look for directional indicators
        if 'to_' in phase:
            directional_phases.append(phase)
    
    # Analyze directional phases
    if directional_phases:
        dhule_to_dhar_indicators = 0
        dhar_to_dhule_indicators = 0
        
        for phase in directional_phases:
            if any(pattern in phase for pattern in ['dhule_to_', 'jhulwania_to_manawar', 'maha_border_to_jhulwania']):
                dhule_to_dhar_indicators += 1
            elif any(pattern in phase for pattern in ['manawar_to_', 'jhulwania_to_maha', 'maha_border_to_dhule']):
                dhar_to_dhule_indicators += 1
        
        if dhule_to_dhar_indicators > dhar_to_dhule_indicators:
            return 'dhule_to_dhar'
        elif dhar_to_dhule_indicators > dhule_to_dhar_indicators:
            return 'dhar_to_dhule'
    
    # Analyze zone sequence
    if len(zones_in_timeline) >= 2:
        first_zone = zones_in_timeline[0]
        last_zone = zones_in_timeline[-1]
        
        # Clear direction indicators
        if first_zone == 'dhule' and last_zone == 'manawar':
            return 'dhule_to_dhar'
        elif first_zone == 'manawar' and last_zone == 'dhule':
            return 'dhar_to_dhule'
        
        # Check for route patterns
        zone_sequence_str = ' -> '.join(zones_in_timeline)
        if 'dhule' in zone_sequence_str and 'manawar' in zone_sequence_str:
            dhule_pos = zone_sequence_str.find('dhule')
            manawar_pos = zone_sequence_str.find('manawar')
            
            if dhule_pos < manawar_pos:
                return 'dhule_to_dhar'
            elif manawar_pos < dhule_pos:
                return 'dhar_to_dhule'
    
    return None

def process_vehicle_journey(vehicle_data):
    vehicle_data.sort(key=lambda x: x['last_connected'])
    timeline = []
    prev_status = None
    prev_time = None
    for rec in vehicle_data:
        try:
            lat, lon = parse_gps_location(rec.get('gps_location') or '')
        except Exception:
            # skip malformed/empty gps points
            continue
        status = get_geofence_status(lat, lon, rec['vehicle_status'])
        try:
            time = datetime.fromisoformat(rec['last_connected'].replace('Z', '+00:00'))
        except Exception:
            # skip if timestamp can't be parsed
            continue
        if prev_status is not None and status != prev_status:
            timeline.append({
                'phase': prev_status,
                'start': prev_time.isoformat(),
                'end': time.isoformat(),
                'duration_seconds': int((time - prev_time).total_seconds())
            })
            prev_time = time
            prev_status = status
        elif prev_status is None:
            prev_status = status
            prev_time = time
    # Add last phase
    if prev_status is not None and prev_time is not None:
        try:
            end_time = datetime.fromisoformat(vehicle_data[-1]['last_connected'].replace('Z', '+00:00'))
            duration = int((end_time - prev_time).total_seconds())
        except Exception:
            end_time = vehicle_data[-1].get('last_connected')
            duration = None
        timeline.append({
            'phase': prev_status,
            'start': prev_time.isoformat(),
            'end': end_time.isoformat() if isinstance(end_time, datetime) else end_time,
            'duration_seconds': duration,
        })
    direction = determine_direction(vehicle_data)
    
    # Also try timeline-based direction detection for verification
    timeline_direction = determine_direction_from_timeline(timeline)
    
    # Use timeline direction if GPS direction is uncertain
    if direction == 'dhule_to_dhar' and timeline_direction and timeline_direction != direction:
        # Cross-validate with timeline analysis
        final_direction = timeline_direction
    else:
        final_direction = direction
    
    return {'direction': final_direction, 'timeline': timeline}

def _zone_from_phase(phase: str) -> str:
    # Normalize the phase down to a zone name
    if not phase:
        return 'unknown'
    phase = phase.lower()
    if 'manawar' in phase:
        return 'manawar'
    if 'jhulwania' in phase:
        return 'jhulwania'
    if 'dhule' in phase:
        return 'dhule'
    if 'maha' in phase or 'mahaborder' in phase or 'maha_border' in phase:
        return 'maha_border'
    return 'unknown'


# Cluster definitions: unordered groups allowed at endpoints
MANAWAR_CLUSTER = {
    'manawar_loading',
    'manawar_yard',
    'manawar_charging',
}
DHULE_CLUSTER = {
    'dhule_unloading',
    'dhule_yard',
}

def canonical_units(direction: str):
    """
    Returns the canonical sequence as units where a unit is either:
    - a set of phases (unordered cluster), or
    - a string phase (single phase, including transits like "a_to_b").
    Clusters are allowed to appear in any order within the unit.
    """
    if direction == 'dhar_to_dhule':
        return [
            MANAWAR_CLUSTER,
            'manawar_to_jhulwania',
            'jhulwania_yard',
            'jhulwania_to_maha_border',
            'maha_border',
            'maha_border_to_dhule',
            DHULE_CLUSTER,
        ]
    elif direction == 'dhule_to_dhar':
        return [
            DHULE_CLUSTER,
            'dhule_to_maha_border',
            'maha_border',
            'maha_border_to_jhulwania',
            'jhulwania_yard',
            'jhulwania_to_manawar',
            MANAWAR_CLUSTER,
        ]
    # Fallback to Dhar -> Dhule if unknown
    return [
        MANAWAR_CLUSTER,
        'manawar_to_jhulwania',
        'jhulwania_yard',
        'jhulwania_to_maha_border',
        'maha_border',
        'maha_border_to_dhule',
        DHULE_CLUSTER,
    ]

def _phase_unit_index(phase: str, units: list[int]) -> int | None:
    """
    Map a timeline phase to its unit index within canonical units.
    - For clusters, any phase present in the set maps to that unit.
    - For zone-phase units like 'jhulwania_yard' or 'maha_border',
      accept any non-transit phase whose zone matches.
    - For transit units (with '_to_'), require exact match.
    Returns None if phase does not belong to any canonical unit.
    """
    if not phase:
        return None
    p = phase.lower()
    zone = _zone_from_phase(p)
    for idx, unit in enumerate(units):
        if isinstance(unit, set):
            if p in unit:
                return idx
        else:
            # Transit unit exact match
            if '_to_' in unit:
                if p == unit:
                    return idx
            else:
                # Zone-phase unit: accept any non-transit phase of that zone
                if '_to_' not in p and _zone_from_phase(p) == _zone_from_phase(unit):
                    return idx
    return None

def _enforce_sequence_cutoff(timeline, direction):
    """
    Enforce canonical unit sequence up to the pivot (latest non-transit phase).
    - Allows any order within MANAWAR_CLUSTER and DHULE_CLUSTER.
    - Drops phases that jump backward to an already passed unit.
    - Restricts to units at or before the pivot unit index.
    """
    import pytz
    from datetime import datetime

    if not timeline:
        return timeline

    ist_tz = pytz.timezone('Asia/Kolkata')
    units = canonical_units(direction)

    # Sort chronologically
    try:
        timeline.sort(key=lambda x: _parse_dt(x.get('start')) or x.get('start', ''))
    except Exception:
        pass

    # Find pivot: latest non-transit phase
    pivot_phase = None
    pivot_time = None
    for entry in timeline:
        phase = entry.get('phase', '')
        if phase and '_to_' not in phase:
            sdt = _parse_dt(entry.get('start'))
            if sdt is None:
                try:
                    sdt = datetime.fromisoformat((entry.get('start') or '').replace('Z', '+00:00')).astimezone(ist_tz)
                except Exception:
                    sdt = None
            if sdt is None:
                continue
            if pivot_time is None or sdt > pivot_time:
                pivot_phase = phase
                pivot_time = sdt

    if pivot_phase is None:
        return timeline

    pivot_idx = _phase_unit_index(pivot_phase, units)
    # If unknown, keep original timeline
    if pivot_idx is None:
        return timeline

    logger.info(f"Sequence enforcement: pivot phase={pivot_phase}, unit_idx={pivot_idx}, time={pivot_time}")

    filtered = []
    last_unit_idx = -1
    for entry in timeline:
        phase = entry.get('phase', '')
        unit_idx = _phase_unit_index(phase, units)
        if unit_idx is None:
            # Drop phases outside canonical units
            continue
        # Restrict to units at or before pivot
        if unit_idx > pivot_idx:
            continue
        # Enforce non-decreasing unit index (no backward jumps)
        if unit_idx < last_unit_idx:
            continue
        # If entry is gap-filled, ensure strictly before pivot time
        if entry.get('gap_filled'):
            sdt = _parse_dt(entry.get('start'))
            if sdt and pivot_time and not (sdt < pivot_time):
                continue
        filtered.append(entry)
        last_unit_idx = max(last_unit_idx, unit_idx)

    # Keep filtered list sorted
    try:
        filtered.sort(key=lambda x: _parse_dt(x.get('start')) or x.get('start', ''))
    except Exception:
        pass
    return filtered


def _label_transit_phases(timeline):
    # Replace generic 'transit' phase entries with descriptive labels
    # using the nearest surrounding non-transit zones.
    for i, entry in enumerate(timeline):
        if entry.get('phase') == 'transit':
            # find previous non-transit
            prev_zone = None
            for j in range(i - 1, -1, -1):
                p = timeline[j].get('phase')
                if p and p != 'transit':
                    prev_zone = _zone_from_phase(p)
                    break
            # find next non-transit
            next_zone = None
            for j in range(i + 1, len(timeline)):
                p = timeline[j].get('phase')
                if p and p != 'transit':
                    next_zone = _zone_from_phase(p)
                    break
            if prev_zone and next_zone and prev_zone != 'unknown' and next_zone != 'unknown':
                # Create properly formatted transit phase name that matches UI canonical order
                transit_phase = f"{prev_zone}_to_{next_zone}"
                entry['phase'] = transit_phase
                logger.info(f"Created transit phase: {transit_phase} (from {prev_zone} to {next_zone})")
            elif prev_zone and not next_zone:
                entry['phase'] = f"{prev_zone}_to_unknown"
                logger.info(f"Created incomplete transit: {prev_zone}_to_unknown")
            elif next_zone and not prev_zone:
                entry['phase'] = f"unknown_to_{next_zone}"
                logger.info(f"Created incomplete transit: unknown_to_{next_zone}")
            else:
                # Keep as 'transit' if we can't determine proper labeling
                entry['phase'] = 'transit'
                logger.info(f"Keeping generic transit (prev_zone={prev_zone}, next_zone={next_zone})")
    return timeline


def _format_hhmm(seconds: int | None) -> str | None:
    if seconds is None:
        return None
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes = rem // 60
    return f"{hours:02d}:{minutes:02d}"


def _parse_dt(s: str | None):
    """
    Safely parse ISO timestamp string to IST-aware datetime.
    Returns None if parsing fails.
    """
    if not s or not isinstance(s, str):
        return None
    try:
        from datetime import datetime
        import pytz
        ist_tz = pytz.timezone('Asia/Kolkata')
        return datetime.fromisoformat(s.replace('Z', '+00:00')).astimezone(ist_tz)
    except Exception:
        return None


def _cleanup_transit_same_zone(timeline):
    # Remove entries where a transit was labeled as X_to_X (same zone)
    cleaned = []
    for entry in timeline:
        phase = entry.get('phase', '')
        if isinstance(phase, str) and '_to_' in phase:
            parts = phase.split('_to_')
            if len(parts) == 2 and parts[0] == parts[1]:
                # skip same-zone transit
                continue
        cleaned.append(entry)
    return cleaned


def _remove_unknown_transits(timeline):
    # Remove entries where transit involves "unknown" zones
    cleaned = []
    for entry in timeline:
        phase = entry.get('phase', '')
        if isinstance(phase, str) and 'unknown' in phase.lower():
            # skip transits to/from unknown zones
            continue
        cleaned.append(entry)
    return cleaned


def _fill_missing_past_phases(timeline, vehicle_data, direction):
    """
    Fill missing past phases for incomplete current journeys using historical data.
    Only fills backward - not future phases. Time-respectful gap-filling WITH TIMESTAMPS.
    """
    import pytz
    from datetime import datetime, timedelta
    
    if not timeline or not direction:
        return timeline
    
    # Timezone setup
    ist_tz = pytz.timezone('Asia/Kolkata')
    current_date = datetime.now(ist_tz).date()
    
    # Get vehicle number for debugging
    vehicle_number = None
    if vehicle_data:
        vehicle_number = vehicle_data[0].get('truck_number', 'unknown')
    
    logger.info(f"Gap-fill: Processing {vehicle_number} - {len(timeline)} phases for direction {direction}")
    
    # Canonical units (with unordered clusters at endpoints)
    units = canonical_units(direction)
    
    # Find current live phase (most recent non-transit phase)
    current_live_phase = None
    current_live_time = None
    timeline_phases = set()
    first_phase_time = None
    
    for entry in timeline:
        phase = entry.get('phase', '')
        
        if phase and '_to_' not in phase:
            timeline_phases.add(phase)
            
            start_time_str = entry.get('start')
            if start_time_str:
                try:
                    start_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00')).astimezone(ist_tz)
                    
                    # Record first phase time for timestamp sequencing
                    if first_phase_time is None:
                        first_phase_time = start_time
                    
                    # Find the most recent phase (current live phase)
                    if current_live_phase is None or start_time > current_live_time:
                        current_live_phase = phase
                        current_live_time = start_time
                except Exception:
                    pass
    
    # Map pivot phase to its unit index
    pivot_unit_idx = _phase_unit_index(current_live_phase, units) if current_live_phase else None
    if not current_live_phase or pivot_unit_idx is None:
        return timeline
    
    # Consider past units (before pivot unit index)
    past_units = units[:pivot_unit_idx]

    # Helper: check if any phase exists in a unit
    def unit_has_phase(unit):
        if isinstance(unit, set):
            return any(p in unit for p in timeline_phases)
        # Zone-phase units accept any non-transit phase with same zone
        if '_to_' not in unit:
            zone_u = _zone_from_phase(unit)
            for p in timeline_phases:
                if '_to_' not in p and _zone_from_phase(p) == zone_u:
                    return True
            return False
        # Transit units handled separately
        return False

    # Compute missing past phases (exclude transit here; they'll be added later)
    missing_past_phases = []
    for unit in past_units:
        if isinstance(unit, set):
            for phase in sorted(list(unit)):
                if phase not in timeline_phases:
                    missing_past_phases.append(phase)
        else:
            if '_to_' in unit:
                # Skip transit in this step
                continue
            # For zone-phase (e.g., jhulwania_yard, maha_border), add canonical phase if none found in zone
            if not unit_has_phase(unit):
                missing_past_phases.append(unit)
    
    if not missing_past_phases:
        logger.info(f"Gap-fill {vehicle_number}: No missing past phases for {current_live_phase}")
        return timeline
    
    logger.info(f"Gap-fill {vehicle_number}: Found {len(missing_past_phases)} missing past phases: {missing_past_phases}")
    
    # Collect historical data if available (STRICTLY before current live time)
    historical_phases = {}
    if vehicle_data:
        for record in vehicle_data:
            try:
                timestamp_str = record.get('last_connected', '')
                if timestamp_str:
                    timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00')).astimezone(ist_tz)
                    # Only consider historical points strictly before the current live phase start
                    if current_live_time and timestamp >= current_live_time:
                        continue
                    
                    # Use historical data from previous days OR any available data
                    gps_data = record.get('gps_location') or ''
                    vehicle_status = record.get('vehicle_status', '')
                    
                    if gps_data:
                        try:
                            lat, lon = parse_gps_location(gps_data)
                            if lat is not None and lon is not None:
                                geofence_status = get_geofence_status(lat, lon, vehicle_status)
                                
                                if geofence_status and geofence_status not in ['transit', 'unknown']:
                                    # Store all historical occurrences, preferring most recent
                                    if geofence_status not in historical_phases or timestamp > historical_phases[geofence_status]['time']:
                                        historical_phases[geofence_status] = {
                                            'time': timestamp,
                                            'vehicle': record.get('truck_number', '')
                                        }
                                    
                                    # Also check for loading-related statuses
                                    if 'LOADING' in vehicle_status.upper():
                                        loading_phase = 'manawar_loading'  # Default loading phase
                                        if loading_phase not in historical_phases or timestamp > historical_phases[loading_phase]['time']:
                                            historical_phases[loading_phase] = {
                                                'time': timestamp,
                                                'vehicle': record.get('truck_number', '')
                                            }
                                            logger.info(f"Gap-fill: Found LOADING status for {loading_phase} at {timestamp}")
                        except Exception:
                            continue
            except Exception:
                continue
    
    # Add missing past phases using historical data
    added_count = 0
    for missing_phase in missing_past_phases:
        hist_data = None
        hist_time = None
        
        # Try direct match first
        if missing_phase in historical_phases:
            hist_data = historical_phases[missing_phase]
            hist_time = hist_data['time']
        else:
            # Try phase mapping for substitutes - improved loading detection
            phase_mapping = {
                'manawar_loading': ['manawar_yard', 'manawar_charging', 'manawar_to_jhulwania'],
                'manawar_yard': ['manawar_charging', 'manawar_loading'],
                'jhulwania_yard': ['jhulwania_charging', 'jhulwania_to_maha_border'],
                'dhule_yard': ['dhule_charging', 'dhule_unloading', 'maha_border_to_dhule'],
                'dhule_unloading': ['dhule_yard', 'dhule_charging'],
                'maha_border': ['maha_border_to_dhule', 'maha_border_to_jhulwania', 'jhulwania_to_maha_border', 'dhule_to_maha_border'],
                # Transit phases can substitute for endpoints
                'manawar_to_jhulwania': ['manawar_loading', 'manawar_yard'],
                'jhulwania_to_maha_border': ['jhulwania_yard', 'jhulwania_charging'],
                'maha_border_to_dhule': ['maha_border', 'dhule_yard'],
                'dhule_to_maha_border': ['dhule_unloading', 'dhule_yard']
            }
            
            alternatives = phase_mapping.get(missing_phase, [])
            for alt_phase in alternatives:
                if alt_phase in historical_phases:
                    hist_data = historical_phases[alt_phase]
                    hist_time = hist_data['time']
                    break
        
        if hist_data and hist_time and hist_time < current_live_time:
            # Keep actual historical timestamps showing when vehicle passed through
            end_time = hist_time + timedelta(minutes=30)
            
            # Format time display with date for yesterday's data
            time_display = hist_time.strftime('%Y-%m-%d %H:%M') if hist_time.date() < current_date else hist_time.strftime('%H:%M')
            end_time_display = end_time.strftime('%Y-%m-%d %H:%M') if end_time.date() < current_date else end_time.strftime('%H:%M')
            
            # Create gap-filled entry with actual timestamp
            gap_fill_entry = {
                'phase': missing_phase,
                'start': hist_time.isoformat(),
                'end': end_time.isoformat(),
                'duration_seconds': 1800,  # 30 minutes
                'duration_hhmm': '00:30',
                'status': 'completed_historical',
                'gap_filled': True,
                'historical': True,
                'time': time_display,
                'end_time': end_time_display
            }
            
            # Append and rely on chronological sort afterwards
            timeline.append(gap_fill_entry)
            added_count += 1
            logger.info(f"Gap-fill {vehicle_number}: Added {missing_phase} at {hist_time}")
    
    # Ensure chronological order
    try:
        timeline.sort(key=lambda x: _parse_dt(x.get('start')) or x.get('start', ''))
    except Exception:
        pass

    # Enforce canonical sequence up to pivot and drop out-of-sequence
    timeline = _enforce_sequence_cutoff(timeline, direction)

    # Add transit phases between consecutive phases (strictly past-only)
    if added_count >= 0:
        added_count += _add_missing_transits(timeline, cutoff_time=current_live_time)

    # Final prune: ensure all gap-filled entries are strictly before current live phase start
    if current_live_time:
        pruned = []
        for e in timeline:
            if e.get('gap_filled'):
                sdt = _parse_dt(e.get('start'))
                if sdt and sdt < current_live_time:
                    pruned.append(e)
                else:
                    # Drop any gap-filled entry that is not strictly in the past
                    continue
            else:
                pruned.append(e)
        timeline = pruned
    
    # Log what historical phases were available
    if not added_count and missing_past_phases:
        logger.warning(f"Gap-fill {vehicle_number}: Could not fill {missing_past_phases}. Available historical: {list(historical_phases.keys())}")
    
    logger.info(f"Gap-fill {vehicle_number}: Added {added_count} total phases (after sequence enforcement)")
    return timeline


def _add_missing_transits(timeline, cutoff_time=None):
    """
    Add missing transit phases between zones after gap-filling.
    ALWAYS fill transit phases when both source and destination zones exist.
    """
    import pytz
    from datetime import datetime, timedelta
    
    ist_tz = pytz.timezone('Asia/Kolkata')
    added_count = 0
    
    # Sort timeline by start time
    timeline.sort(key=lambda x: _parse_dt(x.get('start')) or x.get('start', ''))
    
    i = 0
    while i < len(timeline) - 1:
        current_phase = timeline[i].get('phase', '')
        next_phase = timeline[i + 1].get('phase', '')
        
        # Skip if either is already a transit phase
        if '_to_' in current_phase or '_to_' in next_phase:
            i += 1
            continue
            
        # Check if we need a transit phase
        current_zone = _zone_from_phase(current_phase)
        next_zone = _zone_from_phase(next_phase)
        
        if (current_zone != next_zone and 
            current_zone != 'unknown' and 
            next_zone != 'unknown'):
            
            transit_phase = f"{current_zone}_to_{next_zone}"
            
            try:
                current_end = timeline[i].get('end') or timeline[i].get('start')
                next_start = timeline[i + 1].get('start')
                
                if current_end and next_start:
                    current_time = datetime.fromisoformat(current_end.replace('Z', '+00:00')).astimezone(ist_tz)
                    next_time = datetime.fromisoformat(next_start.replace('Z', '+00:00')).astimezone(ist_tz)
                    
                    # Respect cutoff: only fill transits fully before cutoff_time
                    if cutoff_time is not None:
                        if not (current_time < cutoff_time and next_time <= cutoff_time):
                            i += 1
                            continue
                    
                    # ALWAYS create transit - even for small or negative gaps
                    time_diff = (next_time - current_time).total_seconds()
                    
                    if time_diff > 120:  # Gap > 2 minutes - use gap
                        transit_start = current_time + timedelta(minutes=1)
                        transit_end = next_time - timedelta(minutes=1)
                    elif time_diff > 0:  # Small positive gap
                        transit_start = current_time
                        transit_end = next_time
                    else:  # No gap or negative gap - create minimal transit
                        transit_start = current_time
                        transit_end = current_time + timedelta(minutes=30)  # Default 30 min
                        # Clamp to cutoff if provided
                        if cutoff_time is not None and transit_end > cutoff_time:
                            transit_end = min(cutoff_time, transit_start + timedelta(minutes=30))
                    
                    # Ensure minimum duration
                    if (transit_end - transit_start).total_seconds() < 60:
                        transit_end = transit_start + timedelta(minutes=30)
                    
                    transit_entry = {
                        'phase': transit_phase,
                        'start': transit_start.isoformat(),
                        'end': transit_end.isoformat(),
                        'duration_seconds': int((transit_end - transit_start).total_seconds()),
                        'duration_hhmm': _format_hhmm(int((transit_end - transit_start).total_seconds())),
                        'status': 'completed_historical',  # Blue translucent styling
                        'gap_filled': True,
                        'transit_filled': True,
                        'time': transit_start.strftime('%H:%M'),
                        'end_time': transit_end.strftime('%H:%M')
                    }
                    
                    timeline.insert(i + 1, transit_entry)
                    added_count += 1
                    logger.info(f"Gap-fill: Added transit {transit_phase} (gap: {time_diff/60:.1f} min)")
                    
                    # Skip the inserted transit phase
                    i += 2
                    continue
                else:
                    # No timing data - create basic transit
                    # Without timing, we cannot ensure past-only; skip when cutoff_time provided
                    if cutoff_time is not None:
                        i += 1
                        continue
                    else:
                        transit_entry = {
                            'phase': transit_phase,
                            'start': current_end or 'Unknown',
                            'end': next_start or 'Unknown',
                            'duration_seconds': 1800,  # 30 minutes default
                            'duration_hhmm': '30:00',
                            'status': 'completed_historical',
                            'gap_filled': True,
                            'transit_filled': True,
                            'time': 'Unknown',
                            'end_time': 'Unknown'
                        }
                        
                        timeline.insert(i + 1, transit_entry)
                        added_count += 1
                        logger.info(f"Gap-fill: Added default transit {transit_phase}")
                        
                        # Skip the inserted transit phase
                        i += 2
                        continue
            except Exception as e:
                logger.warning(f"Error creating transit {transit_phase}: {e}")
                
        i += 1
    
    return added_count


def _fill_missing_transit_phases(timeline, expected_sequence, historical_phases):
    """
    Fill missing transit phases between zones (e.g., zone_A_to_zone_B)
    when there's a gap between end of zone A and start of zone B
    """
    import pytz
    from datetime import datetime, timedelta
    
    if len(timeline) < 2:
        return 0
        
    ist_tz = pytz.timezone('Asia/Kolkata')
    added_count = 0
    
    # Sort timeline by start time to ensure proper order
    timeline.sort(key=lambda x: x.get('start', ''))
    
    # Check gaps between consecutive phases
    i = 0
    while i < len(timeline) - 1:
        current_phase = timeline[i].get('phase', '')
        next_phase = timeline[i + 1].get('phase', '')
        
        # Skip if either is already a transit phase
        if '_to_' in current_phase or '_to_' in next_phase:
            i += 1
            continue
            
        # Check if there's a zone transition that needs a transit phase
        current_zone = _zone_from_phase(current_phase)
        next_zone = _zone_from_phase(next_phase)
        
        if current_zone != next_zone and current_zone != 'unknown' and next_zone != 'unknown':
            # We need a transit phase between these zones
            transit_phase = f"{current_zone}_to_{next_zone}"
            
            # Create transit phase based on timing between the two phases
            try:
                current_end = timeline[i].get('end') or timeline[i].get('start')
                next_start = timeline[i + 1].get('start')
                
                if current_end and next_start:
                    current_time = datetime.fromisoformat(current_end.replace('Z', '+00:00')).astimezone(ist_tz)
                    next_time = datetime.fromisoformat(next_start.replace('Z', '+00:00')).astimezone(ist_tz)
                    
                    # Create transit phase in the middle
                    transit_start = current_time + timedelta(minutes=1)
                    transit_end = next_time - timedelta(minutes=1)
                    
                    if transit_start < transit_end:
                        transit_entry = {
                            'phase': transit_phase,
                            'start': transit_start.isoformat(),
                            'end': transit_end.isoformat(),
                            'duration_seconds': int((transit_end - transit_start).total_seconds()),
                            'duration_hhmm': _format_hhmm(int((transit_end - transit_start).total_seconds())),
                            'status': 'completed_historical',  # Transit gap-fill
                            'gap_filled': True,
                            'transit_filled': True,
                            'time': transit_start.strftime('%H:%M'),
                            'end_time': transit_end.strftime('%H:%M')
                        }
                        
                        timeline.insert(i + 1, transit_entry)
                        added_count += 1
                        print(f"GAP-FILL DEBUG: Added transit phase {transit_phase} between {current_phase} and {next_phase}")
                        
                        # Skip the newly inserted phase
                        i += 2
                        continue
            except Exception as e:
                print(f"GAP-FILL DEBUG: Failed to create transit phase: {e}")
                
        i += 1
        
    return added_count


def make_timeline_for_all(data):
    # Group records by vehicle_no (fall back to vehicle_id if vehicle_no is missing)
    vehicles = {}
    for row in data:
        key = row.get('vehicle_no') or str(row.get('vehicle_id'))
        vehicles.setdefault(key, []).append(row)

    results = {}
    for key, vdata in vehicles.items():
        res = process_vehicle_journey(vdata)
        # post-process timeline to label transits by surrounding zones
        timeline = _label_transit_phases(res.get('timeline', []))
        # remove same-zone transits (e.g., manawar_to_manawar)
        timeline = _cleanup_transit_same_zone(timeline)
        # remove transits involving unknown zones
        timeline = _remove_unknown_transits(timeline)
        # Fill missing past phases using historical data
        timeline = _fill_missing_past_phases(timeline, vdata, res.get('direction'))
        # add hh:mm duration and display timestamps with dates
        for t in timeline:
            t['duration_hhmm'] = _format_hhmm(t.get('duration_seconds'))
            
            # Add formatted display timestamps with date for all phases
            try:
                from datetime import datetime
                import pytz
                ist_tz = pytz.timezone('Asia/Kolkata')
                current_date = datetime.now(ist_tz).date()
                
                # Format start time
                start_str = t.get('start')
                if start_str and isinstance(start_str, str):
                    start_dt = datetime.fromisoformat(start_str.replace('Z', '+00:00')).astimezone(ist_tz)
                    # Always include date and time
                    t['display_start'] = start_dt.strftime('%Y-%m-%d %H:%M')
                    # Also keep just time for backward compatibility
                    if 'time' not in t:
                        t['time'] = start_dt.strftime('%H:%M')
                
                # Format end time  
                end_str = t.get('end')
                if end_str and isinstance(end_str, str):
                    end_dt = datetime.fromisoformat(end_str.replace('Z', '+00:00')).astimezone(ist_tz)
                    # Always include date and time
                    t['display_end'] = end_dt.strftime('%Y-%m-%d %H:%M')
                    # Also keep just time for backward compatibility
                    if 'end_time' not in t:
                        t['end_time'] = end_dt.strftime('%H:%M')
            except Exception:
                pass  # If formatting fails, continue without display timestamps
                
        res['timeline'] = timeline
        results[key] = res
    return results


def main():
    parser = argparse.ArgumentParser(description='Build TIME BOX JSON for vehicles')
    parser.add_argument('--src', default=DEFAULT_SRC_URL, help='Source URL for vehicle data (required if env SMARTFASTAPI_URL not set)')
    parser.add_argument('--out', '-o', help='Write JSON results to this file (default: test_data/route_timeline.json)')
    args = parser.parse_args()

    if not args.src:
        print(json.dumps({'error': 'Missing --src and SMARTFASTAPI_URL env not set'}))
        return 1
    try:
        data = fetch_vehicle_data(args.src)
    except Exception as exc:
        print(json.dumps({'error': str(exc)}))
        return 1
    
    results = make_timeline_for_all(data)
    
    # Default output to test_data folder if --out not provided
    output_path = args.out
    if not output_path:
        test_data_dir = os.path.join(os.path.dirname(__file__), 'test_data')
        os.makedirs(test_data_dir, exist_ok=True)
        output_path = os.path.join(test_data_dir, 'route_timeline.json')
    
    with open(output_path, 'w') as fh:
        json.dump(results, fh, indent=2, default=str)
    print(f'Wrote timeline to {output_path}')

if __name__ == "__main__":
    main()
