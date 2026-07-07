"""Main batch processor - orchestrates vehicle record processing.

This module is the entry point for alert generation. It:
1. Loads or creates VehicleState records
2. Delegates all checks to the checks module
3. Handles feed-gap detection for stale vehicles
4. Returns generated alert data (NOT saved to DB)

All business logic is delegated to livetracker.alertService.checks module.

Notification Flow (via create_alert_row):
Alerts are sent directly to notification channels (NO DATABASE SAVE):
1. LiveNotif: Real-time toast notification sent to UI
2. Telegram: Message sent to Telegram chat
3. Webhook: Alert posted to external webhook endpoint
"""

from typing import Optional, Tuple
from django.utils import timezone
from datetime import timedelta
from django.db import transaction
from livetracker.models import VehicleState
from livetracker.alertService.alert_checks import process_vehicle_record
from livetracker.alertService.alert_creation import create_alert_row
from livetracker.alertService.alert_constants import FEED_GAP_SECONDS
import dateutil.parser
import json
import os
from collections import defaultdict
import logging

# Global rate limiter: max alerts per minute to prevent alert storms
MAX_ALERTS_PER_MINUTE = 20  # Maximum total alerts allowed per processing cycle (reduced from 50)
logger = logging.getLogger(__name__)

# Throttle intervals in seconds per alert type
# Prevents alert spam by enforcing minimum time between same alert types for same vehicle
THROTTLE_INTERVALS = {
    # Critical alerts
    'data_feed_gap': 43200,             # 12 hours - device offline
    'low_battery': 1800,                # 30 minutes
    'critical_low_battery': 1800,       # 30 minutes

    # Gate / arrival events - once per trip (2h cooldown survives restarts)
    'gate_in_manawar': 7200,            # 2 hours
    'gate_out_manawar': 7200,           # 2 hours
    'arrival_dabhashi': 7200,           # 2 hours
    'arrival_dharampuri': 7200,         # 2 hours
    
    # Operational alerts - 30 min throttle
    'unplanned_stop': 1800,             # 30 minutes
    'charging_overrun': 1800,           # 30 minutes
    'charging_full_stuck': 1800,        # 30 minutes
    'route_deviation': 1800,            # 30 minutes
    
    # Geofence dwell alerts - 30 min throttle
    'charging_dwell': 1800,             # 30 minutes
    'loading_dwell': 1800,              # 30 minutes
    'weighing_dwell': 1800,             # 30 minutes
    'tarpaulin_dwell': 1800,            # 30 minutes
    'maha_border_dwell': 1800,          # 30 minutes
    'unloading_dwell': 1800,            # 30 minutes
    
    # Transit SLA alerts
    'transit_too_slow': 1800,           # 30 minutes
    'transit_too_fast': 1800,           # 30 minutes
    
    # Default for unlisted alert types - 30 min throttle
    'default': 1800,                    # 30 minutes
}

def should_throttle_alert(state: VehicleState, alert_type: str, now_ts) -> bool:
    """
    Check if alert should be throttled based on last sent time.
    Uses state.last_alert_data JSON field to track per-alert-type timestamps.
    
    Args:
        state: VehicleState object
        alert_type: Type of alert (e.g., 'data_feed_gap', 'unplanned_stop')
        now_ts: Current timestamp
        
    Returns:
        True if alert should be suppressed (throttled), False otherwise
    """
    # Get throttle interval for this alert type, or use default
    interval = THROTTLE_INTERVALS.get(alert_type, THROTTLE_INTERVALS.get('default', 600))
    
    # Parse last_alert_data JSON (stores {alert_type: timestamp_iso})
    try:
        last_alerts = json.loads(state.last_alert_data) if state.last_alert_data else {}
    except (json.JSONDecodeError, TypeError):
        last_alerts = {}
    
    last_sent_iso = last_alerts.get(alert_type)
    if not last_sent_iso:
        return False  # Never sent before, don't throttle
    
    try:
        last_sent = timezone.datetime.fromisoformat(last_sent_iso)
        elapsed = (now_ts - last_sent).total_seconds()
        return elapsed < interval
    except (ValueError, TypeError):
        return False  # Invalid timestamp, don't throttle

def update_alert_timestamp(state: VehicleState, alert_type: str, now_ts):
    """
    Update the last sent timestamp for a specific alert type.
    """
    try:
        last_alerts = json.loads(state.last_alert_data) if state.last_alert_data else {}
    except (json.JSONDecodeError, TypeError):
        last_alerts = {}
    
    last_alerts[alert_type] = now_ts.isoformat()
    state.last_alert_data = json.dumps(last_alerts)
    state.save()


def log_alert_counts(alerts_generated: list, throttled_counts: dict):
    """
    Log alert generation statistics per minute by alert type.
    Creates/appends to test_data/alert_metrics.log
    """
    # Count alerts by type
    alert_counts = defaultdict(int)
    for alert in alerts_generated:
        # All alerts are now dicts (no longer VehicleAlert model instances)
        alert_type = alert.get('alert_type', 'unknown')
        alert_counts[alert_type] += 1
    
    # Prepare log directory and file
    log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'test_data')
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, 'alert_metrics.log')
    
    # Create log entry
    timestamp = timezone.now().strftime('%Y-%m-%d %H:%M:%S')
    total_generated = len(alerts_generated)
    total_throttled = sum(throttled_counts.values())
    
    log_entry_lines = [
        f"\n{'='*70}",
        f"Timestamp: {timestamp}",
        f"Total Alerts Generated: {total_generated}",
        f"Total Alerts Throttled: {total_throttled}",
        f"\nGenerated by Type:"
    ]
    
    # Add counts per alert type
    for alert_type in sorted(alert_counts.keys()):
        count = alert_counts[alert_type]
        log_entry_lines.append(f"  - {alert_type}: {count}")
    
    if throttled_counts:
        log_entry_lines.append(f"\nThrottled by Type:")
        for alert_type in sorted(throttled_counts.keys()):
            count = throttled_counts[alert_type]
            log_entry_lines.append(f"  - {alert_type}: {count}")
    
    log_entry_lines.append(f"{'='*70}\n")
    
    # Write to log file
    with open(log_file, 'a') as f:
        f.write('\n'.join(log_entry_lines))
    
    return log_file


@transaction.atomic
def process_batch(records: list, spv: str = None) -> list:
    """
    Main batch processor entry point.

    For each record:
    1. Load or create VehicleState
    2. Call checks.process_vehicle_record() to handle all logic
    3. Save updated state

    After batch processing:
    4. Detect feed-gap for vehicles not in this batch

    Rate Limiting:
    - Stops processing after MAX_ALERTS_PER_MINUTE to prevent alert storms
    - Logs warning when limit is reached

    Args:
        records: List of vehicle records from API
        spv: SPV/project identifier for alert tagging

    Returns:
        List of alert dicts for UI consumption
    """
    alerts_generated = []
    throttled_counts = defaultdict(int)  # Track throttled alerts by type

    for record in records:
        # Global rate limiter: stop if we've hit the max alerts per cycle
        if len(alerts_generated) >= MAX_ALERTS_PER_MINUTE:
            break

        vehicle_id = record.get("vehicle_id")

        # Load or create state
        state, created = VehicleState.objects.get_or_create(
            vehicle_id=vehicle_id,
            defaults={
                "vehicle_no": record.get("vehicle_no"),
                "driver_name": record.get("driver_name"),
                "last_lat": None,
                "last_lon": None,
                "last_soc": None,
                "last_status": None,
                "last_connected": None,
            },
        )

        # Process record: all checks and state updates happen here
        process_vehicle_record(state, record, alerts_generated, throttled_counts, spv=spv)

        # Save updated state
        state.save()

    # ===== FEED-GAP DETECTION =====
    # DISABLED: Data feed gap alerts are not sent out
    # Uncomment below to re-enable feed gap detection
    """
    threshold_time = timezone.now() - timedelta(seconds=FEED_GAP_SECONDS)
    stale_states = VehicleState.objects.filter(last_connected__lt=threshold_time)

    now_ts = timezone.now()
    for state in stale_states:
        # Global rate limiter check
        if len(alerts_generated) >= MAX_ALERTS_PER_MINUTE:
            logger.warning(
                f"⚠️ Alert limit reached during feed-gap detection. "
                f"Skipping remaining {stale_states.count()} stale vehicles."
            )
            break
        
        # Check throttling before generating alert
        if should_throttle_alert(state, 'data_feed_gap', now_ts):
            throttled_counts['data_feed_gap'] += 1
            continue
        
        gps_loc = (
            f"{state.last_lat},{state.last_lon}"
            if state.last_lat and state.last_lon
            else ""
        )
        last_conn_iso = (
            state.last_connected.isoformat() if state.last_connected else "unknown"
        )
        text = f"{state.vehicle_no}  — Data feed gap. Last connected at {last_conn_iso}"
        a = create_alert_row(
            state.vehicle_id,
            state.vehicle_no,
            state.driver_name,
            gps_loc,
            None,
            state.last_lat,
            state.last_lon,
            state.last_soc,
            "data_feed_gap",
            text,
            context={"last_connected": last_conn_iso},
        )
        alerts_generated.append(a)
        
        # Update throttling timestamp
        update_alert_timestamp(state, 'data_feed_gap', now_ts)
        state.last_alert_ts = now_ts
        state.save()
    """

    # All alerts are already dicts (no DB models anymore)
    # Just return them directly for UI consumption
    
    # Log alert metrics to file
    log_alert_counts(alerts_generated, throttled_counts)

    return alerts_generated
