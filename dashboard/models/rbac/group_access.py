from django.db import models
from django.contrib.auth.models import Group
from .projects import Project
from .page import Page

class GroupAccess(models.Model):
    group = models.OneToOneField(
        Group,
        on_delete=models.CASCADE,
        related_name="access_config"
    )
    
    projects = models.ManyToManyField(
        Project,
        blank=True,
        related_name="group_accesses",
        help_text="Projects this group has access to"
    )
    
    pages = models.ManyToManyField(
        Page,
        blank=True,
        related_name="group_accesses",
        help_text="Pages this group has access to"
    )
    
    access = models.JSONField(default=dict, blank=True, help_text="Additional access configuration (optional)")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Access for {self.group.name}"
    
    class Meta:
        verbose_name = "Group Access"
        verbose_name_plural = "Group Access"