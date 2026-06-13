from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from dashboard.models import UserProfile


class Command(BaseCommand):
    help = "Check MSAL connection status for all users"

    def handle(self, *args, **options):
        self.stdout.write(
            self.style.SUCCESS("Checking MSAL connection status for all users:")
        )
        self.stdout.write("-" * 60)

        users = User.objects.all()

        if not users.exists():
            self.stdout.write(self.style.WARNING("No users found in the database."))
            return

        for user in users:
            try:
                profile = user.profile
                msal_status = (
                    "✓ MSAL Connected" if profile.msal_connected else "✗ Manual Auth"
                )
                auth_method = profile.auth_method

                self.stdout.write(
                    f"User: {user.username} | "
                    f"Email: {user.email} | "
                    f"Status: {msal_status} | "
                    f"Method: {auth_method}"
                )
            except UserProfile.DoesNotExist:
                self.stdout.write(
                    f"User: {user.username} | "
                    f"Email: {user.email} | "
                    f"Status: ⚠️  NO PROFILE"
                )

        self.stdout.write("-" * 60)

        # Summary
        total_users = users.count()
        msal_users = UserProfile.objects.filter(msal_connected=True).count()
        manual_users = UserProfile.objects.filter(msal_connected=False).count()
        no_profile = total_users - UserProfile.objects.count()

        self.stdout.write(f"Summary:")
        self.stdout.write(f"  Total Users: {total_users}")
        self.stdout.write(f"  MSAL Connected: {msal_users}")
        self.stdout.write(f"  Manual Auth: {manual_users}")
        self.stdout.write(f"  No Profile: {no_profile}")
