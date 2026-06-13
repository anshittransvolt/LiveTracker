# Alert Service Integration Guide

This guide explains how to set up and use the alert monitoring service for vehicle tracking.

## Overview

The alert service fetches vehicle data from the API every 60 seconds, processes it through geofence and status rules, and generates alerts based on various conditions like:
- Charging overruns
- Unplanned stops
- Data feed gaps
- Loading/unloading dwell times
- Transit SLA violations
- And more...

## Setup Instructions

### 1. Install Dependencies

Make sure you have the required Python packages:

```bash
pip install requests python-dateutil
```

### 2. Run Database Migrations

The models have been updated with new fields. Run migrations to update your database:

```bash
cd /home/parth/testlive/dev_folder
python manage.py makemigrations livetracker
python manage.py migrate livetracker
```

### 3. Get Your API Key

You'll need an API key to authenticate with the smartfastapi at:
`https://smartfastapi.transvolt.org/vehicleiplt`

### 4. Start the Alert Service

There are two ways to run the alert service:

#### Option A: Using Django Management Command (Recommended)

```bash
# Using command line argument
python manage.py run_alert_service --token YOUR_API_KEY_HERE

# Or using environment variable
export SMARTFASTAPI_ACCESS_KEY="YOUR_API_KEY_HERE"
python manage.py run_alert_service
```

#### Option B: Running Directly in Python

```python
from livetracker.alertService.alert import alertService

# Initialize with your API key
api_key = "YOUR_API_KEY_HERE"
service = alertService(api_key)

# Start monitoring (runs every 60 seconds)
service.start_monitoring()

# Keep running (or do other work)
# Press Ctrl+C to stop

# To stop programmatically:
# service.stop_monitoring()
```

### 5. Start Django Server

In a separate terminal, run the Django development server:

```bash
cd /home/parth/testlive/dev_folder
python manage.py runserver
```

### 6. View Alerts in the Frontend

Once both services are running:
1. Open your browser to `http://127.0.0.1:8000/livetracker/`
2. Alerts will automatically appear as toast notifications in the top-right corner
3. Alerts are checked every 30 seconds from the frontend

## API Endpoints

### Get Recent Alerts
```
GET /livetracker/api/alerts/?minutes=5
```

Returns alerts from the last 5 minutes (or specify a different number).

Response:
```json
{
  "success": true,
  "count": 2,
  "alerts": [
    {
      "id": 1,
      "vehicle_id": "MH18BZ3380",
      "vehicle_no": "MH 18 BZ 3380",
      "driver_name": "DRIMH18BZ3380",
      "geofence_name": "Charging Point",
      "gps_location": "21.86668,75.20319",
      "lat": 21.86668,
      "lon": 75.20319,
      "soc": 99,
      "alert_type": "charging_overrun",
      "text": "[ALERT] MH 18 BZ 3380 (DRIMH18BZ3380) — Charging at Charging Point > 90 min",
      "created_at": "2025-11-12T10:30:00+05:30"
    }
  ]
}
```

### Mark Alert as Seen
```
POST /livetracker/api/alerts/<alert_id>/seen/
```

## Alert Types

The system generates the following types of alerts:

1. **charging_overrun** - Vehicle charging for more than 90 minutes
2. **soc_100_stuck** - Vehicle at 100% SOC for more than 5 minutes
3. **unplanned_stop_outside_geofence** - Vehicle stopped outside any geofence for 10+ minutes
4. **data_feed_gap** - No data received for 3+ minutes
5. **tare_weight_overrun** - Tare weighing taking more than 5 minutes
6. **gross_weight_overrun** - Gross weighing taking more than 10 minutes
7. **loading_overrun** - Loading taking more than 20 minutes
8. **tarpaulin_overrun** - Tarpaulin work taking more than 10 minutes
9. **maha_border_dwell** - Stuck at Maha Border for 45+ minutes
10. **unloading_overrun** - Unloading taking more than 15 minutes
11. **gate_in_manawar** - Vehicle entered Manawar gate (info)
12. **gate_out_manawar** - Vehicle exited Manawar gate (info)
13. **transit_sla_violation** - Transit time outside SLA bounds

## Configuration

### Geofences

Geofences are defined in `/livetracker/alertService/alert_utils.py`:
- **Circle geofences**: Define by center coordinates and radius
- **Polygon geofences**: Define by list of coordinate points

### Time Thresholds

Alert timing thresholds can be adjusted in `alert_utils.py`:
```python
DEBOUNCE_SECONDS = 60
FEED_GAP_SECONDS = 180
UNPLANNED_STOP_SECONDS = 600  # 10 mins
CHARGING_OVER_SECONDS = 5400  # 90 mins
# ... and more
```

### API Polling Interval

The alert service fetches data every 60 seconds (configurable in `alert.py`):
```python
time.sleep(60)  # Wait for 60 seconds before next fetch
```

The frontend polls for new alerts every 30 seconds (configurable in `alert_monitor.js`):
```javascript
window.alertMonitor = new AlertMonitor(30000); // 30 seconds
```

## Data Format

The API should return data in this format:

```json
[
  {
    "vehicle_no": "MH18BZ3380",
    "end_odometer": "4772.023",
    "start_odometer": "4770.981",
    "soc": "99",
    "battery_temp": 29,
    "battery_voltage": "631.3",
    "gps_speed": "29.9",
    "gps_location": "21.86668,75.20319",
    "vehicle_status": "Offline",
    "lat": 21.86668,
    "lng": 75.20319,
    "last_connected": "08-10-2025 18:57"
  }
]
```

The service automatically transforms this to the internal format.

## Troubleshooting

### No alerts appearing
1. Check that the alert service is running
2. Check the Django server logs for errors
3. Open browser console to see if frontend is polling correctly
4. Verify the auth token is valid

### Database errors
Make sure you've run the migrations:
```bash
python manage.py makemigrations livetracker
python manage.py migrate livetracker
```

### Import errors
Make sure you're running commands from the correct directory:
```bash
cd /home/parth/testlive/dev_folder
```

### API connection errors
- Verify the API URL is correct
- Check your internet connection
- Verify the auth token is valid
- Check API rate limits

## Logging

The alert service logs to console with detailed information:
- INFO: Successful operations
- WARNING: Non-critical issues
- ERROR: Critical errors

Check the logs for debugging:
```
2025-11-12 10:30:00 - livetracker.alertService.alert - INFO - Fetching vehicle data from API...
2025-11-12 10:30:01 - livetracker.alertService.alert - INFO - Successfully fetched data for 25 vehicles
2025-11-12 10:30:02 - livetracker.alertService.alert - INFO - Processing 25 vehicle records...
2025-11-12 10:30:03 - livetracker.alertService.alert - INFO - Generated 3 alerts
```

## Production Deployment

For production, consider using:
1. **Supervisor** or **systemd** to keep the alert service running
2. **Celery** for distributed task processing
3. **Redis** for caching and real-time updates
4. **WebSockets** for instant alert delivery (instead of polling)

Example supervisor config:
```ini
[program:alert_service]
command=/path/to/venv/bin/python manage.py run_alert_service
directory=/home/parth/testlive/dev_folder
autostart=true
autorestart=true
stderr_logfile=/var/log/alert_service.err.log
stdout_logfile=/var/log/alert_service.out.log
environment=SMARTFASTAPI_ACCESS_KEY="YOUR_API_KEY_HERE"
```

## Support

For issues or questions, check:
1. Django logs: `/home/parth/testlive/dev_folder/logs/`
2. Browser console for frontend errors
3. Alert service console output for backend errors
