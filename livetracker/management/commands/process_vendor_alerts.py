"""
Django management command to run the SQS alert poller.

Usage:
    python manage.py process_vendor_alerts
    
This command will:
1. Poll SQS queue for vendor alert messages
2. Filter for "Iplt Live Tracker App" vendor
3. Process each alert through the unified notification system
4. Send notifications via LiveNotif, Telegram, and Webhook
5. Delete successfully processed messages from queue
"""

from django.core.management.base import BaseCommand
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Process vendor alerts from SQS queue and send notifications'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Print messages without processing them',
        )

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    'DRY RUN MODE: Messages will be displayed but not processed'
                )
            )

        self.stdout.write(
            self.style.SUCCESS(
                '🚀 Starting SQS vendor alert processor...'
            )
        )

        try:
            from livetracker.alertService.sqs_script import poll_messages
            
            # Run the poller
            poll_messages()
            
        except KeyboardInterrupt:
            self.stdout.write(
                self.style.WARNING(
                    '\n⏹️  Poller stopped by user'
                )
            )
        except Exception as e:
            logger.error(f"Error in SQS poller: {e}", exc_info=True)
            self.stdout.write(
                self.style.ERROR(
                    f'❌ Error: {str(e)}'
                )
            )
            raise
