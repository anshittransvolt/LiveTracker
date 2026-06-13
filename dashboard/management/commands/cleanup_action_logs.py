"""
Management command to clean up old user action logs.
Usage: python manage.py cleanup_action_logs --days 90
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from dashboard.models.user_action_log import UserActionLog


class Command(BaseCommand):
    help = 'Delete user action logs older than specified days (default: 90 days)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=90,
            help='Number of days to keep logs (default: 90)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be deleted without actually deleting',
        )

    def handle(self, *args, **options):
        days = options['days']
        dry_run = options['dry_run']
        
        cutoff_date = timezone.now() - timedelta(days=days)
        
        old_logs = UserActionLog.objects.filter(created_at__lt=cutoff_date)
        count = old_logs.count()
        
        if count == 0:
            self.stdout.write(
                self.style.SUCCESS(f'No logs older than {days} days found.')
            )
            return
        
        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f'[DRY RUN] Would delete {count} logs older than {days} days '
                    f'(before {cutoff_date.strftime("%Y-%m-%d %H:%M:%S")})'
                )
            )
        else:
            old_logs.delete()
            self.stdout.write(
                self.style.SUCCESS(
                    f'Successfully deleted {count} logs older than {days} days '
                    f'(before {cutoff_date.strftime("%Y-%m-%d %H:%M:%S")})'
                )
            )
