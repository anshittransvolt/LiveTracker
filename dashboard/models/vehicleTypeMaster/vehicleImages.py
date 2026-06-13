from django.db import models
from django.core.exceptions import ValidationError
from .vehicleType import ModelType


class ModelImage(models.Model):
    model_type = models.ForeignKey(
        ModelType, on_delete=models.CASCADE, related_name="images"
    )
    image = models.ImageField(upload_to="vehicles/")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        """Limit images per vehicle type to 2"""
        if self.model_type.images.count() >= 2 and not self.pk:
            raise ValidationError("A vehicle type can have a maximum of 2 images.")

    def __str__(self):
        return f"Image for {self.model_type.model_number}"

    class Meta:
        verbose_name = "Model image"
        verbose_name_plural = "Model images"
        db_table = (
            "dashboard_vehicleimage"  # Keep old table name to avoid migration issues
        )
