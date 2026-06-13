from django.db import models


# --- Vendor ---
class Vendor(models.Model):
    vendor_name = models.CharField(max_length=255)
    vendor_support_email = models.EmailField()
    transvolt_contact_email = models.EmailField()
    transvolt_contact_person_mobile_no = models.CharField(
        max_length=20, blank=True, null=True
    )
    vendor_support_site = models.URLField(blank=True, null=True)
    details = models.JSONField(blank=True, null=True)

    def __str__(self):
        return self.vendor_name
