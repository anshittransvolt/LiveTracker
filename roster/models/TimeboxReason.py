from django.db import models
from django.contrib.auth.models import User


class TimeboxReason(models.Model):
    """
    Model to store timebox reasons with driver and vehicle information.
    Tracks who logged the reason and when.
    """
    reason = models.TextField(help_text="Reason for timebox entry")
    driver_name = models.CharField(max_length=100)
    driver_phone = models.CharField(max_length=15, help_text="Driver's phone number")
    vehicle_number = models.CharField(max_length=50, help_text="Vehicle registration number")
    logged_at = models.DateTimeField(auto_now_add=True, help_text="Date and time when this was logged")
    logged_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True,
        related_name='timebox_reasons',
        help_text="User who logged this entry"
    )
    
    class Meta:
        verbose_name = "Timebox Reason"
        verbose_name_plural = "Timebox Reasons"
        ordering = ['-logged_at']
        indexes = [
            models.Index(fields=['-logged_at']),
            models.Index(fields=['vehicle_number']),
            models.Index(fields=['driver_phone']),
        ]
    
    def __str__(self):
        return f"{self.vehicle_number} - {self.driver_name} ({self.logged_at.strftime('%Y-%m-%d %H:%M')})"
