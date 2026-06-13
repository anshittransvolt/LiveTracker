from django.db import models
import secrets
import string


class ApiAuth(models.Model):
    """
    Model to store API authentication credentials.
    Database table for FastAPI application to manage API access keys.
    """
    username = models.CharField(max_length=255, unique=True, db_index=True)
    access_key = models.CharField(max_length=21, unique=True, db_index=True, editable=False)
    ttl = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Expiration date and time. Leave blank for no expiration.",
        verbose_name="Expires At"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "API Authentication"
        verbose_name_plural = "API Authentications"
        db_table = "tmpl_api_auth"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.username} - {self.access_key}"

    def save(self, *args, **kwargs):
        """Override save to generate access key if not present."""
        if not self.access_key:
            self.access_key = self.generate_access_key()
        super().save(*args, **kwargs)

    @staticmethod
    def generate_access_key(length=20):
        """
        Generate a random 16-character access key.
        Uses uppercase letters, lowercase letters, and digits.
        """
        characters = string.ascii_letters + string.digits
        return ''.join(secrets.choice(characters) for _ in range(length))

    def is_expired(self):
        """
        Check if the access key has expired.
        Returns False if ttl is None (no expiration set).
        """
        if self.ttl is None:
            return False
        from django.utils import timezone
        return timezone.now() > self.ttl
