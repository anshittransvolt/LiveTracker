from __future__ import annotations

import os
from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "vehicletracker.settings")

app = Celery("vehicletracker")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

app.conf.beat_schedule = {
    "recompute-month-cache-daily": {
        "task": "mis.tasks.recompute_month_cache_task",
        "schedule": crontab(hour=0, minute=1),
        "options": {"queue": "default"},
    },
}

@app.task(bind=True)
def debug_task(self):
    print(f"Request: {self.request!r}")
