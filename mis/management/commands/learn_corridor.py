from django.core.management.base import BaseCommand
from datetime import datetime, timedelta
import json
import os

from mis.services.route_learning import learn_corridor


class Command(BaseCommand):
    help = "Learn corridor polylines from telemetry and write a corridor JSON file."

    def add_arguments(self, parser):
        parser.add_argument("--start", type=str, help="Start date YYYY-MM-DD (inclusive)")
        parser.add_argument("--end", type=str, help="End date YYYY-MM-DD (exclusive)")
        parser.add_argument("--days", type=int, default=14, help="If start/end missing, use last N days (default 14)")
        parser.add_argument("--epsilon-m", type=float, default=500.0, help="RDP simplify epsilon in meters (default 500)")
        parser.add_argument("--sample-step", type=int, default=5, help="Downsample every N points (default 5)")
        parser.add_argument("--min-points", type=int, default=50, help="Minimum points to produce a segment (default 50)")
        parser.add_argument("--output", type=str, help="Output path for corridor JSON. Overrides env/settings path.")

    def handle(self, *args, **opts):
        start = opts.get("start")
        end = opts.get("end")
        days = int(opts.get("days") or 14)
        eps = float(opts.get("epsilon_m") or opts.get("epsilon-m") or 500.0)
        step = int(opts.get("sample_step") or opts.get("sample-step") or 5)
        min_points = int(opts.get("min_points") or 50)
        out = opts.get("output")

        # Resolve dates
        if not start or not end:
            today = datetime.now().date()
            end_date = today + timedelta(days=1)
            start_date = end_date - timedelta(days=days)
            start = start_date.strftime("%Y-%m-%d")
            end = end_date.strftime("%Y-%m-%d")

        self.stdout.write(self.style.HTTP_INFO(f"Learning corridor from {start} to {end} (eps={eps}m, step={step})"))
        data = learn_corridor(start, end, epsilon_m=eps, sample_step=step, min_points=min_points)

        # Determine output path
        path = out
        if not path:
            # Try env/settings through the loader's defaults
            from mis.services.route_corridor import _read_config_path
            path = _read_config_path() or os.path.join(os.getcwd(), "corridor_config.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f)
        self.stdout.write(self.style.SUCCESS(f"Corridor written to {path}"))
