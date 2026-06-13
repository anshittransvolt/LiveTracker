import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from django.core.cache import cache

from ..vendor_spv_list import VENDOR_SPV_LIST
from ..services.dashboard_kpi_services import (
    fetch_fleet_average_temperature,
    fetch_active_vehicle_kpi,
    fetch_average_soh_kpi,
    fetch_avg_efficiency_kpi,
)

logger = logging.getLogger(__name__)

projects = ['ULTRATECH', 'MBMT', 'UMT', 'NAGPUR']


def refresh_dashboard_cache():
    try:
        jobs = [
            (spv, vendor)
            for spv in projects
            for vendor in VENDOR_SPV_LIST.get(spv, [])
        ]

        active_vehicle_counts = {p: 0 for p in projects}
        soh_sum = {p: 0.0 for p in projects}
        soh_count = {p: 0 for p in projects}
        eff_sum = {p: 0.0 for p in projects}
        eff_count = {p: 0 for p in projects}

        with ThreadPoolExecutor(max_workers=min(len(jobs), 15) or 1) as executor:
            future_map = {}

            for spv, vendor in jobs:
                future_map[executor.submit(fetch_active_vehicle_kpi, spv=spv, vendor=vendor)] = ("active", spv)
                future_map[executor.submit(fetch_average_soh_kpi, spv=spv, vendor=vendor)] = ("soh", spv)
                future_map[executor.submit(fetch_avg_efficiency_kpi, spv=spv, vendor=vendor)] = ("eff", spv)

            for future in as_completed(future_map):
                typ, spv = future_map[future]
                result = future.result() or {}

                try:
                    if typ == "active":
                        active_vehicle_counts[spv] += int(result.get("total_vehicles", 0) or 0)

                    elif typ == "soh":
                        avg = float(result.get("average_soh", 0) or 0)
                        cnt = int(result.get("count", 0) or 0)
                        if cnt > 0:
                            soh_sum[spv] += avg * cnt
                            soh_count[spv] += cnt

                    elif typ == "eff":
                        avg = float(result.get("average_efficiency_kwh_per_km", 0) or 0)
                        cnt = int(result.get("count", 0) or 0)
                        if cnt > 0:
                            eff_sum[spv] += avg * cnt
                            eff_count[spv] += cnt

                except Exception as e:
                    logger.warning(f"KPI processing failed for {spv}: {e}")

        
        average_soh_values = {
            p: round(soh_sum[p] / soh_count[p], 2) if soh_count[p] > 0 else 0
            for p in projects
        }

        average_efficiency_values = {
            p: round(eff_sum[p] / eff_count[p], 3) if eff_count[p] > 0 else 0
            for p in projects
        }

       
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')

        fleet_temp_data = fetch_fleet_average_temperature(
            projects=projects,
            start_date=yesterday,
            end_date=yesterday
        ) or {}

        
        data = {
            "active_vehicle_counts": active_vehicle_counts,
            "average_soh_values": average_soh_values,
            "average_efficiency_values": average_efficiency_values,
            "fleet_average_temperature": fleet_temp_data.get("fleet_average_temperature", 0),
            "project_temperatures": fleet_temp_data.get("project_temperatures", {}),
            "temperature_date": fleet_temp_data.get("date"),
            "last_updated": datetime.now().isoformat()
        }

        
        cache.set("dashboard:kpis", data, timeout=10800)

    except Exception as e:
        logger.error(f"Dashboard cache refresh failed: {e}")
        