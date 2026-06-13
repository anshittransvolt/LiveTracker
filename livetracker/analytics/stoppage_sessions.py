import pandas as pd
from ..alertService.alert_constants import CIRCLE_GEOFENCES
import math
from typing import List, Dict, Any
from datetime import datetime, timedelta

def aggregate_stoppage_sessions(points: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    # Parse gps_location into latitude/longitude if missing
    for p in points:
        if (not p.get('latitude') or not p.get('longitude')) and p.get('gps_location'):
            try:
                lat_str, lng_str = p['gps_location'].split(',')
                p['latitude'] = float(lat_str.strip())
                p['longitude'] = float(lng_str.strip())
            except Exception as e:
                print(f"[DEBUG] Failed to parse gps_location for point: {p.get('gps_location')}, error: {e}")
        # Add a unified time field with fallback logic
        p['__stoppage_time'] = p.get('last_connected') or p.get('gps_time') or p.get('timestamp')
    print(f"[DEBUG] aggregate_stoppage_sessions called with {len(points) if points else 0} points")
    for i, p in enumerate(points[:5]):
        print(f"[DEBUG] Raw point {i}: {p}")
    # Filter for vehicle_status
    filtered_status = [p for p in points if str(p.get('vehicle_status', '')).strip().lower() in ('stop', 'stopped')]
    print(f"[DEBUG] After vehicle_status filter: {len(filtered_status)} points")
    # Filter for lat/lng/time
    filtered_latlng = [p for p in filtered_status if p.get('latitude') and p.get('longitude') and p.get('__stoppage_time')]
    print(f"[DEBUG] After lat/lng/time filter: {len(filtered_latlng)} points")
    # Use filtered_latlng for further processing
    stoppage_points = filtered_latlng
    # Use heatmap logic: group by lat/lng, use last_connected, only stoppages > 5 min, ignore geofence
    if not points:
        return []
    stoppage_points = [p for p in points if str(p.get('vehicle_status', '')).strip().lower() in ('stop', 'stopped') and p.get('last_connected') and p.get('latitude') and p.get('longitude')]
    print(f"[DEBUG] Filtered to {len(stoppage_points)} stoppage points with lat/lng and last_connected")
    # Sort by time
    stoppage_points.sort(key=lambda p: pd.to_datetime(p.get('__stoppage_time')))
    sessions = []
    session = None
    def point_in_circle(lat, lng, circle):
        # Haversine formula for distance in meters
        R = 6371000
        lat1 = math.radians(lat)
        lng1 = math.radians(lng)
        lat2 = math.radians(circle[1])
        lng2 = math.radians(circle[2])
        dlat = lat2 - lat1
        dlng = lng2 - lng1
        a = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlng/2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        d = R * c
        return d <= circle[3]

    MANAWAR_GEOFENCE_SET = {"Tarpulien", "Charging Point", "Loading Area", "Weighing Area"}
    def get_geofence_name(lat, lng):
        for name, clat, clng, radius in CIRCLE_GEOFENCES:
            if point_in_circle(lat, lng, (name, clat, clng, radius)):
                if name in MANAWAR_GEOFENCE_SET:
                    return f"Manawar {name}"
                return name
        return None

    for p in stoppage_points:
        t = pd.to_datetime(p.get('__stoppage_time'))
        lat = float(p.get('latitude'))
        lng = float(p.get('longitude'))
        # Group by consecutive points at same location (within ~0.001 deg)
        if not session:
            session = {
                'start_time': t,
                'end_time': t,
                'lat': lat,
                'lng': lng,
                'points': [p]
            }
            continue
        prev = session['points'][-1]
        prev_t = pd.to_datetime(prev.get('__stoppage_time'))
        prev_lat = float(prev.get('latitude'))
        prev_lng = float(prev.get('longitude'))
        # Only split session when location changes (by >0.001 deg), ignore time gap
        if abs(lat - session['lat']) > 0.001 or abs(lng - session['lng']) > 0.001:
            session['end_time'] = prev_t
            duration_min = int((session['end_time'] - session['start_time']).total_seconds() / 60)
            if duration_min > 5:
                session['duration_min'] = duration_min
                # Determine geofence and unplanned
                geofence_name = get_geofence_name(session['lat'], session['lng'])
                session['geofence'] = geofence_name
                session['is_unplanned'] = not bool(geofence_name)
                sessions.append(session)
                print(f"[DEBUG] Created stoppage session: start={session['start_time']}, end={session['end_time']}, duration={duration_min} min, lat={session['lat']}, lng={session['lng']}, geofence={geofence_name}, unplanned={not bool(geofence_name)}, points={len(session['points'])}")
            session = {
                'start_time': t,
                'end_time': t,
                'lat': lat,
                'lng': lng,
                'points': [p]
            }
        else:
            session['points'].append(p)
    # Push last session
    if session and session['points']:
        session['end_time'] = pd.to_datetime(session['points'][-1].get('__stoppage_time'))
        duration_min = int((session['end_time'] - session['start_time']).total_seconds() / 60)
        if duration_min > 5:
            session['duration_min'] = duration_min
            geofence_name = get_geofence_name(session['lat'], session['lng'])
            session['geofence'] = geofence_name
            session['is_unplanned'] = not bool(geofence_name)
            sessions.append(session)
            print(f"[DEBUG] Created stoppage session: start={session['start_time']}, end={session['end_time']}, duration={duration_min} min, lat={session['lat']}, lng={session['lng']}, geofence={geofence_name}, unplanned={not bool(geofence_name)}, points={len(session['points'])}")
    print(f"[DEBUG] Returning {len(sessions)} stoppage sessions")
    return sessions


def stoppage_sessions_to_dataframe(sessions: List[Dict[str, Any]]) -> pd.DataFrame:
    """
    Convert stoppage sessions to a DataFrame for Excel export.
    """
    rows = []
    for s in sessions:
        rows.append({
            'Start Time': s['start_time'],
            'End Time': s['end_time'],
            'Duration (min)': s['duration_min'],
            'Geofence': s['geofence'],
            'Unplanned': s['is_unplanned'],
            'Latitude': s.get('lat'),
            'Longitude': s.get('lng'),
            'Points': len(s['points'])
        })
    df = pd.DataFrame(rows)
    # Make all datetime columns timezone-naive
    for col in ['Start Time', 'End Time']:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col]).dt.tz_localize(None)
    return df
    return pd.DataFrame(rows)
