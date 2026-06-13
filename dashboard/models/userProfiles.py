from django.db import models
from django.contrib.auth.models import User, Group
from django.db.models.signals import post_save
from django.dispatch import receiver


class UserProfile(models.Model):
    """Extended user profile to track additional user information"""

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    group = models.ForeignKey(
        Group,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="user_profiles",
        help_text="Assign user to a group for access control"
    )
    msal_connected = models.BooleanField(
        default=False,
        help_text="True if user was created/authenticated via Microsoft MSAL, False if manually created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "User Profile"
        verbose_name_plural = "User Profiles"
        ordering = ["-created_at"]

    def __str__(self):
        group_info = f" - {self.group.name}" if self.group else " - No Group"
        auth_method = 'MSAL' if self.msal_connected else 'Manual'
        return f"{self.user.username}{group_info} ({auth_method})"

    @property
    def full_name(self):
        """Get user's full name"""
        return (
            f"{self.user.first_name} {self.user.last_name}".strip()
            or self.user.username
        )

    @property
    def auth_method(self):
        """Get authentication method as string"""
        return "Microsoft MSAL" if self.msal_connected else "Manual Entry"
    
    @property
    def group_name(self):
        """Get group name safely"""
        return self.group.name if self.group else "No Group"


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    """Automatically create UserProfile when User is created"""
    if created:
        # Only create profile if it doesn't already exist
        # This prevents interference with MSAL authentication service
        profile, profile_created = UserProfile.objects.get_or_create(
            user=instance, defaults={"msal_connected": False}
        )
        # print(f"DEBUG SIGNAL: User created - {instance.username}, Profile created: {profile_created}")


@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    """Save UserProfile when User is saved"""
    if hasattr(instance, "profile"):
        # print(f"DEBUG SIGNAL: Saving existing profile for {instance.username} - msal_connected: {instance.profile.msal_connected}")
        # Don't save here as it might interfere with MSAL service
        pass
    else:
        # Only create profile if it doesn't exist
        profile, profile_created = UserProfile.objects.get_or_create(
            user=instance, defaults={"msal_connected": False}
        )
        # print(f"DEBUG SIGNAL: Created missing profile for {instance.username}, Profile created: {profile_created}")
