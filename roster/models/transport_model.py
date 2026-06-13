from django.db import models
from django.core.exceptions import ValidationError


class TransportMaster(models.Model):
    transport_name = models.CharField(
        max_length=200, default="Transvolt Logistics Private Limited"
    )

    # THESE MUST REMAIN UNIQUE (truck identity)
    horse_chassis_no = models.CharField(max_length=50, unique=True)
    horse_number = models.CharField(max_length=50, unique=True, db_index=True)

    # THESE ARE OPTIONAL AND NOT UNIQUE
    trolley_number = models.CharField(
        max_length=50, blank=True, null=True, db_index=True
    )
    trolley_chassis_no = models.CharField(
        max_length=50, blank=True, null=True
    )

    class Meta:
        db_table = "transport_master"
        verbose_name = "Transport Master"
        verbose_name_plural = "Transport Masters"

    def clean(self):

        # ------------------------------
        # 1. HORSE CHASSIS VALIDATION
        # ------------------------------
        if not self.horse_chassis_no or not self.horse_chassis_no.strip():
            raise ValidationError(
                {"horse_chassis_no": "Horse chassis number is required."}
            )
        self.horse_chassis_no = self.horse_chassis_no.strip().upper()

        # enforce uniqueness
        if (
            TransportMaster.objects.filter(horse_chassis_no=self.horse_chassis_no)
            .exclude(pk=self.pk)
            .exists()
        ):
            raise ValidationError(
                {"horse_chassis_no": "Horse chassis number already exists."}
            )

        # ------------------------------
        # 2. HORSE NUMBER VALIDATION
        # ------------------------------
        if not self.horse_number or not self.horse_number.strip():
            raise ValidationError({"horse_number": "Horse number is required."})

        self.horse_number = self.horse_number.strip().upper()

        if (
            TransportMaster.objects.filter(horse_number=self.horse_number)
            .exclude(pk=self.pk)
            .exists()
        ):
            raise ValidationError({"horse_number": "Horse number already exists."})

        # ------------------------------
        # 3. FORMAT OPTIONAL FIELDS
        # ------------------------------
        if self.trolley_number:
            self.trolley_number = self.trolley_number.strip().upper()

        if self.trolley_chassis_no:
            self.trolley_chassis_no = self.trolley_chassis_no.strip().upper()

        # IMPORTANT:
        # No uniqueness validation for trolley_number or trolley_chassis_no
        # because dataset shows MANY duplicates/shared values.

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.horse_number} - {self.trolley_number or 'No Trolley'}"
