from django.db import models
from .vehicleType import ModelType


class ModelSpecification(models.Model):
    model_type = models.OneToOneField(
        ModelType, on_delete=models.CASCADE, related_name="specification"
    )
    specs = models.JSONField(
        help_text="Store specs as JSON, e.g. {'battery': '200kWh', 'range': '250km'}"
    )

    def __str__(self):
        return f"Specs for {self.model_type.model_number}"

    class Meta:
        verbose_name = "Model specification"
        verbose_name_plural = "Model specifications"
        db_table = (
            "dashboard_specification"  # Keep old table name to avoid migration issues
        )
