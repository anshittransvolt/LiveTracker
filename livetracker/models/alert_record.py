from django.db import models
from django.contrib.auth.models import User


class LiveTrackerAlertAction(models.Model):
    """
    Stores ONLY user interaction with alerts.
    Alerts themselves live in another system.
    """

    # Reference to external alert (from SQS / webhook DB)
    alert_id = models.CharField(max_length=100)  
    alert_type = models.CharField(max_length=100)
    vehicle_no = models.CharField(max_length=50, blank=True)

    # User interaction
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="alert_actions"
    )

    class ActionType(models.TextChoices):
        ACKNOWLEDGED = "ack", "Acknowledged"
        ACTION_TAKEN = "action", "Action Taken"

    action_type = models.CharField(
        max_length=20,
        choices=ActionType.choices
    )

    action_note = models.TextField(blank=True)

    action_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "livetracker_live_alert_action"
        verbose_name = "Live Alert User Action"
        verbose_name_plural = "Live Alert User Actions"
        ordering = ["-action_at"]
        indexes = [
            models.Index(fields=["alert_id"], name="live_alert_alertid_idx"),
            models.Index(fields=["user"], name="live_alert_user_idx"),
            models.Index(fields=["-action_at"], name="live_alert_actionat_idx"),
            models.Index(fields=["vehicle_no"], name="live_alert_vehicle_idx"),
        ]
        unique_together = ("alert_id", "user", "action_type")

    def __str__(self):
        return f"{self.alert_type} - {self.vehicle_no} | {self.user.username} | {self.get_action_type_display()}"
