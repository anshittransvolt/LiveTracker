from django.db import models

class Page(models.Model):
    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=100)
    section = models.CharField(max_length=100, blank=True, null=True)  # Optional grouping field
    project = models.CharField(max_length=100, blank=True, null=True)  # Optional project association

    class Meta:
        verbose_name = "RBAC: Page"
        verbose_name_plural = "RBAC: Pages"
        ordering = ['code']

    def __str__(self):
        return self.name