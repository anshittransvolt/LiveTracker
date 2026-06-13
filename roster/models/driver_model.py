from django.db import models
from django.core.exceptions import ValidationError
import re


class DriverMaster(models.Model):
    employee_code = models.CharField(max_length=50, unique=True, db_index=True)
    employee_name = models.CharField(max_length=200, db_index=True)
    phone = models.CharField(max_length=10, blank=True, null=True)
    ultratech_id = models.CharField(max_length=50, unique=True, null=True, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    class Meta:
        db_table = "driver_master"
        verbose_name = "Driver Master"
        verbose_name_plural = "Driver Masters"

    def clean(self):
        if not self.employee_code or not self.employee_code.strip():
            raise ValidationError({"employee_code": "Employee code is required."})

        self.employee_code = self.employee_code.strip().upper()

        if not self.employee_name or not self.employee_name.strip():
            raise ValidationError({"employee_name": "Employee name is required."})

        if len(self.employee_name.strip()) < 2:
            raise ValidationError(
                {"employee_name": "Employee name must be at least 2 characters."}
            )

        self.employee_name = self.employee_name.strip().title()

        # Validate phone if provided
        if self.phone:
            phone = re.sub(r"\D", "", self.phone)  # Remove non-digits
            if len(phone) != 10:
                raise ValidationError(
                    {"phone": "Phone number must be exactly 10 digits."}
                )
            if not phone.isdigit():
                raise ValidationError(
                    {"phone": "Phone number must contain only digits."}
                )
            self.phone = phone

        if (
            DriverMaster.objects.filter(employee_code=self.employee_code)
            .exclude(pk=self.pk)
            .exists()
        ):
            raise ValidationError({"employee_code": "Employee code already exists."})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.employee_name} ({self.employee_code})"
