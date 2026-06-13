from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class AssignmentLog(models.Model):
    """
    Logs all assignment operations (create, update, delete).
    Tracks which user performed the action and when.
    """
    
    ACTION_CHOICES = [
        ('CREATE', 'Created'),
        ('UPDATE', 'Updated'),
        ('DELETE', 'Deleted'),
    ]
    
    # Assignment details
    horse_number = models.CharField(max_length=50, db_index=True)
    driver_code = models.CharField(max_length=50, db_index=True)
    driver_name = models.CharField(max_length=255)
    route = models.CharField(max_length=20, blank=True, null=True)
    place = models.CharField(max_length=15, blank=True, null=True)
    lr_number = models.CharField(max_length=50, blank=True, null=True)
    tonnage = models.CharField(max_length=50, blank=True, null=True)
    
    # Action details
    action = models.CharField(max_length=10, choices=ACTION_CHOICES, db_index=True)
    performed_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='assignment_logs'
    )
    performed_at = models.DateTimeField(default=timezone.now, db_index=True)
    
    # Additional information
    notes = models.TextField(blank=True, null=True)
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    
    # Previous values (for updates)
    previous_driver_code = models.CharField(max_length=50, blank=True, null=True)
    previous_driver_name = models.CharField(max_length=255, blank=True, null=True)
    previous_route = models.CharField(max_length=20, blank=True, null=True)
    previous_place = models.CharField(max_length=15, blank=True, null=True)
    previous_lr_number = models.CharField(max_length=50, blank=True, null=True)
    previous_tonnage = models.CharField(max_length=50, blank=True, null=True)
    
    class Meta:
        db_table = 'roster_assignment_log'
        ordering = ['-performed_at']
        verbose_name = 'Assignment Log'
        verbose_name_plural = 'Assignment Logs'
        indexes = [
            models.Index(fields=['-performed_at']),
            models.Index(fields=['horse_number', '-performed_at']),
            models.Index(fields=['driver_code', '-performed_at']),
        ]
    
    def __str__(self):
        return f"{self.action} - {self.horse_number} -> {self.driver_name} by {self.performed_by or 'System'} at {self.performed_at}"
    
    def get_action_display_color(self):
        """Return color class for action type"""
        colors = {
            'CREATE': 'green',
            'UPDATE': 'blue',
            'DELETE': 'red',
        }
        return colors.get(self.action, 'gray')
    
    def get_action_icon(self):
        """Return lucide icon name for action type"""
        icons = {
            'CREATE': 'plus-circle',
            'UPDATE': 'edit-2',
            'DELETE': 'trash-2',
        }
        return icons.get(self.action, 'circle')
