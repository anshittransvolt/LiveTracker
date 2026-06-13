from django.db import models
from django.contrib.auth.models import User


class UserActionLog(models.Model):
    """
    Stores user activity / action logs for auditing and tracking.
    """

    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="action_logs"
    )

    role = models.CharField(
        max_length=50,
        blank=True,
        help_text="Role of the user at the time of action"
    )

    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True
    )

    user_agent = models.TextField(
        blank=True,
        help_text="Browser/client user agent string"
    )

    session_id = models.CharField(
        max_length=255,
        blank=True,
        help_text="Session ID to group actions by session"
    )

    section = models.CharField(
        max_length=100,
        help_text="Application module or section"
    )

    action = models.CharField(
        max_length=255,
        help_text="Action performed by the user"
    )

    path = models.CharField(
        max_length=500,
        help_text="Request URL or frontend route"
    )

    method = models.CharField(
        max_length=10,
        blank=True,
        help_text="HTTP method (GET, POST, PUT, DELETE, etc.)"
    )

    response_status = models.IntegerField(
        null=True,
        blank=True,
        help_text="HTTP response status code (200, 404, 500, etc.)"
    )

    duration_ms = models.IntegerField(
        null=True,
        blank=True,
        help_text="Request processing duration in milliseconds"
    )

    session_duration = models.IntegerField(
        null=True,
        blank=True,
        help_text="Total session duration in seconds at time of action"
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    class Meta:
        db_table = "user_action_log"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user"]),
            models.Index(fields=["section"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["session_id"]),
            models.Index(fields=["response_status"]),
        ]

    def __str__(self):
        return f"{self.user} | {self.action} | {self.created_at}"
