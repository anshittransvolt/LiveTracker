from django.db import models
from .vendor import Vendor


class ModelType(models.Model):
    CATEGORY_CHOICES = [
        ("bus", "Bus"),
        ("truck", "Truck"),
    ]

    vendor = models.ForeignKey(
        Vendor, on_delete=models.CASCADE, related_name="vehicle_types"
    )
    model_number = models.CharField(max_length=100, unique=True)
    category = models.CharField(max_length=10, choices=CATEGORY_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.vendor.vendor_name} - {self.model_number}"

    class Meta:
        verbose_name = "Model type"
        verbose_name_plural = "Model types"
        db_table = (
            "dashboard_vehicletype"  # Keep old table name to avoid migration issues
        )
