from django.db import models
from django.utils import timezone


class VehicleState(models.Model):
    vehicle_id = models.TextField(null=True)  # Unique identifier from API
    vehicle_no = models.TextField(null=True)
    driver_name = models.TextField(null=True)

    last_lat = models.FloatField(null=True)
    last_lon = models.FloatField(null=True)
    last_soc = models.IntegerField(null=True)
    last_status = models.TextField(null=True)  # "Moving" / "Stop" / "Charging"
    last_connected = models.DateTimeField(null=True)

    # current_geofence = name of geofence we consider vehicle to be INSIDE (after debounce)
    current_geofence = models.TextField(null=True)
    # when we became 'inside' current_geofence (timezone-aware)
    inside_since = models.DateTimeField(null=True)
    # when we became 'outside' (used for debouncing or gate-out detection)
    outside_since = models.DateTimeField(null=True)

    # for detecting long stops outside geofence
    stop_start_ts = models.DateTimeField(null=True)

    # for charging dwell detection
    charging_start_ts = models.DateTimeField(null=True)

    # for transit: when vehicle left Manawar Out Area (after debounce)
    last_departure_ts = models.DateTimeField(null=True)
    last_departure_geofence = models.TextField(null=True)

    # last time an alert was emitted (optional help)
    last_alert_ts = models.DateTimeField(null=True)
    
    # JSON field to store per-alert-type last sent timestamps
    # Format: {"alert_type": "2025-12-03T10:30:00+00:00", ...}
    last_alert_data = models.TextField(null=True, blank=True)

    def __str__(self):
        return f"{self.vehicle_no} ({self.vehicle_id})"