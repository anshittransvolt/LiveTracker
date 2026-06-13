from datetime import datetime, timedelta
from django.core.management.base import BaseCommand
from django.core.cache import cache
from livetracker.views import fetch_day
from livetracker.timebox import build_timebox_for_vehicle


class Command(BaseCommand):
    help = (
        "Pre-warm TIME BOX caches: last N days (daily) and last M months (monthly->day drilldown)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--days", type=int, default=30, help="Number of days to pre-warm (default 30, max 60)",
        )
        parser.add_argument(
            "--months", type=int, default=6, help="Number of months to pre-warm (default 6, max 12)",
        )

    def handle(self, *args, **options):
        days = max(1, min(int(options["days"]), 60))
        months = max(1, min(int(options["months"]), 12))

        self.stdout.write(self.style.MIGRATE_HEADING(f"Pre-warming TIME BOX cache: days={days}, months={months}"))

        # Pre-warm daily series (last `days`)
        self._prewarm_daily_series(days)

        # Pre-warm month series (last `months`) and each month's day-wise series
        self._prewarm_month_series(months)

        self.stdout.write(self.style.SUCCESS("TIME BOX cache pre-warm complete."))

    # --- Internal helpers ---
    def _phase_sla(self):
        from livetracker.alertService import alert_constants as ac
        return {
            'manawar_loading': ac.LOADING_DWELL_SECONDS,
            'dhule_unloading': ac.UNLOADING_DWELL_SECONDS,
            'manawar_charging': ac.CHARGING_OVER_SECONDS,
            'dhule_charging': ac.CHARGING_OVER_SECONDS,
            'jhulwania_charging': ac.CHARGING_OVER_SECONDS,
            'maha_border': ac.MAHA_BORDER_DWELL_SECONDS,
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

    def _calc_vehicle_delay_seconds(self, timeline: list, PHASE_SLA: dict) -> int:
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

    def _compute_day_avg(self, date_obj) -> dict:
        PHASE_SLA = self._phase_sla()
        start = date_obj.strftime('%Y-%m-%d')
        end = (date_obj + timedelta(days=1)).strftime('%Y-%m-%d')
        cache_key = f"tb:day:{start}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
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
                delay_sec = self._calc_vehicle_delay_seconds(timeline, PHASE_SLA)
                delays.append(delay_sec)
            except Exception:
                continue
        avg_sec = (sum(delays) // len(delays)) if delays else 0
        result = {
            'date': start,
            'avg_delay': f"{avg_sec//3600:02d}:{(avg_sec%3600)//60:02d}",
            'avg_delay_minutes': (avg_sec // 60)
        }
        cache.set(cache_key, result, timeout=60 * 60 * 24)
        return result

    def _prewarm_daily_series(self, days: int):
        self.stdout.write(self.style.HTTP_INFO(f"Pre-warming last {days} days (daily)") )
        today = datetime.now().date()
        series = []
        for i in range(days - 1, -1, -1):
            d = today - timedelta(days=i)
            series.append(self._compute_day_avg(d))
        cache.set(f"tb:series:day:{days}", series, timeout=60 * 30)

    def _prewarm_month_series(self, months: int):
        self.stdout.write(self.style.HTTP_INFO(f"Pre-warming last {months} months (monthly + day drilldown)"))
        # Month-level series
        today = datetime.now().date().replace(day=1)
        month_series = []
        month_labels = []
        for i in range(months - 1, -1, -1):
            # compute target year/month
            month_index = (today.year * 12 + (today.month - 1)) - i
            year = month_index // 12
            month = (month_index % 12) + 1
            label = f"{year:04d}-{month:02d}"
            month_labels.append((year, month, label))
            # ensure day-wise cached and compute monthly avg over day avgs
            days = self._compute_month_day_series(year, month)
            mins = [p['avg_delay_minutes'] for p in days if p]
            avg_m = (sum(mins) // len(mins)) if mins else 0
            month_series.append({
                'date': label,
                'label': label,
                'avg_delay': f"{(avg_m//60):02d}:{(avg_m%60):02d}",
                'avg_delay_minutes': avg_m
            })
        cache.set(f"tb:series:month:{months}", month_series, timeout=60 * 60 * 6)

    def _compute_month_day_series(self, year: int, month: int):
        key = f"tb:month_days:{year:04d}-{month:02d}"
        cached = cache.get(key)
        if cached is not None:
            return cached
        days = []
        first = datetime(year, month, 1).date()
        if month == 12:
            next_month = datetime(year + 1, 1, 1).date()
        else:
            next_month = datetime(year, month + 1, 1).date()
        d = first
        while d < next_month:
            days.append(self._compute_day_avg(d))
            d += timedelta(days=1)
        cache.set(key, days, timeout=60 * 60 * 6)
        return days
