import pandas as pd
from typing import List, Dict, Any
from ..alertService.alert_constants import CIRCLE_GEOFENCES
import math


def point_in_circle(lat, lng, circle):
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

def aggregate_charging_sessions(points: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Aggregate charging sessions for a vehicle.
    Each session is a dict with start_time, end_time, duration_min, geofence, points.
    Sessions are merged if gap between them is < 3 minutes and geofence is same.
    """

    print(f"[DEBUG] aggregate_charging_sessions called with {len(points) if points else 0} points")
    for i, p in enumerate(points[:5]):
        print(f"[DEBUG] Raw point {i}: {p}")
    # Parse gps_location into latitude/longitude if missing
    for p in points:
        if (not p.get('latitude') or not p.get('longitude')) and p.get('gps_location'):
            try:
                lat_str, lng_str = p['gps_location'].split(',')
                p['latitude'] = float(lat_str.strip())
                p['longitude'] = float(lng_str.strip())
            except Exception as e:
                print(f"[DEBUG] Failed to parse gps_location for point: {p.get('gps_location')}, error: {e}")
    # Filter for vehicle_status
    filtered_status = [p for p in points if str(p.get('vehicle_status', '')).strip().lower() == 'charging']
    print(f"[DEBUG] After vehicle_status filter: {len(filtered_status)} points")
    # Filter for last_connected
    filtered_time = [p for p in filtered_status if p.get('last_connected')]
    print(f"[DEBUG] After last_connected filter: {len(filtered_time)} points")
    charging_points = filtered_time
    if not charging_points:
        print("[DEBUG] No valid charging points after filtering")
        return []

    # Sort by timestamp
    charging_points.sort(key=lambda p: pd.to_datetime(p.get('last_connected')))

    sessions = []
    session = None


    i = 0
    n = len(charging_points)
    while i < n:
        p = charging_points[i]
        t = pd.to_datetime(p.get('last_connected'))
        lat = float(p.get('latitude')) if p.get('latitude') else None
        lng = float(p.get('longitude')) if p.get('longitude') else None
        soc = p.get('soc')
        geofence = get_geofence_name(lat, lng) if lat and lng else None

        if session is None:
            session = {
                'start_time': t,
                'end_time': t,
                'geofence': geofence,
                'start_soc': soc,
                'end_soc': soc,
                'points': [p]
            }
            i += 1
            continue

        prev_point = session['points'][-1]
        prev_t = pd.to_datetime(prev_point.get('last_connected'))
        gap_min = (t - prev_t).total_seconds() / 60.0
        prev_lat = float(prev_point.get('latitude')) if prev_point.get('latitude') else None
        prev_lng = float(prev_point.get('longitude')) if prev_point.get('longitude') else None
        prev_geofence = get_geofence_name(prev_lat, prev_lng) if prev_lat and prev_lng else None

        # If geofence changes or gap > 3 min, close current session
        if geofence != session['geofence'] or gap_min > 3:
            session['end_time'] = prev_t
            session['end_soc'] = prev_point.get('soc')
            session['duration_min'] = int((session['end_time'] - session['start_time']).total_seconds() / 60)
            sessions.append(session)

            # Check if next session should be merged (gap <= 3 min)
            # Look ahead to merge consecutive sessions if gap <= 3 min
            j = i
            while j < n:
                next_p = charging_points[j]
                next_t = pd.to_datetime(next_p.get('last_connected'))
                next_lat = float(next_p.get('latitude')) if next_p.get('latitude') else None
                next_lng = float(next_p.get('longitude')) if next_p.get('longitude') else None
                next_geofence = get_geofence_name(next_lat, next_lng) if next_lat and next_lng else None
                if next_geofence == geofence:
                    # Check gap from previous session end
                    gap_from_last = (next_t - prev_t).total_seconds() / 60.0
                    if 0 < gap_from_last <= 3:
                        # Merge: extend previous session
                        session['end_time'] = next_t
                        session['end_soc'] = next_p.get('soc')
                        session['duration_min'] = int((session['end_time'] - session['start_time']).total_seconds() / 60)
                        session['points'].append(next_p)
                        i = j + 1
                        prev_t = next_t
                        prev_point = next_p
                        continue
                break
            # Start new session
            session = None
            continue
        else:
            session['points'].append(p)
        i += 1

    # Close final session
    if session and session['points']:
        session['end_time'] = pd.to_datetime(session['points'][-1].get('last_connected'))
        session['end_soc'] = session['points'][-1].get('soc')
        session['duration_min'] = int((session['end_time'] - session['start_time']).total_seconds() / 60)
        sessions.append(session)

    print(f"[DEBUG] Returning {len(sessions)} charging sessions")
    return sessions


def charging_sessions_to_dataframe(sessions: List[Dict[str, Any]]) -> pd.DataFrame:
    """
    Convert charging sessions to a DataFrame for Excel export.
    """
    rows = []
    for s in sessions:
        rows.append({
            'Start Time': s.get('start_time'),
            'End Time': s.get('end_time'),
            'Duration (min)': s.get('duration_min'),
            'Geofence': s.get('geofence'),
            'Start SOC': s.get('start_soc'),
            'End SOC': s.get('end_soc'),
            'Points': len(s.get('points', []))
        })

    df = pd.DataFrame(rows)

    # Make datetime columns timezone-naive (Excel-safe)
    for col in ['Start Time', 'End Time']:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors='coerce').dt.tz_localize(None)

    return df


# -------------------------
# Example usage
# -------------------------
if __name__ == "__main__":
    # points = [...]  # your raw telemetry points here

    # sessions = aggregate_charging_sessions(points)
    # df = charging_sessions_to_dataframe(sessions)
    # df.to_excel("charging_sessions.xlsx", index=False)

    pass
