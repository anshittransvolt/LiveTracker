from django.db import models
from django.core.exceptions import ValidationError
from .transport_model import TransportMaster
from .driver_model import DriverMaster


class HorseTrolleyAssignment(models.Model):
    # Route choices
    ROUTE_CHOICES = [
        ('DHAR_TO_DHULE', 'Dhar to Dhule'),
        ('DHULE_TO_DHAR', 'Dhule to Dhar'),
    ]
    
    # Place choices
    PLACE_CHOICES = [
        ('DHAR', 'Dhar'),
        ('DHULE', 'Dhule'),
        ('JULWANIYA', 'Julwaniya'),
    ]
    
    # Horse (Vehicle) reference
    horse = models.ForeignKey(
        TransportMaster,
        on_delete=models.PROTECT,
        to_field="horse_number",
        db_column="horse_number",
        related_name="horse_assignments"
    )

    # Driver reference
    driver = models.ForeignKey(
        DriverMaster,
        on_delete=models.PROTECT,
        to_field="employee_code",
        db_column="driver_code",
        related_name="driver_assignments"
    )
    
    # Route field
    route = models.CharField(
        max_length=20,
        choices=ROUTE_CHOICES,
        null=True,
        blank=True,
        help_text="Route direction"
    )
    
    # Place field
    place = models.CharField(
        max_length=15,
        choices=PLACE_CHOICES,
        null=True,
        blank=True,
        help_text="Current place location"
    )
    
    # LR Number (only for Dhar)
    lr_number = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        help_text="LR Number (only applicable when place is Dhar)"
    )

    tonnage = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        help_text="Tonnage of the Truck"
    )

    # Assignment timestamp
    assigned_date = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "horse_trolley_assignment"
        verbose_name = "Horse Assignment"
        verbose_name_plural = "Horse Assignments"
        ordering = ["-assigned_date"]

        constraints = [
            models.UniqueConstraint(
                fields=["horse"],
                name="unique_horse_assignment"
            )
        ]
        
        # Indexes for fast lookups
        indexes = [
            models.Index(fields=['horse', 'assigned_date'], name='idx_horse_date'),
        ]

    # -----------------------
    # VALIDATION
    # -----------------------
    def clean(self):
        # Ensure only active drivers can be assigned
        if self.driver and not self.driver.is_active:
            raise ValidationError(
                {"driver": "Selected driver is not active."}
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    # -----------------------
    # BACKWARD COMPATIBILITY
    # -----------------------
    @property
    def horse_number(self):
        return self.horse.horse_number if self.horse else None

    @property
    def driver_code(self):
        return self.driver.employee_code if self.driver else None

    @property
    def driver_name(self):
        return self.driver.employee_name if self.driver else None

    @property
    def driver_phone(self):
        return self.driver.phone if self.driver else None

    # -----------------------
    # HELPERS
    # -----------------------
    def get_full_details(self):
        return {
            "horse_number": self.horse.horse_number if self.horse else None,
            "horse_chassis_no": self.horse.horse_chassis_no if self.horse else None,
            "driver_code": self.driver.employee_code if self.driver else None,
            "driver_name": self.driver.employee_name if self.driver else None,
            "driver_phone": self.driver.phone if self.driver else None,
            "driver_active": self.driver.is_active if self.driver else False,
            "assigned_date": self.assigned_date,
            "route": self.get_route_display() if self.route else None,
            "place": self.get_place_display() if self.place else None,
            "lr_number": self.lr_number,
            "tonnage": self.tonnage,
        }

    def __str__(self):
        return f"{self.horse_number} - {self.driver_name}"
