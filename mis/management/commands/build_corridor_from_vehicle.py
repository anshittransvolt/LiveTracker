from django.core.management.base import BaseCommand
from datetime import datetime, timedelta
import json
import os
from typing import Dict, List, Tuple
import pandas as pd

from livetracker.views import fetch_day
from mis.services.geofence_processor import GeofenceProcessor
from mis.services.route_learning import _collect_segment_points, _rdp_simplify
from mis.services.route_corridor import _read_config_path


class Command(BaseCommand):
    help = "Build corridor polylines from a single vehicle's telemetry on a specific date."

    def add_arguments(self, parser):
        parser.add_argument("--vehicle", required=True, type=str, help="Vehicle number (e.g., MH18BZ2874)")
        parser.add_argument("--date", required=True, type=str, help="Date YYYY-MM-DD")
        parser.add_argument("--epsilon-m", type=float, default=150.0, help="RDP simplify epsilon in meters (default 150)")
        parser.add_argument("--sample-step", type=int, default=1, help="Downsample every N points (default 1)")
        parser.add_argument("--min-points", type=int, default=20, help="Minimum points to produce a segment (default 20)")
        parser.add_argument("--buffer-m", type=int, default=3000, help="Corridor buffer meters per segment (default 3000)")
        parser.add_argument("--output", type=str, help="Output path for corridor JSON. Overrides env/settings path.")

    def handle(self, *args, **opts):
        vehicle = opts["vehicle"]
        date_str = opts["date"]
        eps = float(opts.get("epsilon_m") or opts.get("epsilon-m") or 150.0)
        step = int(opts.get("sample_step") or opts.get("sample-step") or 1)
        min_points = int(opts.get("min_points") or 20)
        buffer_m = int(opts.get("buffer_m") or 3000)
        out = opts.get("output")

        try:
            day = datetime.strptime(date_str, "%Y-%m-%d").date()
        except Exception:
            self.stdout.write(self.style.ERROR(f"Invalid date: {date_str}"))
            return
        start = day.strftime("%Y-%m-%d")
        end = (day + timedelta(days=1)).strftime("%Y-%m-%d")

        self.stdout.write(self.style.HTTP_INFO(f"Building corridor from {vehicle} on {date_str} (eps={eps}m, step={step})"))
        data = fetch_day(vehicle, start, end) or []
        if not data:
            self.stdout.write(self.style.ERROR("No telemetry data found for given vehicle/date"))
            return

        df = pd.DataFrame.from_records(data)
        if df.empty:
            self.stdout.write(self.style.ERROR("Telemetry missing or invalid format"))
            return
        # Normalize columns expected by processors
        # Map lat/lon
        if 'lat' not in df.columns and 'latitude' in df.columns:
            df['lat'] = pd.to_numeric(df['latitude'], errors='coerce')
        if 'lon' not in df.columns and 'longitude' in df.columns:
            df['lon'] = pd.to_numeric(df['longitude'], errors='coerce')
        # Parse gps_location like "lat,lon"
        if 'lat' not in df.columns and 'gps_location' in df.columns:
            def _parse_lat(x):
                try:
                    return float(str(x).split(',')[0].strip())
                except Exception:
                    return float('nan')
            df['lat'] = df['gps_location'].map(_parse_lat)
        if 'lon' not in df.columns and 'gps_location' in df.columns:
            def _parse_lon(x):
                try:
                    return float(str(x).split(',')[1].strip())
                except Exception:
                    return float('nan')
            df['lon'] = df['gps_location'].map(_parse_lon)
        if 'last_connected' in df.columns:
            df['last_connected'] = pd.to_datetime(df['last_connected'], errors='coerce')
        elif 'gps_time' in df.columns:
            df['last_connected'] = pd.to_datetime(df['gps_time'], errors='coerce')
        else:
            self.stdout.write(self.style.ERROR("Missing timestamp column (last_connected/gps_time)"))
            return
        if 'vehicle_no' not in df.columns and 'registration_number' in df.columns:
            df['vehicle_no'] = df['registration_number']
        if 'vehicle_status' not in df.columns:
            df['vehicle_status'] = df.get('status', None)
        if 'end_odometer' not in df.columns:
            df['end_odometer'] = df.get('odometer', None)
        if 'soc' not in df.columns:
            df['soc'] = pd.NA
        df = df.sort_values("last_connected").reset_index(drop=True)

        gp = GeofenceProcessor()
        try:
            telem = gp.process_telemetry(df)
            intervals = gp.build_intervals(telem)
            visits = gp.build_cluster_visits(intervals)
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Failed to process telemetry: {e}"))
            return

        seg_pts = _collect_segment_points(intervals, visits, sample_step=step)

        def reverse_pts(pts: List[Tuple[float, float]]):
            return list(reversed(pts))

        # Merge forward + reversed of reverse segments to ensure directionality
        agg: Dict[str, List[Tuple[float, float]]] = {
            "M_J": seg_pts.get("M_J", []) or [],
            "J_D": (seg_pts.get("J_D", []) or []) + reverse_pts(seg_pts.get("D_J", []) or []),
            "D_M": (seg_pts.get("D_M", []) or []) + reverse_pts(seg_pts.get("J_M", []) or []),
        }

        segments = {}
        for key, pts in agg.items():
            if len(pts) < min_points:
                segments[key] = {"polyline": [], "buffer_m": buffer_m}
                continue
            simp = _rdp_simplify(pts, epsilon_m=eps)
            segments[key] = {"polyline": simp, "buffer_m": buffer_m}

        content = {"segments": segments}

        path = out or _read_config_path()
        if not path:
            path = os.path.join(os.getcwd(), "voltrack", "mis", "services", "corridor_config.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(content, f)
        self.stdout.write(self.style.SUCCESS(f"Corridor written to {path}"))
