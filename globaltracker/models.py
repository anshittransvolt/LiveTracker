from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


class Geofence(models.Model):
    name = models.CharField(max_length=200)
    # GeoJSON geometry stored as JSON (supports polygon, circle, rectangle)
    geometry = models.JSONField()
    # Optional metadata
    spv = models.CharField(max_length=50, blank=True)  # e.g. UMT, MBMT, nagpur
    color = models.CharField(max_length=20, default='#3b82f6')
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='geofences'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name
