"""
Management command to test alert generation without touching the real API.

Injects a synthetic vehicle record straight into process_batch() so you can
verify that a specific alert type fires, throttles, and delivers notifications.

Usage examples
--------------
# Trigger an unplanned-stop alert for a test vehicle inside the Charging Point geofence:
python manage.py test_alerts

# Trigger for a real vehicle number (uses its existing VehicleState if any):
python manage.py test_alerts --vehicle MH18BZ3384

# Pick a specific pre-set scenario:
python manage.py test_alerts --scenario charging_overrun
python manage.py test_alerts --scenario unplanned_stop
python manage.py test_alerts --scenario feed_gap
python manage.py test_alerts --scenario manawar_gate_in
python manage.py test_alerts --scenario low_soc        # SOC=15%

# Pass arbitrary lat/lon:
python manage.py test_alerts --lat 22.2654 --lon 75.1270

# Reset throttle state first (so the alert definitely fires):
python manage.py test_alerts --scenario charging_overrun --reset-throttle
"""

import json
from datetime import datetime, timedelta, timezone as dt_timezone
from django.core.management.base import BaseCommand
from django.utils import timezone


# Preset scenario definitions
# Each scenario is a partial record dict + optional db_override tweaks applied
# to the VehicleState *before* processing so dwell timers are already expired.
SCENARIOS = {
    # --- Charging overrun ---
    # Vehicle is inside "Charging Point" (lat 22.265636, lon 75.127046, r=100m)
    # and has been there for 100 min (> CHARGING_OVER_SECONDS = 90 min)
    "charging_overrun": {
        "record": {
            "gps_location": "22.265636,75.127046",
            "soc": 80,
            "vehicle_status": "charging",
        },
        "db_override": {
            # pre-set inside_since + charging_start_ts far enough in the past
            "inside_since_offset_seconds": -(100 * 60),
            "charging_start_ts_offset_seconds": -(100 * 60),
            "current_geofence": "Charging Point",
        },
    },

    # --- Unplanned stop ---
    # Vehicle is outside every geofence, speed=0, stopped for 15 min
    "unplanned_stop": {
        "record": {
            "gps_location": "22.100000,75.000000",
            "soc": 60,
            "vehicle_status": "Stop",
        },
        "db_override": {
            "stop_start_ts_offset_seconds": -(15 * 60),
            "current_geofence": None,
        },
    },

    # --- Feed gap ---
    # Vehicle last connected 5 hours ago
    "feed_gap": {
        "record": {
            "gps_location": "22.265636,75.127046",
            "soc": 50,
            "vehicle_status": "Stop",
            "last_connected": (
                datetime.now(dt_timezone.utc) - timedelta(hours=5)
            ).isoformat(),
        },
        "db_override": {},
    },

    # --- Manawar gate-in ---
    # Vehicle enters "Manawar Out Area" geofence (lat 22.262448, lon 75.128085, r=50m)
    "manawar_gate_in": {
        "record": {
            "gps_location": "22.262448,75.128085",
            "soc": 70,
            "vehicle_status": "moving",
        },
        "db_override": {
            "current_geofence": None,  # was outside before
        },
    },

    # --- Low SOC (informational) ---
    "low_soc": {
        "record": {
            "gps_location": "22.265636,75.127046",
            "soc": 15,
            "vehicle_status": "Stop",
        },
        "db_override": {},
    },
}

DEFAULT_SCENARIO = "unplanned_stop"


class Command(BaseCommand):
    help = "Inject a synthetic vehicle record into process_batch() to test alert generation."

    def add_arguments(self, parser):
        parser.add_argument(
            "--vehicle",
            default="TEST_VEHICLE_001",
            help="Vehicle registration number to use (default: TEST_VEHICLE_001)",
        )
        parser.add_argument(
            "--scenario",
            choices=list(SCENARIOS.keys()),
            default=DEFAULT_SCENARIO,
            help=f"Pre-set alert scenario to trigger (default: {DEFAULT_SCENARIO})",
        )
        parser.add_argument(
            "--lat",
            type=float,
            default=None,
            help="Override GPS latitude",
        )
        parser.add_argument(
            "--lon",
            type=float,
            default=None,
            help="Override GPS longitude",
        )
        parser.add_argument(
            "--reset-throttle",
            action="store_true",
            default=False,
            help="Clear last_alert_data throttle timestamps so alerts always fire",
        )

    def handle(self, *args, **options):
        from livetracker.models import VehicleState
        from livetracker.alertService.alert_processor import process_batch

        vehicle_no = options["vehicle"]
        scenario_name = options["scenario"]
        scenario = SCENARIOS[scenario_name]

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"\n=== Alert Test: {scenario_name.upper()} | vehicle={vehicle_no} ===\n"
            )
        )

        # Build the record
        now_iso = timezone.now().isoformat()
        record = {
            "vehicle_id": vehicle_no,
            "vehicle_no": vehicle_no,
            "driver_name": f"DRI{vehicle_no}",
            "gps_location": "22.265636,75.127046",
            "soc": 50,
            "vehicle_status": "Stop",
            "last_connected": now_iso,
        }
        record.update(scenario["record"])

        # Override lat/lon if provided
        if options["lat"] is not None and options["lon"] is not None:
            record["gps_location"] = f"{options['lat']},{options['lon']}"

        self.stdout.write(f"Record: {json.dumps(record, indent=2, default=str)}")

        # Apply db_override: pre-tweak VehicleState timers so conditions are met
        db_override = scenario.get("db_override", {})
        if db_override:
            state, created = VehicleState.objects.get_or_create(
                vehicle_id=vehicle_no,
                defaults={"vehicle_no": vehicle_no, "driver_name": record["driver_name"]},
            )
            now = timezone.now()

            if "current_geofence" in db_override:
                state.current_geofence = db_override["current_geofence"]

            inside_offset = db_override.get("inside_since_offset_seconds")
            if inside_offset is not None:
                state.inside_since = now + timedelta(seconds=inside_offset)

            charging_offset = db_override.get("charging_start_ts_offset_seconds")
            if charging_offset is not None:
                state.charging_start_ts = now + timedelta(seconds=charging_offset)

            stop_offset = db_override.get("stop_start_ts_offset_seconds")
            if stop_offset is not None:
                state.stop_start_ts = now + timedelta(seconds=stop_offset)

            if options["reset_throttle"]:
                state.last_alert_data = "{}"

            state.save()
            self.stdout.write(
                self.style.WARNING(
                    f"VehicleState pre-tweaked: geofence={state.current_geofence}, "
                    f"inside_since={getattr(state, 'inside_since', 'N/A')}"
                )
            )
        elif options["reset_throttle"]:
            state, _ = VehicleState.objects.get_or_create(
                vehicle_id=vehicle_no,
                defaults={"vehicle_no": vehicle_no, "driver_name": record["driver_name"]},
            )
            state.last_alert_data = "{}"
            state.save()

        # Run the processor
        self.stdout.write("\nRunning process_batch()…\n")
        alerts = process_batch([record])

        if alerts:
            self.stdout.write(self.style.SUCCESS(f"\n✅ {len(alerts)} alert(s) generated:\n"))
            for a in alerts:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  [{a.get('alert_type', '?')}] {a.get('message') or a.get('text', '')}"
                    )
                )
        else:
            self.stdout.write(
                self.style.WARNING(
                    "\n⚠️  No alerts generated. Possible reasons:\n"
                    "  1. Alert is still throttled — use --reset-throttle to clear\n"
                    "  2. Dwell timer hasn't expired — the db_override may not match the model fields\n"
                    "  3. The scenario conditions weren't met (check geofence coords)\n"
                    "  4. MAX_ALERTS_PER_MINUTE was already reached\n"
                    "\nCheck logs and livetracker/test_data/alert_metrics.log for details."
                )
            )

        # Show current throttle state
        try:
            state = VehicleState.objects.get(vehicle_id=vehicle_no)
            if state.last_alert_data and state.last_alert_data != "{}":
                self.stdout.write(
                    f"\nCurrent throttle timestamps:\n"
                    f"{json.dumps(json.loads(state.last_alert_data), indent=2)}"
                )
        except VehicleState.DoesNotExist:
            pass
