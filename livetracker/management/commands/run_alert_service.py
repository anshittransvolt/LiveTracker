"""
Django management command to run the vehicle alert monitoring service.
Usage: python manage.py run_alert_service [--vendor VENDOR] [--spv SPV]
Data is fetched from the TWINS API (configured via Django settings).
"""

import signal
import sys
from django.core.management.base import BaseCommand
from livetracker.alertService.alert import alertService


class Command(BaseCommand):
    help = (
        "Runs the vehicle alert monitoring service that fetches data every 60 seconds "
        "from the TWINS API."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--vendor",
            type=str,
            help="TWINS API vendor filter (overrides TWINS_VENDOR setting)",
            default=None,
        )
        parser.add_argument(
            "--spv",
            type=str,
            help="TWINS API SPV filter (overrides TWINS_SPV setting)",
            default=None,
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("Starting alert monitoring service (TWINS API)…"))
        self.stdout.write(self.style.WARNING("Press Ctrl+C to stop"))

        service = alertService(
            vendor=options.get("vendor"),
            spv=options.get("spv"),
        )

        # Handle graceful shutdown
        def signal_handler(sig, frame):
            self.stdout.write(self.style.WARNING("\nStopping alert service..."))
            service.stop_monitoring()
            self.stdout.write(self.style.SUCCESS("Alert service stopped successfully"))
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        # Start monitoring
        service.start_monitoring()

        # Keep the main thread alive
        try:
            while service.is_running:
                signal.pause()
        except KeyboardInterrupt:
            service.stop_monitoring()
            self.stdout.write(self.style.SUCCESS("Alert service stopped"))
