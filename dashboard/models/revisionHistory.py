from django.conf import settings
from django.db import models
import re


class RevisionHistory(models.Model):
    """Stores revision/version entries for application changes.

    Behaviour added:
    - `created_by` is a nullable FK to the project user model. Admin/save handlers should set
      this to the logged-in user when creating entries.
    - `version` remains a CharField but will be auto-computed on save (previous version + 1)
      when left empty. The auto-computation attempts several sensible fallbacks:
        * If last version is an integer -> increment it
        * If semantic (dot-separated) -> increment the last numeric segment
        * If ends with digits -> increment the trailing digits
        * Otherwise append `.1`
    """

    version = models.CharField(
        max_length=64, help_text="Semantic version or tag", db_index=True, blank=True
    )
    title = models.CharField(max_length=200)
    description = models.TextField(help_text="Detailed notes or list of changes")

    # Renamed: use a proper FK to the user model and allow null to preserve older rows.
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="revision_histories",
        help_text="User who created this revision (auto-filled from request.user in admin)",
    )

    # Store the creator's email separately so we can auto-fill and display it
    # without exposing a user FK input in the admin form.
    created_by_email = models.EmailField(
        max_length=254,
        null=True,
        blank=True,
        help_text="Email of the user who created this revision (auto-filled)",
    )

    is_published = models.BooleanField(
        default=True, help_text="If false, this revision is hidden from public listing"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    effective_date = models.DateTimeField(
        null=True, blank=True, help_text="When this revision became effective"
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["version"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        if getattr(self, "created_by", None):
            try:
                creator = self.created_by.get_full_name() or self.created_by.username
            except Exception:
                creator = str(self.created_by)
        else:
            creator = "System"
        return f"{self.version or 'unversioned'} - {self.title} ({creator})"

    @classmethod
    def _parse_and_increment(cls, version_str: str) -> str:
        """Try several strategies to increment a version-like string.

        Returns the incremented version (string) or version_str + '.1' as a last resort.
        """
        v = (version_str or "").strip()
        if not v:
            return "1"

        # 1) Plain integer
        try:
            return str(int(v) + 1)
        except Exception:
            pass

        # 2) Dot separated semantic parts - increment the last numeric segment
        parts = v.split(".")
        for i in range(len(parts) - 1, -1, -1):
            try:
                num = int(parts[i])
                parts[i] = str(num + 1)
                return ".".join(parts)
            except Exception:
                continue

        # 3) Trailing digits anywhere in the string
        m = re.search(r"(\d+)$", v)
        if m:
            num = int(m.group(1)) + 1
            return v[: m.start(1)] + str(num)

        # 4) Fallback
        return v + ".1"

    @classmethod
    def next_version(cls) -> str:
        """Return the next version string based on the latest saved RevisionHistory.

        This queries the DB for the most recent entry (by created_at). If none exist,
        returns '1.0.0'.
        """
        last = cls.objects.order_by("-created_at").first()
        if not last or not getattr(last, "version", None):
            return "1.0.0"

        v = (last.version or "").strip()

        # Prefer semantic-style increments (major.minor.patch). Try to increment
        # the last numeric segment and normalize to 3 parts.
        parts = v.split(".")
        for i in range(len(parts) - 1, -1, -1):
            try:
                num = int(parts[i])
                parts[i] = str(num + 1)
                # Normalize to exactly 3 components (major.minor.patch)
                if len(parts) < 3:
                    parts = parts + ["0"] * (3 - len(parts))
                if len(parts) > 3:
                    parts = parts[:3]
                return ".".join(parts)
            except Exception:
                continue

        # If we can't parse semantic parts, try parse-and-increment then normalize
        candidate = cls._parse_and_increment(v)
        if "." in candidate:
            parts = candidate.split(".")
            parts = parts + ["0"] * (3 - len(parts)) if len(parts) < 3 else parts[:3]
            return ".".join(parts)
        try:
            n = int(candidate)
            return f"{n}.0.0"
        except Exception:
            return "1.0.0"

    def save(self, *args, **kwargs):
        # Auto-set version when not provided
        if not self.version:
            try:
                self.version = self.__class__.next_version()
            except Exception:
                # Keep saving even if next_version fails for some reason
                if not self.version:
                    self.version = "1"
        # If created_by is set but created_by_email not provided, copy it across.
        try:
            if getattr(self, "created_by", None) and not self.created_by_email:
                email = getattr(self.created_by, "email", None)
                if email:
                    self.created_by_email = email
        except Exception:
            pass
        super().save(*args, **kwargs)
