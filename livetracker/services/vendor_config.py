# Project/SPV -> vendor mapping and the Voltrack API HTTP+cache helper,
# copied from dashboard (vendor_spv_list.py / dashboard_kpi_services.py) so
# livetracker has no runtime dependency on the dashboard app.

import logging

import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

VENDOR_SPV_LIST = {
    "ULTRATECH": ["intangles"],
    "NAGPUR": ["eka"],
    "MBMT": ["intangles"],
    "UMT": ["intangles"],
    "VECV": ["intangles"],
    "STAR_CEMENT": ["propel"],
    "JM_BAXI": ["eim"],
    "GTI": ["eim"],
}


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
            "x-api-key": settings.VOLTRACK_API_TOKEN,
            "Content-Type": "application/json",
        },
        cache_ttl=cache_ttl,
    )
