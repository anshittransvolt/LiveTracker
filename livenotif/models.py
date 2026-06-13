from django.db import models

SEVERITY_CHOICES = [
    ("high", "High"),
    ("medium", "Medium"),
    ("normal", "Normal"),
]


class EventType(models.Model):
    """Master table for event types/definitions"""

    event_id = models.CharField(
        max_length=20, unique=True, primary_key=True, help_text="e.g., EVT-101, EVT-102"
    )
    event_name = models.CharField(max_length=200, help_text="Name of the event")
    event_description = models.TextField(help_text="Detailed description of the event")
    severity = models.CharField(
        max_length=10, choices=SEVERITY_CHOICES, default="normal"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Event Type"
        verbose_name_plural = "Event Types"
        ordering = ["event_id"]

    def __str__(self):
        return f"{self.event_id} - {self.event_name}"


class Event(models.Model):
    """Event instances - each occurrence of an event type"""

    event_type = models.ForeignKey(
        EventType, on_delete=models.CASCADE, related_name="events"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(
        default=True, help_text="Whether this event is currently active/visible"
    )
    source = models.CharField(
        max_length=20, 
        help_text="Source of the event (e.g., 'alert_service', 'manual', 'sqs')"
    )
    latitude = models.DecimalField(
        max_digits=10, 
        decimal_places=7, 
        null=True, 
        blank=True,
        help_text="Latitude coordinate of the event location"
    )
    longitude = models.DecimalField(
        max_digits=10, 
        decimal_places=7, 
        null=True, 
        blank=True,
        help_text="Longitude coordinate of the event location"
    )

    class Meta:
        verbose_name = "Event"
        verbose_name_plural = "Events"
        ordering = ["-created_at"]

    def __str__(self):
        return (
            f"{self.event_type.event_id} - {self.created_at.strftime('%Y-%m-%d %H:%M')}"
        )

    @property
    def event_id(self):
        """Quick access to event_type's event_id"""
        return self.event_type.event_id

    @property
    def severity(self):
        """Quick access to event_type's severity"""
        return self.event_type.severity
