from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from datetime import datetime
from typing import Optional, Tuple

from mis.models import DailyLog, CalculatedTrip


def normalize_number(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return ''.join(str(value).split()).upper() or None


class Command(BaseCommand):
    help = (
        "Normalize vehicle/horse numbers in-place (uppercase, no spaces) for DailyLog.horse_no "
        "and CalculatedTrip.vehicle_no. Dry-run by default."
    )

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='Apply changes (default is dry-run)')
        parser.add_argument('--start', type=str, help='Start date YYYY-MM-DD for DailyLog.log_date / CalculatedTrip.log_date filter')
        parser.add_argument('--end', type=str, help='End date YYYY-MM-DD for DailyLog.log_date / CalculatedTrip.log_date filter')
        parser.add_argument('--limit', type=int, help='Max rows per model to process')
        parser.add_argument('--batch-size', type=int, default=500, help='Batch size for bulk updates')
        parser.add_argument('--models', type=str, default='dailylog,calculatedtrip', help='Comma-separated: dailylog,calculatedtrip')

    def handle(self, *args, **options):
        apply = options.get('apply', False)
        start = options.get('start')
        end = options.get('end')
        limit = options.get('limit')
        batch_size = options.get('batch_size') or 500
        models_opt = (options.get('models') or 'dailylog,calculatedtrip').lower()
        do_daily = 'dailylog' in models_opt
        do_calc = 'calculatedtrip' in models_opt

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"Normalization {'APPLY' if apply else 'DRY-RUN'} | models={models_opt} | batch={batch_size}"
        ))

        start_date = self._parse_date(start)
        end_date = self._parse_date(end)
        if start_date and end_date and start_date > end_date:
            self.stderr.write(self.style.ERROR('Start date must be <= end date'))
            return

        total_changed = 0
        total_conflicts = 0

        if do_daily:
            changed, conflicts = self._process_daily_logs(apply, start_date, end_date, limit, batch_size)
            total_changed += changed
            total_conflicts += conflicts

        if do_calc:
            changed, conflicts = self._process_calculated_trips(apply, start_date, end_date, limit, batch_size)
            total_changed += changed
            total_conflicts += conflicts

        self.stdout.write(self.style.SUCCESS(
            f"Done. Changed={total_changed}, Conflicts={total_conflicts}, Mode={'APPLY' if apply else 'DRY-RUN'}"
        ))

    def _parse_date(self, s: Optional[str]) -> Optional[datetime.date]:
        if not s:
            return None
        try:
            return datetime.fromisoformat(s).date()
        except ValueError:
            self.stderr.write(self.style.WARNING(f"Ignoring invalid date: {s}"))
            return None

    def _process_daily_logs(self, apply: bool, start_date, end_date, limit, batch_size) -> Tuple[int, int]:
        qs = DailyLog.objects.all().only('id', 'horse_no', 'log_date').order_by('id')
        if start_date:
            qs = qs.filter(log_date__gte=start_date)
        if end_date:
            qs = qs.filter(log_date__lte=end_date)
        if limit:
            qs = qs[:limit]

        to_update = []
        changed = 0
        for obj in qs.iterator(chunk_size=batch_size):
            orig = obj.horse_no
            norm = normalize_number(orig)
            if orig != norm:
                changed += 1
                obj.horse_no = norm
                to_update.append(obj)
                if not apply and changed <= 5:
                    self.stdout.write(f"DailyLog id={obj.id} '{orig}' -> '{norm}' ({obj.log_date})")

        if apply and to_update:
            with transaction.atomic():
                DailyLog.objects.bulk_update(to_update, ['horse_no'], batch_size=batch_size)
        self.stdout.write(self.style.SUCCESS(f"DailyLog: changed={changed}"))
        return changed, 0

    def _process_calculated_trips(self, apply: bool, start_date, end_date, limit, batch_size) -> Tuple[int, int]:
        qs = CalculatedTrip.objects.all().only('id', 'vehicle_no', 'manawar_in_time', 'log_date').order_by('id')
        if start_date:
            qs = qs.filter(log_date__gte=start_date)
        if end_date:
            qs = qs.filter(log_date__lte=end_date)
        if limit:
            qs = qs[:limit]

        to_update = []
        changed = 0
        conflicts = 0
        for obj in qs.iterator(chunk_size=batch_size):
            orig = obj.vehicle_no
            norm = normalize_number(orig)
            if orig == norm:
                continue
            # Collision detection: unique_together (vehicle_no, manawar_in_time)
            if obj.manawar_in_time is not None:
                exists = CalculatedTrip.objects.filter(
                    vehicle_no=norm,
                    manawar_in_time=obj.manawar_in_time
                ).exclude(pk=obj.id).exists()
                if exists:
                    conflicts += 1
                    if conflicts <= 5:
                        self.stderr.write(
                            self.style.WARNING(
                                f"Conflict: Trip id={obj.id} {orig} -> {norm} at {obj.manawar_in_time} would collide; skipping"
                            )
                        )
                    continue
            changed += 1
            obj.vehicle_no = norm
            to_update.append(obj)
            if not apply and changed <= 5:
                self.stdout.write(f"CalculatedTrip id={obj.id} '{orig}' -> '{norm}' (log_date={obj.log_date})")

        if apply and to_update:
            with transaction.atomic():
                CalculatedTrip.objects.bulk_update(to_update, ['vehicle_no'], batch_size=batch_size)
        self.stdout.write(self.style.SUCCESS(f"CalculatedTrip: changed={changed}, conflicts={conflicts}"))
        return changed, conflicts
