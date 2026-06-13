from django.core.cache import cache
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
import logging

from ..services.dashboard_cache_service import refresh_dashboard_cache


logger = logging.getLogger(__name__)

PROJECTS = ["ULTRATECH", "MBMT", "UMT", "NAGPUR"]


@login_required
def dashboard(request):
    context = cache.get("dashboard:kpis")

    # LocMem cache is process-local; data warmed via management command may not
    # exist in the running web worker process. Warm on-demand in this process.
    if not context:
        try:
            refresh_dashboard_cache()
            context = cache.get("dashboard:kpis")
        except Exception as exc:
            logger.warning(f"On-demand dashboard cache refresh failed: {exc}")

    # fallback (only if cache empty)
    if not context:
        context = {
            "active_vehicle_counts": {p: 0 for p in PROJECTS},
            "average_soh_values": {p: 0 for p in PROJECTS},
            "average_efficiency_values": {p: 0 for p in PROJECTS},
            "fleet_average_temperature": 0,
            "project_temperatures": {p: {"avg": 0, "max": 0} for p in PROJECTS},
            "temperature_date": None,
            "last_updated": None
        }
    print("Dashboard context:", context)  # Debug log   

    return render(request, "dashboard/dashboard.html", context)