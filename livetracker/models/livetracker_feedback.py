from django.db import models
from django.contrib.auth.models import User


class Feedback(models.Model):

    class FeedbackType(models.TextChoices):
        BUG = "bug", "Bug"
        FEATURE = "feature", "Feature Request"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        WORKING = "working", "Working on it"
        CLOSED = "closed", "Closed"

    # What user is submitting
    feedback_type = models.CharField(
        max_length=20,
        choices=FeedbackType.choices
    )

    # Core user inputs
    title = models.CharField(max_length=255)
    description = models.TextField()

    # Optional screenshot
    screenshot = models.ImageField(
        upload_to="livetracker/feedback/screenshots/",
        null=True,
        blank=True
    )

    # Auto-filled fields
    reported_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    page_url = models.URLField(max_length=500)

    browser = models.CharField(max_length=100, blank=True)
    os = models.CharField(max_length=100, blank=True)
    device = models.CharField(max_length=100, blank=True)

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.OPEN
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "feedback"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.feedback_type.upper()} | {self.title}"
