from django.db import models
from django.utils import timezone


class VehicleAlert(models.Model):
    vehicle_id = models.TextField(null=True)  # Added vehicle_id
    vehicle_no = models.TextField()
    driver_name = models.TextField(null=True)  # Added driver_name
    geofence_name = models.TextField(null=True)
    gps_location = models.TextField(null=True)
    lat = models.FloatField(null=True)
    lon = models.FloatField(null=True)
    soc = models.IntegerField(null=True)
    alert_type = models.TextField()  # e.g., charging_overrun, unplanned_stop
    text = models.TextField()
    priority = models.CharField(
        max_length=10,
        choices=[("low", "Low"), ("medium", "Medium"), ("high", "High")],
        default="medium",
        help_text="Priority of the alert",
    )
    spv = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        help_text="SPV/project identifier (e.g., 'ULTRATECH', 'MBMT')",
    )
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"[{self.alert_type}] {self.vehicle_no} - {self.text[:60]}"
