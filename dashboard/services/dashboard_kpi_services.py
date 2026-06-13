# Date- 08-04-2024
# Edited by- PD - BFI-162 - Make Active Vehicle Count, Avg SOH and Avg Efficiency KPI Dynamic
# This file contains optimized services for fetching and processing KPIs for the dashboard.


import requests
import logging
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

TOKEN = settings.VOLTRACK_API_TOKEN
TWINS_API_TOKEN=settings.TWINS_API_TOKEN


def fetch_api(
    base_url: str,
    endpoint: str,
    method: str = "GET",
    params: dict = None,
    json_body: dict = None,
    headers: dict = None,
    cache_ttl: int = 300,
    timeout: int = 30,
):
    try:
        params = params or {}
        headers = headers or {}

        url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"

        # 🔑 Cache key
        cache_key = (
            f"{method}:{url}:"
            + "|".join(f"{k}={params[k]}" for k in sorted(params))
            + (f":body={str(json_body)}" if json_body else "")
        )

        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        response = requests.request(
            method=method.upper(),
            url=url,
            headers=headers,
            params=params,
            json=json_body,
            timeout=timeout,
        )

        response.raise_for_status()
        data = response.json()

        cache.set(cache_key, data, cache_ttl)
        return data

    except requests.exceptions.RequestException as e:
        logger.error(f"[API ERROR] {url} -> {str(e)}")
        return None
    except Exception as e:
        logger.error(f"[UNEXPECTED ERROR] {url} -> {str(e)}")
        return None



def fetch_voltrack_api(endpoint: str, params: dict, cache_ttl: int = 300):
    return fetch_api(
        base_url=settings.VOLTRACK_API_BASE_URL,
        endpoint=endpoint,
        method="GET",
        params=params,
        headers={
            "x-api-key": TOKEN,
            "Content-Type": "application/json"
        },
        cache_ttl=cache_ttl
    )

def fetch_twins_api(endpoint: str, params: dict, cache_ttl: int = 300):
    return fetch_api(
        base_url=settings.TWINS_API_URL,
        endpoint=endpoint,
        method="GET",
        params=params,
        headers={
            "Authorization": f"Bearer {TWINS_API_TOKEN}",
            "Content-Type": "application/json"
        },
        cache_ttl=cache_ttl
    )


def extract_temperature_kpi(data: list):
    max_temps = []

    for record in data:
        if isinstance(record, dict):
            val = record.get("max_temperature")
            if val is not None:
                try:
                    max_temps.append(float(val))
                except (ValueError, TypeError):
                    continue

    if not max_temps:
        return {
            "max_temperature": 0,
            "average_temperature": 0,
            "sum_temperature": 0,
            "count": 0
        }

    total_sum = sum(max_temps)
    count = len(max_temps)

    return {
        "max_temperature": round(max(max_temps), 2),
        "average_temperature": round(total_sum / count, 2),
        "sum_temperature": total_sum,
        "count": count
    }



def fetch_high_temperature_kpi(**params):
    api_response = fetch_voltrack_api(
        endpoint="analytics/high-temperature",
        params=params
    )

    if not api_response:
        return None

    data = (
        api_response.get("data", [])
        if isinstance(api_response, dict)
        else api_response
    )

    return extract_temperature_kpi(data)



def fetch_fleet_average_temperature(
    projects: list,
    start_date: str = None,
    end_date: str = None
):
    try:
       
        if not start_date or not end_date:
            yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
            start_date = start_date or yesterday
            end_date = end_date or yesterday

        total_sum = 0
        total_count = 0
        all_max_temps = []
        project_temps = {}

        max_workers = min(len(projects), 4) or 1

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    fetch_high_temperature_kpi,
                    spv=project,
                    start_date=start_date,
                    end_date=end_date
                ): project
                for project in projects
            }

            for future in as_completed(futures):
                project = futures[future]

                try:
                    data = future.result() or {}
                except Exception:
                    data = {}

                max_temp = data.get("max_temperature", 0)
                avg_temp = data.get("average_temperature", 0)

                project_temps[project] = {
                    "max": max_temp,
                    "avg": avg_temp
                }

                total_sum += data.get("sum_temperature", 0)
                total_count += data.get("count", 0)

                if max_temp > 0:
                    all_max_temps.append(max_temp)

        fleet_avg = round(total_sum / total_count, 2) if total_count else 0
        fleet_max = round(max(all_max_temps), 2) if all_max_temps else 0

        return {
            "fleet_average_temperature": fleet_avg,
            "fleet_max_temperature": fleet_max,
            "project_temperatures": project_temps,
            "date": end_date
        }

    except Exception as e:
        logger.error(f"[FLEET KPI ERROR] {str(e)}")
        return None

def fetch_active_vehicle_kpi(**params):
    api_response = fetch_twins_api(
        endpoint="latest_points",
        params=params
    )

    if not api_response:
        return None
    
    return {
        "total_vehicles": api_response.get("total_vehicles", 0)
    }

def fetch_average_soh_kpi(**params):
    api_response = fetch_voltrack_api(
        endpoint="/analytics/vehicle-soh-daily",
        params=params
    )

    if not isinstance(api_response, dict):
        return {"average_soh": 0}

    data = api_response.get("data", [])

    soh_values = []

    for record in data:
        if isinstance(record, dict):
            soh = record.get("soh")
            if soh is not None:
                try:
                    soh_values.append(float(soh))
                except (ValueError, TypeError):
                    continue

    if not soh_values:
        return {"average_soh": 0}

    avg_soh = round(sum(soh_values) / len(soh_values), 2)

    return {
        "average_soh": avg_soh,
        "count": len(soh_values)
    }

def fetch_avg_efficiency_kpi(**params):
    api_response = fetch_voltrack_api(
        endpoint="/analytics/soc-discharge",
        params=params
    )

    if not isinstance(api_response, dict):
        return {"average_efficiency_kwh_per_km": 0, "count": 0}

    data = api_response.get("data", [])

    included_records = []

    for record in data:
        if not isinstance(record, dict):
            continue

        try:
            distance = float(record.get("distance_km", 0) or 0)
            discharge = float(record.get("total_discharge_pct", 0) or 0)

            
            if distance >= 10 and discharge >= 10:
                included_records.append(record)

        except (ValueError, TypeError):
            continue

   
    efficiency_values = []

    for record in included_records:
        try:
            val = float(record.get("efficiency_kwh_per_km", 0) or 0)
            if val > 0:  # optional (recommended)
                efficiency_values.append(val)
        except (ValueError, TypeError):
            continue

    if not efficiency_values:
        return {"average_efficiency_kwh_per_km": 0, "count": 0}

    avg_efficiency = round(sum(efficiency_values) / len(efficiency_values), 3)

    return {
        "average_efficiency_kwh_per_km": avg_efficiency,
        "count": len(efficiency_values),
        "total_records": len(data),               # optional
        "included_records": len(included_records) # optional
    }