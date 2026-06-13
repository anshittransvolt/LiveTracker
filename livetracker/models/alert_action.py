from django.db import models
from django.utils import timezone
import uuid


class AlertAction(models.Model):
    """
    Model to track actions taken on vehicle alerts.
    Independent model without foreign key dependencies.
    Records who took action, what action was taken, and when.
    
    Usage in views/API:
        # Create alert action with current user
        alert_action = AlertAction.objects.create(
            event_id='EVT-001',
            action_type='acknowledged',
            action_taken_by=request.user.username,  # Auto-fill from request
            notes='Issue resolved'
        )
        
        # Or using the create_action helper method
        alert_action = AlertAction.create_action(
            event_id='EVT-001',
            action_type='closed',
            user=request.user,
            notes='False alarm'
        )
    """
    
    ACTION_TYPES = [
        ('closed', 'Closed'),
        ('acknowledged', 'Acknowledged'),
        ("action_taken", "Action Taken"),
    ]
    
    id = models.AutoField(
        primary_key=True,
        help_text="Auto-incrementing primary key"
    )
    alert_id = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True,
        help_text="Unique identifier for the alert"
    )
    event_id = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        help_text="Event ID from livenotif system (e.g., EVT-001)"
    )
    action_type = models.CharField(
        max_length=20,
        choices=ACTION_TYPES,
        help_text="Type of action taken on the alert"
    )
    action_taken_by = models.CharField(
        max_length=150,
        help_text="Username or identifier of who took the action (auto-filled from request.user)"
    )
    notes = models.TextField(
        blank=True,
        null=True,
        help_text="Additional notes or comments about the action"
    )
    created_at = models.DateTimeField(
        default=timezone.now,
        help_text="When the action was taken"
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="Last update timestamp"
    )

    class Meta:
        db_table = 'livetracker_alert_action'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['alert_id']),
            models.Index(fields=['event_id']),
            models.Index(fields=['action_taken_by', '-created_at']),
            models.Index(fields=['-created_at']),
        ]

    def __str__(self):
        return f"{self.action_type} by {self.action_taken_by} - {self.alert_id}"

    @classmethod
    def create_action(cls, event_id, action_type, user, notes=None):
        """
        Helper method to create an alert action with the current user.
        
        Args:
            event_id (str): Event ID from livenotif system
            action_type (str): One of 'closed', 'acknowledged', 'action_taken'
            user (User): Django User object from request.user
            notes (str, optional): Additional notes
            
        Returns:
            AlertAction: Created alert action instance
            
        Example:
            alert_action = AlertAction.create_action(
                event_id='EVT-001',
                action_type='acknowledged',
                user=request.user,
                notes='Investigating the issue'
            )
        """
        return cls.objects.create(
            event_id=event_id,
            action_type=action_type,
            action_taken_by=user.username if hasattr(user, 'username') else str(user),
            notes=notes
        )

    def save(self, *args, **kwargs):
        """Auto-update updated_at on save"""
        if not self.pk:
            # First time save
            self.created_at = timezone.now()
        self.updated_at = timezone.now()
        super().save(*args, **kwargs)
