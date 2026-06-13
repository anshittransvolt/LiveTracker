from django.core.management.base import BaseCommand
from django.core.cache import cache

from dashboard.services.dashboard_cache_service import refresh_dashboard_cache


class Command(BaseCommand):
    help = "Refresh dashboard KPI cache"

    def handle(self, *args, **options):
        self.stdout.write("Refreshing dashboard KPI cache...")

        try:
            refresh_dashboard_cache()
            cached = cache.get("dashboard:kpis")

            if cached:
                updated_at = cached.get("last_updated", "unknown")
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Dashboard cache refreshed successfully. last_updated={updated_at}"
                    )
                )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        "Refresh completed but cache key 'dashboard:kpis' is empty."
                    )
                )
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"Dashboard cache refresh failed: {exc}"))
            raise
