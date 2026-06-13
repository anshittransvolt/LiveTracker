from datetime import datetime, timedelta
from django.core.management.base import BaseCommand
from django.db import transaction
from django.core.cache import cache

from livetracker.views import fetch_day
from livetracker.timebox import build_timebox_for_vehicle
from livetracker.models import TimeBoxDailyAvgDelay


class Command(BaseCommand):
    help = (
        "Compute and persist daily fleet-wide average delay (minutes) for TIME BOX trends."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--days", type=int, default=30, help="Number of past days to compute (default 30, max 90)",
        )
        parser.add_argument(
            "--start", type=str, help="Optional start date YYYY-MM-DD (inclusive)",
        )
        parser.add_argument(
            "--end", type=str, help="Optional end date YYYY-MM-DD (exclusive)",
        )
        parser.add_argument(
            "--force", action="store_true", help="Recompute even if records already exist",
        )

    def handle(self, *args, **options):
        days = options.get("days")
        start = options.get("start")
        end = options.get("end")
        force = options.get("force")
        days = max(1, min(int(days or 30), 90))

        if start and end:
            try:
                start_date = datetime.strptime(start, "%Y-%m-%d").date()
                end_date = datetime.strptime(end, "%Y-%m-%d").date()
            except Exception:
                self.stdout.write(self.style.ERROR("Invalid --start/--end format. Use YYYY-MM-DD."))
                return
        else:
            # default range: last `days` days ending today
            end_date = datetime.now().date() + timedelta(days=1)
            start_date = end_date - timedelta(days=days)

        self.stdout.write(self.style.MIGRATE_HEADING(f"Computing daily avg delays from {start_date} to {end_date} (force={force})"))

        # SLA thresholds per phase (seconds)
        from livetracker.alertService import alert_constants as ac
        PHASE_SLA = {
            'manawar_loading': ac.LOADING_DWELL_SECONDS,
            'dhule_unloading': ac.UNLOADING_DWELL_SECONDS,
            'manawar_charging': ac.CHARGING_OVER_SECONDS,
            'dhule_charging': ac.CHARGING_OVER_SECONDS,
            'jhulwania_charging': ac.CHARGING_OVER_SECONDS,
            'maha_border': ac.MAHA_BORDER_DWELL_SECONDS,
            # Transit phases
            'manawar_to_jhulwania': ac.MANAWAR_TO_JHULWANIA_TARGET,
            'jhulwania_to_manawar': ac.MANAWAR_TO_JHULWANIA_TARGET,
            'jhulwania_to_maha_border': ac.JHULWANIA_TO_DHULE_TARGET,
            'maha_border_to_dhule': ac.JHULWANIA_TO_DHULE_TARGET,
            'dhule_to_maha_border': ac.JHULWANIA_TO_DHULE_TARGET,
            'maha_border_to_jhulwania': ac.JHULWANIA_TO_DHULE_TARGET,
            'manawar_yard': 0,
            'jhulwania_yard': 0,
            'dhule_yard': 0,
        }

        def _calc_vehicle_delay_seconds(timeline: list) -> int:
            total = 0
            for phase in timeline or []:
                name = (phase.get('phase') or '').lower()
                dur = int(phase.get('duration_seconds') or 0)
                if not name or dur <= 0:
                    continue
                key = name.replace('mahaborder', 'maha_border').replace('maha border', 'maha_border')
                sla = PHASE_SLA.get(key)
                if sla is None:
                    if '_to_' in key:
                        sla = 0
                    else:
                        continue
                if sla == 0 and key in ['manawar_yard','jhulwania_yard','dhule_yard']:
                    total += dur
                elif sla and dur > sla:
                    total += (dur - sla)
            return max(0, int(total))

        @transaction.atomic
        def upsert_day(date_obj):
            start = date_obj.strftime('%Y-%m-%d')
            end = (date_obj + timedelta(days=1)).strftime('%Y-%m-%d')
            # If not forcing and already present, skip
            if not force and TimeBoxDailyAvgDelay.objects.filter(date=date_obj).exists():
                return False
            records = fetch_day(None, start, end) or []
            by_vehicle = {}
            for rec in records:
                vn = rec.get('vehicle_no')
                if not vn:
                    continue
                by_vehicle.setdefault(vn, []).append(rec)
            delays = []
            for _, points in by_vehicle.items():
                try:
                    journey = build_timebox_for_vehicle(points)
                    timeline = journey.get('timeline', [])
                    delay_sec = _calc_vehicle_delay_seconds(timeline)
                    delays.append(delay_sec)
                except Exception:
                    continue
            avg_sec = (sum(delays) // len(delays)) if delays else 0
            avg_minutes = (avg_sec // 60)
            obj, _ = TimeBoxDailyAvgDelay.objects.update_or_create(
                date=date_obj,
                defaults={
                    'avg_delay_minutes': avg_minutes,
                    'vehicle_count': len(delays),
                }
            )
            # also populate per-day cache for consistency
            cache.set(f"tb:day:{start}", {
                'date': start,
                'avg_delay': f"{avg_sec//3600:02d}:{(avg_sec%3600)//60:02d}",
                'avg_delay_minutes': avg_minutes
            }, timeout=60 * 60 * 24)
            return True

        # Iterate all days in range
        d = start_date
        updated = 0
        while d < end_date:
            if upsert_day(d):
                updated += 1
            d += timedelta(days=1)

        self.stdout.write(self.style.SUCCESS(f"Updated {updated} day records in TimeBoxDailyAvgDelay."))
