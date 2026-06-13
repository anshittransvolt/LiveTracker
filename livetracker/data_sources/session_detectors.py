"""
Session detection utilities for vehicle telemetry.

These functions operate on the standardized points produced by adapters in
this package. Views should call these helpers rather than re-implementing
session logic, to keep behavior consistent across data sources.
"""
from __future__ import annotations

from typing import List, Dict, Any
from datetime import datetime


def _get_ts(p: Dict[str, Any]) -> str:
    """Return primary timestamp for sorting: prefer gps_time, then last_connected, then timestamp."""
    return str(p.get('gps_time') or p.get('last_connected') or p.get('timestamp') or '')


def _parse_iso(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace('Z', '+00:00'))
    except Exception:
        return None


def _get_speed(p: Dict[str, Any]) -> float | None:
    v = p.get('speed', None)
    if v is None:
        v = p.get('gps_speed', None)
    try:
        return float(v) if v is not None else None
    except Exception:
        return None


def detect_charging_sessions(
    points: List[Dict[str, Any]],
    min_session_duration_min: float = 1.0,
) -> List[Dict[str, Any]]:
    """
    Detect charging sessions using SOC trend + speed.
    
    Logic: A vehicle is charging when:
    - Speed <= 1 km/h (stationary)
    - SOC is increasing between consecutive points
    
    This works even when vehicle_status doesn't explicitly say "Charging"
    because SOC increase is the true indicator of charging.
    
    Returns list of sessions with: start_time, end_time, start_soc, end_soc, soc_gain, duration (minutes)
    """
    import logging
    logger = logging.getLogger(__name__)
    
    pts = sorted([p for p in points if isinstance(p, dict)], key=_get_ts)
    sessions: List[Dict[str, Any]] = []
    cur: Dict[str, Any] | None = None
    
    # Debug: collect stats
    charging_points = 0
    charging_status_points = 0  # Count points where vehicle_status == 'Charging'
    
    # IMMEDIATE DEBUG LOG
    print(f"🔍 CHARGING DETECTOR: Processing {len(pts)} points")
    print(f"   Analyzing all points with vehicle_status...")
    
    # Initialize prev_soc with first valid SOC value
    prev_soc: float | None = None
    for p in pts:
        sraw = p.get('soc')
        try:
            s = float(sraw) if sraw is not None else None
        except Exception:
            s = None
        if s is not None:
            prev_soc = s
            break

    for i, p in enumerate(pts):
        ts = _get_ts(p)
        dt = _parse_iso(ts)
        
        # Get speed and SOC
        spd = _get_speed(p)
        sraw = p.get('soc')
        try:
            s = float(sraw) if sraw is not None else None
        except Exception:
            s = None
        
        # Get vehicle_status
        vehicle_status = p.get('vehicle_status', 'Unknown')
        
        # Print points where vehicle_status == 'Charging'
        if vehicle_status and 'charging' in str(vehicle_status).lower():
            charging_status_points += 1
            soc_gain = (s - prev_soc) if (s is not None and prev_soc is not None) else None
            print(f"   Point {i}: status='{vehicle_status}', speed={spd}, soc={s}, prev_soc={prev_soc}, soc_gain={soc_gain}")

        if dt is None:
            continue

        # Detect charging: stationary (speed <= 1) AND SOC increasing
        is_charging = False
        soc_gain = 0
        
        if spd is not None and spd <= 1.0 and s is not None and prev_soc is not None:
            soc_gain = s - prev_soc
            # Charging if SOC increased by at least 0.5%
            if soc_gain >= 0.5:
                is_charging = True
                charging_points += 1

        if is_charging:
            if cur is None:
                # Start new charging session
                cur = {
                    'start_time': ts,
                    'start_soc': s,
                    'end_time': ts,
                    'end_soc': s,
                    'points': 1,
                }
            else:
                # Continue charging session
                cur['end_time'] = ts
                cur['end_soc'] = s
                cur['points'] += 1
        else:
            # Not charging - finalize current session if exists
            if cur is not None:
                start_dt = _parse_iso(cur['start_time'])
                end_dt = _parse_iso(cur['end_time'])
                dur = ((end_dt - start_dt).total_seconds() / 60.0) if (start_dt and end_dt) else 0.0
                
                print(f"   ⏸️  Finalizing charging session: start_dt={start_dt}, end_dt={end_dt}, dur={dur}min")
                
                if dur >= min_session_duration_min:
                    # Calculate SOC gain
                    if cur['start_soc'] is not None and cur['end_soc'] is not None:
                        cur['soc_gain'] = cur['end_soc'] - cur['start_soc']
                    cur['duration'] = dur
                    sessions.append(cur)
                    print(f"      ✅ Session added (duration={dur}min, soc_gain={cur.get('soc_gain')}%)")
                else:
                    print(f"      ❌ Session filtered out (duration {dur}min < {min_session_duration_min}min)")
                
                cur = None
        
        # Update SOC history
        if s is not None:
            prev_soc = s

    # Finalize any open session
    if cur is not None:
        start_dt = _parse_iso(cur['start_time'])
        end_dt = _parse_iso(cur['end_time'])
        dur = ((end_dt - start_dt).total_seconds() / 60.0) if (start_dt and end_dt) else 0.0
        
        print(f"   ⏸️  Finalizing LAST charging session: start_dt={start_dt}, end_dt={end_dt}, dur={dur}min")
        
        if dur >= min_session_duration_min:
            # Calculate SOC gain
            if cur['start_soc'] is not None and cur['end_soc'] is not None:
                cur['soc_gain'] = cur['end_soc'] - cur['start_soc']
            cur['duration'] = dur
            sessions.append(cur)
            print(f"      ✅ Session added (duration={dur}min, soc_gain={cur.get('soc_gain')}%)")
        else:
            print(f"      ❌ Session filtered out (duration {dur}min < {min_session_duration_min}min)")

    # Log what we found
    print(f"   Points with 'Charging' in vehicle_status: {charging_status_points}")
    print(f"   Points detected as charging (speed<=1 AND soc_gain>=0.5): {charging_points}")
    logger.info(f"🔍 Charging detector: {charging_points} charging points found, {len(sessions)} sessions before merge")

    # Merge consecutive sessions with gap < 5 minutes
    merged_sessions: List[Dict[str, Any]] = []
    for session in sessions:
        if not merged_sessions:
            merged_sessions.append(session)
        else:
            prev = merged_sessions[-1]
            prev_end = _parse_iso(prev['end_time'])
            curr_start = _parse_iso(session['start_time'])
            
            if prev_end and curr_start:
                gap_minutes = (curr_start - prev_end).total_seconds() / 60.0
                if 0 <= gap_minutes < 5.0:
                    # Merge: extend previous session end and update duration
                    prev['end_time'] = session['end_time']
                    prev['end_soc'] = session['end_soc']
                    
                    # Recalculate SOC gain after merge
                    if prev['start_soc'] is not None and prev['end_soc'] is not None:
                        prev['soc_gain'] = prev['end_soc'] - prev['start_soc']
                    
                    # Recalculate duration after merge
                    start_dt = _parse_iso(prev['start_time'])
                    end_dt = _parse_iso(prev['end_time'])
                    prev['duration'] = ((end_dt - start_dt).total_seconds() / 60.0) if (start_dt and end_dt) else 0.0
                    prev['points'] = prev.get('points', 0) + session.get('points', 0)
                else:
                    merged_sessions.append(session)
            else:
                merged_sessions.append(session)
    
    logger.info(f"✅ Charging detector result: {len(merged_sessions)} sessions after merge")

    return merged_sessions


def detect_stoppage_sessions(
    points: List[Dict[str, Any]],
    zero_threshold: float = 0.0,
    move_threshold: float = 5.0,
) -> List[Dict[str, Any]]:
    """
    Detect stoppage sessions using speed + SOC logic.
    
    Logic: A vehicle is stopped when:
    - Speed <= 1 km/h (stationary)
    - SOC is NOT increasing (either stable or decreasing)
    
    This accurately separates charging (stationary + SOC up) from
    stopped (stationary + SOC flat/down).
    
    Returns list with: start_time, end_time, duration (minutes)
    """
    import logging
    logger = logging.getLogger(__name__)
    
    pts = sorted([p for p in points if isinstance(p, dict)], key=_get_ts)
    sessions: List[Dict[str, Any]] = []
    cur: Dict[str, Any] | None = None
    
    # Debug stats
    stop_points = 0
    stop_status_points = 0  # Count points where vehicle_status == 'Stop'
    
    # IMMEDIATE DEBUG LOG
    print(f"⏹️  STOPPAGE DETECTOR: Processing {len(pts)} points")
    print(f"   Analyzing all points with 'Stop' status...")
    
    # Initialize prev_soc with first valid SOC value
    prev_soc: float | None = None
    for p in pts:
        sraw = p.get('soc')
        try:
            s = float(sraw) if sraw is not None else None
        except Exception:
            s = None
        if s is not None:
            prev_soc = s
            break

    for i, p in enumerate(pts):
        ts = _get_ts(p)
        dt = _parse_iso(ts)
        
        # Get speed and SOC
        spd = _get_speed(p)
        sraw = p.get('soc')
        try:
            s = float(sraw) if sraw is not None else None
        except Exception:
            s = None
        
        # Get vehicle_status
        vehicle_status = p.get('vehicle_status', 'Unknown')
        
        # Print points where vehicle_status == 'Stop'
        if vehicle_status and 'stop' in str(vehicle_status).lower():
            stop_status_points += 1
            soc_change = (s - prev_soc) if (s is not None and prev_soc is not None) else None
            print(f"   Point {i}: time='{ts}', status='{vehicle_status}', speed={spd}, soc={s}, prev_soc={prev_soc}, soc_change={soc_change}")

        if dt is None:
            continue

        # Detect stoppage: stationary (speed <= 1) AND SOC NOT increasing
        is_stopped = False
        soc_change = 0
        
        if spd is not None and spd <= 1.0:
            # Vehicle is stationary
            # Check if SOC is stable or decreasing (not charging)
            if s is not None and prev_soc is not None:
                soc_change = s - prev_soc
                # Stopped if SOC decreased or stayed same (SOC_change < 0.5%)
                # Don't count as stopped if SOC is increasing (that's charging)
                if soc_change < 0.5:
                    is_stopped = True
                    stop_points += 1
            elif prev_soc is None:
                # First point, assume stopped if stationary
                is_stopped = True
                stop_points += 1

        if is_stopped:
            if cur is None:
                # Start new stoppage session
                cur = {
                    'start_time': ts,
                    'end_time': ts,
                    'points': 1,
                }
            else:
                # Continue stoppage session
                cur['end_time'] = ts
                cur['points'] += 1
        else:
            # Not stopped - finalize current session if exists
            if cur is not None:
                start_dt = _parse_iso(cur['start_time'])
                end_dt = _parse_iso(cur['end_time'])
                dur = ((end_dt - start_dt).total_seconds() / 60.0) if (start_dt and end_dt) else 0.0
                
                print(f"   ⏸️  Finalizing stoppage session: start_dt={start_dt}, end_dt={end_dt}, dur={dur}min")
                
                if dur >= 1.0:
                    cur['duration'] = dur
                    sessions.append(cur)
                    print(f"      ✅ Session added (duration={dur}min)")
                else:
                    print(f"      ❌ Session filtered out (duration {dur}min < 1.0min)")
                
                cur = None
        
        # Update SOC history
        if s is not None:
            prev_soc = s

    # Finalize any open session
    if cur is not None:
        start_dt = _parse_iso(cur['start_time'])
        end_dt = _parse_iso(cur['end_time'])
        dur = ((end_dt - start_dt).total_seconds() / 60.0) if (start_dt and end_dt) else 0.0
        
        print(f"   ⏸️  Finalizing LAST stoppage session: start_dt={start_dt}, end_dt={end_dt}, dur={dur}min")
        
        if dur >= 1.0:
            cur['duration'] = dur
            sessions.append(cur)
            print(f"      ✅ Session added (duration={dur}min)")
        else:
            print(f"      ❌ Session filtered out (duration {dur}min < 1.0min)")

    # Log what we found
    print(f"   Points with 'Stop' in vehicle_status: {stop_status_points}")
    print(f"   Points detected as stopped (speed<=1 AND soc_change<0.5): {stop_points}")
    logger.info(f"⏹️  Stoppage detector: {stop_points} stop points found, {len(sessions)} sessions before merge")

    # Merge consecutive sessions with gap < 5 minutes
    merged_sessions: List[Dict[str, Any]] = []
    for session in sessions:
        if not merged_sessions:
            merged_sessions.append(session)
        else:
            prev = merged_sessions[-1]
            prev_end = _parse_iso(prev['end_time'])
            curr_start = _parse_iso(session['start_time'])
            if prev_end and curr_start:
                gap_minutes = (curr_start - prev_end).total_seconds() / 60.0
                if gap_minutes < 5.0:
                    # Merge: extend previous session end and update duration
                    prev['end_time'] = session['end_time']
                    start_dt = _parse_iso(prev['start_time'])
                    end_dt = _parse_iso(prev['end_time'])
                    prev['duration'] = ((end_dt - start_dt).total_seconds() / 60.0) if (start_dt and end_dt) else 0.0
                    prev['points'] = prev.get('points', 0) + session.get('points', 0)
                else:
                    merged_sessions.append(session)
            else:
                merged_sessions.append(session)

    logger.info(f"✅ Stoppage detector result: {len(merged_sessions)} sessions after merge")
