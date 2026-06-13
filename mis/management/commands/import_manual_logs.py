from django.core.management.base import BaseCommand, CommandError
from mis.services.manual_entry_merger import ManualEntryMerger


class Command(BaseCommand):
    help = "Import manual DailyLog entries from an Excel file (matched by horse_no + log_date)"

    def add_arguments(self, parser):
        parser.add_argument("excel_path", type=str, help="Path to Excel file")
        parser.add_argument("--sheet", dest="sheet", type=str, default=None, help="Optional sheet name")
        parser.add_argument("--dry-run", dest="dry_run", action="store_true", help="Parse rows without saving")

    def handle(self, *args, **options):
        excel_path = options.get("excel_path")
        sheet = options.get("sheet")
        dry_run = options.get("dry_run", False)

        if not excel_path:
            raise CommandError("excel_path is required")

        merger = ManualEntryMerger()
        try:
            count = merger.import_daily_logs_from_excel(excel_path, sheet_name=sheet, dry_run=dry_run)
            action = "Parsed" if dry_run else "Imported"
            self.stdout.write(self.style.SUCCESS(f"{action} {count} daily logs from {excel_path}"))
        except Exception as e:
            raise CommandError(f"Failed to import logs: {e}")
