# MIS Pipeline — Management Commands Reference

All commands are run from `voltrack/voltrack/` with the virtualenv active:

```bash
cd /home/anshit/voltrack/voltrack
source /home/anshit/voltrack/venv/bin/activate
```

---

## 1. Check Trip Data Status

Shows the current date ranges for VehicleTripState, DailyLog, and CalculatedTrip.

```bash
python3 manage.py check_and_backfill_trip_data
```

---

## 2. Full Pipeline (recommended for backfills)

Calculates trips for a date range, saves to DB, and rebuilds TripPerformanceSummary. Logs to `logs/mis_pipeline.log` and the `mis_full_pipeline_run` DB table.

```bash
# Run for a date range
python3 manage.py run_full_pipeline --start 2026-05-01 --end 2026-05-13

# Force recalculate (deletes existing CalculatedTrip + all VehicleTripState in range first)
python3 manage.py run_full_pipeline --start 2026-05-01 --end 2026-05-13 --force

# Restrict to a single vehicle
python3 manage.py run_full_pipeline --start 2026-05-01 --end 2026-05-13 --vehicle MH15GB0001
```

> **Note:** `--force` deletes ALL VehicleTripState rows (carry-over state). Only use it when you want a completely fresh start. If you want to preserve carry-over from a prior month, delete states manually first (see section 6).

---

## 3. Calculate Daily Trips

Lightweight command for the last N days. Scheduled daily via APScheduler at 01:00 AM IST.

```bash
# Default: yesterday + today (2 days)
python3 manage.py calculate_daily_trips

# Custom lookback
python3 manage.py calculate_daily_trips --days 5

# Force recalculate even if trips exist
python3 manage.py calculate_daily_trips --days 2 --force
```

---

## 4. Recompute Month Cache

Fetches raw telemetry for a target day, recalculates trips for that entire month-to-date, and replaces the cached trips atomically.

```bash
# Default: yesterday
python3 manage.py recompute_month_cache

# Specific date
python3 manage.py recompute_month_cache --date 2026-05-10

# With custom lookback and vehicle filter
python3 manage.py recompute_month_cache --date 2026-05-10 --lookback 7 --vehicle MH15GB0001
```

---

## 5. Build Performance Summary

Builds/refreshes the `TripPerformanceSummary` table from existing CalculatedTrip data.

```bash
# Single month
python3 manage.py build_performance_summary --month 2026-05

# Date range
python3 manage.py build_performance_summary --start-month 2026-01 --end-month 2026-05

# All months in DB
python3 manage.py build_performance_summary --all

# Restrict to one vehicle
python3 manage.py build_performance_summary --month 2026-05 --vehicle MH15GB0001
```

---

## 6. Manual Data Cleanup (Django Shell)

Use when you need to delete a specific date range before re-running the pipeline.

```bash
python3 manage.py shell -c "
from mis.models import VehicleTripState, CalculatedTrip
from datetime import date

cutoff = date(2026, 4, 30)
vts_deleted, _ = VehicleTripState.objects.filter(state_date__gt=cutoff).delete()
ct_deleted, _ = CalculatedTrip.objects.filter(log_date__gt=cutoff).delete()
print(f'Deleted VehicleTripState: {vts_deleted}')
print(f'Deleted CalculatedTrip: {ct_deleted}')
"
```

After cleanup, run the full pipeline without `--force` so carry-over states from the cutoff date are preserved:

```bash
python3 manage.py run_full_pipeline --start 2026-05-01 --end 2026-05-13
```

---

## Typical Workflows

### Backfill a gap in data
1. Check status to find the gap: `python3 manage.py check_and_backfill_trip_data`
2. Run pipeline for the missing range: `python3 manage.py run_full_pipeline --start YYYY-MM-DD --end YYYY-MM-DD`

### Reset and rerun a month from scratch
1. Delete states and trips after the previous month's end (see section 6)
2. Run pipeline without `--force`: `python3 manage.py run_full_pipeline --start YYYY-MM-01 --end YYYY-MM-DD`

### Refresh performance summaries after trip changes
```bash
python3 manage.py build_performance_summary --month YYYY-MM
```
