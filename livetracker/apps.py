from django.apps import AppConfig
import os


class LivetrackerConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "livetracker"

    def ready(self):
        """
        Auto-start the alert service when Django starts and register signals
        """
        # Import signals to register them
        import livetracker.signals
        
        # Only run in the main process (not in migrations or other management commands)
        import sys

        # Check if we're running the development server
        is_runserver = "runserver" in sys.argv
        is_main_process = os.environ.get("RUN_MAIN") == "true"

        # Only start in the main runserver process or production
        if is_runserver and is_main_process:
            self.start_alert_service()

    def start_alert_service(self):
        """
        Start the alert monitoring service in the background
        """
        import logging
        from threading import Thread

        logger = logging.getLogger(__name__)

        try:
            from livetracker.alertService.alert import alertService

            # Create and start the service (credentials come from Django settings)
            service = alertService()

            # Start in a separate thread to not block Django startup
            def start_monitoring():
                try:
                    service.start_monitoring()
                    logger.info(
                        "✅ Alert service started successfully - monitoring every 60 seconds"
                    )
                except Exception as e:
                    logger.error(f"❌ Failed to start alert service: {e}")

            # Start the monitoring thread
            thread = Thread(target=start_monitoring, daemon=True)
            thread.start()

            logger.info("🚀 Alert service initialization started")

        except ImportError as e:
            logger.error(f"❌ Could not import alert service: {e}")
        except Exception as e:
            logger.error(f"❌ Error starting alert service: {e}")
