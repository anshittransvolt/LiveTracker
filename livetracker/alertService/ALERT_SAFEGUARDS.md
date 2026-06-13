# Alert System Safeguards

This document describes all the mechanisms in place to prevent alert spam and manage alert frequency.

## Overview

The alert system has **4 layers of protection** against spam:

1. ✅ **Per-Alert-Type Throttling** - Rate limits per alert category
2. ✅ **Global Rate Limiting** - System-wide alert cap per cycle
3. ✅ **Deduplication** - Prevents identical alerts
4. ✅ **Debouncing** - Filters GPS noise and transient conditions

---

## 1. Per-Alert-Type Throttling

Each alert type has its own cooldown period. Once an alert is sent for a vehicle, the same alert type won't trigger again until the cooldown expires.

**Configuration** (`alert_processor.py`):

```python
THROTTLE_INTERVALS = {
    # Critical alerts - lower frequency
    'data_feed_gap': 3600,              # 1 hour - device offline
    'low_battery': 1800,                # 30 minutes
    'critical_low_battery': 900,        # 15 minutes
    
    # Operational alerts - medium frequency
    'unplanned_stop': 600,              # 10 minutes
    'charging_overrun': 900,            # 15 minutes
    'charging_full_stuck': 600,         # 10 minutes
    'route_deviation': 600,             # 10 minutes
    
    # Geofence dwell alerts - higher frequency allowed
    'charging_dwell': 1800,             # 30 minutes
    'loading_dwell': 1800,              # 30 minutes
    'weighing_dwell': 900,              # 15 minutes
    'tarpaulin_dwell': 900,             # 15 minutes
    'maha_border_dwell': 1800,          # 30 minutes
    'unloading_dwell': 1800,            # 30 minutes
    
    # Transit SLA alerts - once per trip
    'transit_too_slow': 3600,           # 1 hour
    'transit_too_fast': 3600,           # 1 hour
    
    # Default for unlisted alert types
    'default': 600,                     # 10 minutes
}
```

**How It Works**:
- System tracks last sent time per alert type per vehicle
- Stored in `VehicleState.last_alert_data` as JSON: `{"alert_type": "timestamp"}`
- Before sending alert, checks if cooldown period has elapsed
- If still in cooldown, alert is suppressed and logged as "throttled"

**Example**:
- Vehicle MH18BZ3384 triggers "unplanned_stop" at 10:00 AM
- Alert is sent successfully
- Vehicle triggers same alert again at 10:05 AM
- Alert is **suppressed** (only 5 min elapsed, needs 10 min)
- Vehicle triggers same alert at 10:15 AM
- Alert is **sent** (10+ min elapsed)

---

## 2. Global Rate Limiting

Prevents alert storms by capping total alerts per processing cycle (every 60 seconds).

**Configuration** (`alert_processor.py`):

```python
MAX_ALERTS_PER_MINUTE = 50  # Maximum total alerts per cycle
```

**How It Works**:
- During each batch processing cycle, counts total alerts generated
- Once `MAX_ALERTS_PER_MINUTE` is reached, stops processing remaining records
- Logs warning with details about remaining unprocessed vehicles
- Protects notification channels (Telegram, LiveNotif, Webhook) from overload

**Example**:
- System receives 100 vehicle records
- First 20 vehicles trigger 50 alerts (limit reached)
- Remaining 80 vehicles are **not processed** in this cycle
- Next cycle (60 seconds later) will process them
- Warning logged: "⚠️ Alert storm detected: 50 alerts generated. Stopping processing..."

---

## 3. Deduplication System

Prevents sending identical alerts for unchanged conditions.

**Implementation**:
- Uses `VehicleState.last_alert_data` JSON field
- Tracks: `{"alert_type": "last_sent_timestamp_iso"}`
- Before creating alert, checks:
  1. Has this alert type been sent for this vehicle?
  2. Has enough time passed since last send? (throttle interval)
  3. Has the underlying condition changed? (state comparison)

**State Tracking**:
Each vehicle maintains persistent state:
- Current geofence
- Inside/outside timestamps
- Charging start time
- Stop start time
- Departure time
- Last alert timestamp

**Example**:
- Vehicle stuck in "Charging" geofence for 2 hours
- First alert sent at 10:00 AM: "Charging dwell exceeded"
- Vehicle still in same geofence at 10:15 AM
- Alert **suppressed** - same state, throttle period not elapsed
- Vehicle finally leaves at 11:00 AM, then returns at 11:30 AM
- New dwell starts - fresh condition, new alert can be sent

---

## 4. Debouncing (GPS Noise Filtering)

Prevents alerts from GPS jitter and brief transient conditions.

**Configuration** (`alert_constants.py`):

```python
DEBOUNCE_SECONDS = 60  # Vehicle must be in state for 60s before alert
```

**How It Works**:
- Geofence entry/exit tracked with `inside_since` / `outside_since` timestamps
- Alert only fires after vehicle has been in condition for full debounce period
- Filters out:
  - GPS coordinate drift near geofence boundaries
  - Brief stops (< 60s)
  - Momentary status changes

**Example - Geofence Entry**:
```
10:00:00 - Vehicle enters "Loading Area" → inside_since = 10:00:00
10:00:30 - GPS glitch shows outside → inside_since reset to None
10:00:35 - GPS back inside → inside_since = 10:00:35 (restarted)
10:01:40 - 60+ seconds elapsed → Loading dwell check activates
```

**Example - Unplanned Stop**:
```python
UNPLANNED_STOP_SECONDS = 10 * 60  # 10 minutes
```
- Vehicle must be stopped for 10 full minutes before alert
- Brief traffic stops won't trigger alerts

---

## Alert Metrics Logging

System logs detailed metrics for monitoring and debugging.

**Log Location**: `livetracker/test_data/alert_metrics.log`

**Log Format**:
```
======================================================================
Timestamp: 2026-01-20 15:30:45
Total Alerts Generated: 12
Total Alerts Throttled: 45

Generated by Type:
  - charging_dwell: 3
  - data_feed_gap: 5
  - unplanned_stop: 4

Throttled by Type:
  - charging_dwell: 20
  - data_feed_gap: 15
  - unplanned_stop: 10
======================================================================
```

**Metrics Tracked**:
- Total alerts sent
- Total alerts suppressed (throttled)
- Breakdown by alert type
- Timestamp for trend analysis

**Use Cases**:
- Monitor alert volume over time
- Identify frequently triggered alerts
- Detect alert storms
- Tune throttle intervals

---

## Adjusting Thresholds

### To Reduce Alert Frequency:
1. **Increase throttle intervals** in `THROTTLE_INTERVALS`
2. **Decrease MAX_ALERTS_PER_MINUTE** for stricter global limit
3. **Increase DEBOUNCE_SECONDS** for longer validation periods

### To Increase Alert Sensitivity:
1. **Decrease throttle intervals** (minimum 300s recommended)
2. **Increase MAX_ALERTS_PER_MINUTE** (be careful with notification channels)
3. **Decrease condition thresholds** (e.g., `CHARGING_OVER_SECONDS`)

### Example: Make Charging Alerts Less Frequent
```python
# In alert_processor.py
THROTTLE_INTERVALS = {
    'charging_dwell': 3600,  # Change from 30min to 1 hour
}

# In alert_constants.py
CHARGING_OVER_SECONDS = 120 * 60  # Change from 90min to 2 hours
```

---

## Testing Alert Safeguards

### View Throttled Alerts
Check the metrics log:
```bash
tail -f /home/anshit/voltrack_new/voltrack/livetracker/test_data/alert_metrics.log
```

### Query Alert Timestamps
```python
from livetracker.models import VehicleState
import json

# Check throttle data for a vehicle
state = VehicleState.objects.get(vehicle_no="MH18BZ3384")
print(json.loads(state.last_alert_data))
# Output: {"data_feed_gap": "2026-01-20T10:30:00+05:30", ...}
```

### Simulate Alert Storm
Temporarily set `MAX_ALERTS_PER_MINUTE = 5` to test rate limiting.

---

## Summary

| Protection Layer | Purpose | Configuration |
|-----------------|---------|---------------|
| **Throttling** | Prevent same alert spam per vehicle | `THROTTLE_INTERVALS` (600-3600s) |
| **Global Limit** | Prevent system-wide alert storms | `MAX_ALERTS_PER_MINUTE` (50) |
| **Deduplication** | Suppress unchanged conditions | `VehicleState.last_alert_data` |
| **Debouncing** | Filter GPS noise | `DEBOUNCE_SECONDS` (60s) |

All 4 layers work together to ensure **reliable, non-spammy alerts** while still catching critical events.
