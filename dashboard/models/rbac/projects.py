# rbac/models.py
from django.db import models

class Project(models.Model):
    name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "RBAC: Project"
        verbose_name_plural = "RBAC: Projects"
        ordering = ['name']

    def __str__(self):
        return self.name