"""
Fleet Trend Scheduler
Runs _run_fleet_trend_pipeline every day at 02:00 AM IST via APScheduler.
Started by MisConfig.ready() — guarded against double-start in dev reloader.
"""
from __future__ import annotations

import logging
import os
from datetime import date, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger("mis.scheduler")

_scheduler: BackgroundScheduler | None = None


def _run_fleet_trend_pipeline() -> None:
    from collections import defaultdict
    from dashboard.services.dashboard_kpi_services import fetch_voltrack_api
    from dashboard.vendor_spv_list import VENDOR_SPV_LIST
    from livetracker.models import FleetTrendDaily

    BATTERY_KWH = 282
    today = date.today()
    start_date = (today - timedelta(days=7)).strftime("%Y-%m-%d")
    end_date = (today - timedelta(days=1)).strftime("%Y-%m-%d")

    def _avg(lst):
        return round(sum(lst) / len(lst), 4) if lst else None

    def _parse_record(rec):
        if not isinstance(rec, dict):
            return None
        date_key = str(rec.get("dt") or rec.get("date") or rec.get("data_date") or rec.get("record_date") or "")[:10]
        if not date_key:
            return None
        try:
            dist = float(rec.get("distance_km", 0) or 0)
            discharge = float(rec.get("total_discharge_pct", 0) or 0)
        except (ValueError, TypeError):
            return None
        if dist < 1:
            return None
        raw_energy = rec.get("energy_consumed_kwh") or rec.get("energy_kwh")
        energy = float(raw_energy) if raw_energy not in (None, "", 0) else (discharge / 100) * BATTERY_KWH
        try:
            eff = float(rec.get("efficiency_kwh_per_km", 0) or 0)
        except (ValueError, TypeError):
            eff = 0.0
        reg = str(rec.get("registration_number") or "").upper().strip()
        return date_key, reg, dist, energy, eff

    for spv, vendors in VENDOR_SPV_LIST.items():
        if not vendors:
            continue
        vendor = vendors[0]
        logger.info(f"Fleet trend: fetching {spv}/{vendor} {start_date}→{end_date}")

        all_records = []
        cursor = None
        for _ in range(30):
            params = {"spv": spv, "vendor": vendor, "start_date": start_date, "end_date": end_date}
            if cursor:
                params["cursor"] = cursor
            try:
                resp = fetch_voltrack_api("/analytics/soc-discharge", params=params, cache_ttl=60)
            except Exception as exc:
                logger.warning(f"Fleet trend API error for {spv}: {exc}")
                break
            if not resp:
                break
            all_records.extend(resp.get("data", []))
            cursor = (resp.get("pagination") or {}).get("next_cursor")
            if not cursor:
                break

        fleet: dict = defaultdict(lambda: {"dist": [], "energy": [], "eff": []})
        per_vehicle: dict = defaultdict(lambda: {"dist": [], "energy": [], "eff": []})

        for rec in all_records:
            parsed = _parse_record(rec)
            if parsed is None:
                continue
            date_key, reg, dist, energy, eff = parsed
            fleet[date_key]["dist"].append(dist)
            fleet[date_key]["energy"].append(energy)
            if eff > 0:
                fleet[date_key]["eff"].append(eff)
            if reg:
                per_vehicle[(date_key, reg)]["dist"].append(dist)
                per_vehicle[(date_key, reg)]["energy"].append(energy)
                if eff > 0:
                    per_vehicle[(date_key, reg)]["eff"].append(eff)

        saved = 0
        for date_str, vals in fleet.items():
            try:
                FleetTrendDaily.objects.update_or_create(
                    date=date_str, spv=spv, vehicle_no=None,
                    defaults={
                        "avg_distance_km": _avg(vals["dist"]),
                        "avg_energy_kwh": _avg(vals["energy"]),
                        "avg_efficiency_kwh_per_km": _avg(vals["eff"]),
                        "vehicle_count": len(vals["dist"]),
                    },
                )
                saved += 1
            except Exception as exc:
                logger.warning(f"Fleet avg save failed {spv}/{date_str}: {exc}")

        for (date_str, reg), vals in per_vehicle.items():
            try:
                FleetTrendDaily.objects.update_or_create(
                    date=date_str, spv=spv, vehicle_no=reg,
                    defaults={
                        "avg_distance_km": _avg(vals["dist"]),
                        "avg_energy_kwh": _avg(vals["energy"]),
                        "avg_efficiency_kwh_per_km": _avg(vals["eff"]),
                        "vehicle_count": len(vals["dist"]),
                    },
                )
                saved += 1
            except Exception as exc:
                logger.warning(f"Vehicle trend save failed {spv}/{reg}/{date_str}: {exc}")

        logger.info(f"Fleet trend: saved {saved} rows for {spv}")


def start() -> None:
    global _scheduler
    if os.environ.get("RUN_MAIN") == "true":
        return
    if _scheduler is not None and _scheduler.running:
        return
    _scheduler = BackgroundScheduler(timezone="Asia/Kolkata")
    _scheduler.add_job(
        _run_fleet_trend_pipeline,
        trigger=CronTrigger(hour=2, minute=0),
        id="fleet_trend_daily",
        name="Fleet Trend Daily Cache",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    _scheduler.start()
    logger.info("[APScheduler] Fleet trend scheduler started — 02:00 AM IST.")
