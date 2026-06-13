"""
MIS Daily Pipeline Scheduler
==============================
Uses APScheduler (BackgroundScheduler) to run the full MIS pipeline
for yesterday's data every day at 01:00 AM.

Started automatically when the Django app is ready (via MisConfig.ready()).
Guarded against double-starts in multi-process / reload scenarios using a
module-level flag — only the main Django process starts the scheduler
(RUN_MAIN env var check for manage.py runserver, always on for gunicorn).
"""
from __future__ import annotations

import logging
import os
from datetime import date, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger("mis.pipeline")

_scheduler: BackgroundScheduler | None = None


def _run_daily_pipeline() -> None:
    """
    Called by APScheduler at 01:00 AM every day.
    Runs run_full_pipeline for yesterday without --force so carry-over
    vehicle states are preserved.
    """
    from django.core.management import call_command

    yesterday = date.today() - timedelta(days=1)
    date_str = yesterday.strftime("%Y-%m-%d")

    logger.info(f"[APScheduler] Daily MIS pipeline triggered — processing {date_str}")
    try:
        call_command(
            "run_full_pipeline",
            start=date_str,
            end=date_str,
        )
        logger.info(f"[APScheduler] Daily MIS pipeline completed for {date_str}")
    except Exception as exc:
        logger.exception(f"[APScheduler] Daily MIS pipeline failed for {date_str}: {exc}")


def start() -> None:
    """Start the background scheduler. Safe to call multiple times — only starts once."""
    global _scheduler

    # Avoid starting a second scheduler in Django's auto-reloader child process.
    # RUN_MAIN=true is set by the reloader parent; the inner process that actually
    # serves requests does NOT have it, so we start there.  Under gunicorn / uvicorn
    # the var is absent entirely, which is also fine.
    if os.environ.get("RUN_MAIN") == "true":
        logger.debug("[APScheduler] Skipping scheduler start in reloader parent process.")
        return

    if _scheduler is not None and _scheduler.running:
        logger.debug("[APScheduler] Scheduler already running — skipping.")
        return

    _scheduler = BackgroundScheduler(timezone="Asia/Kolkata")
    _scheduler.add_job(
        _run_daily_pipeline,
        trigger=CronTrigger(hour=1, minute=0),
        id="mis_daily_pipeline",
        name="MIS Daily Pipeline (yesterday)",
        replace_existing=True,
        misfire_grace_time=3600,  # allow up to 1 h late if server was down
    )
    _scheduler.start()
    logger.info("[APScheduler] Scheduler started — MIS pipeline will run daily at 01:00 AM IST.")
