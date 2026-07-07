# livetracker/views.py
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from datetime import timedelta, datetime
from django.conf import settings
from django.core.cache import cache
import json
import requests
import logging
import os
import time
import pandas as pd
from .models import TimeBoxDailyAvgDelay, Geofence, FleetTrendDaily
from .analytics.analytics_service import format_analytics_response
from .analytics.charging_sessions import aggregate_charging_sessions, charging_sessions_to_dataframe
from .analytics.stoppage_sessions import aggregate_stoppage_sessions, stoppage_sessions_to_dataframe
from .analytics.dashboard_report import download_dashboard_report
from .timebox import build_timebox_for_vehicle
from .data_sources import DataSourceManager
from .services.route_corridor import load_corridor
@login_required
@require_http_methods(["GET"])
def dashboard_report_view(request):
    """
    Download Excel dashboard report for all vehicles (latest point per vehicle).
    """
    return download_dashboard_report(request)
from .models import VehicleAlert
from .alertService.telegram import send_telegram_message
from dashboard.models import Vehicle
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Simple in-memory cache for geocoding results to reduce API calls
GEOCODE_CACHE_TIMEOUT = 86400  # 24 hours in seconds (addresses don't change often)

# Rate limiting: Nominatim allows max 1 request per second
_last_nominatim_request_time = 0
_nominatim_rate_limit_lock = None

def _wait_for_rate_limit():
    """Ensure we don't exceed Nominatim's 1 request per second limit."""
    global _last_nominatim_request_time
    current_time = time.time()
    time_since_last_request = current_time - _last_nominatim_request_time
    
    if time_since_last_request < 1.0:
        sleep_time = 1.0 - time_since_last_request
        logger.debug(f"⏱️ Rate limiting: sleeping for {sleep_time:.2f}s")
        time.sleep(sleep_time)
    
    _last_nominatim_request_time = time.time()



@login_required
def all_view(request):
    # Returns the All Vehicles view (map with tails)
    # Uses TWINS API via Django proxies (/livetracker/api/twins/...)
    context = {}
    return render(request, "livetracker/dashboard.html", context)


@login_required
def vehicle_view(request, registration_number):
    # Returns single-vehicle analytics + playback page
    # Uses TWINS API via Django proxies (/livetracker/api/twins/...)
    return render(
        request,
        "livetracker/vehicle.html",
        {
            "registration_number": registration_number,
        },
    )


@login_required
def vehicle_history_view(request, registration_number, date):
    """
    Returns historical vehicle analytics + playback page for a specific date.
    Uses the same template as live view but with historical data.
    Uses TWINS API via Django proxies (/livetracker/api/twins/...)
    """
    return render(
        request,
        "livetracker/vehicle_history.html",
        {
            "registration_number": registration_number,
            "historical_date": date,
        },
    )


@login_required
@require_http_methods(["GET"])
def corridor_config_api(request):
    """
    Return corridor polyline segments with buffers for client overlay.
    """
    try:
        cfg = load_corridor()
        segments = {}
        for key in ["M_J", "J_D", "D_M"]:
            seg = cfg.get(key) if cfg else None
            if seg:
                segments[key] = {
                    "polyline": seg.polyline,
                    "buffer_m": seg.buffer_m,
                }
            else:
                segments[key] = {"polyline": [], "buffer_m": 3000}
        return JsonResponse({"segments": segments})
    except Exception as e:
        logger.exception("Failed to load corridor config")
        return JsonResponse({"segments": {"M_J": {"polyline": [], "buffer_m": 3000}, "J_D": {"polyline": [], "buffer_m": 3000}, "D_M": {"polyline": [], "buffer_m": 3000}}})

def send_message_telegram(request):
    """
    Manual endpoint to send a custom message to Telegram.
    Expects a 'message' parameter in GET or POST.
    """
    message = request.GET.get("message") or request.POST.get("message")
    if not message:
        return JsonResponse({"success": False, "error": "Message is required"}, status=400)
    try:
        send_telegram_message(message)
        logger.info(f"Telegram message sent: {message}")
        return JsonResponse({"success": True})
    except Exception as e:
        logger.exception("Failed to send telegram message")
        return JsonResponse({"success": False, "error": str(e)}, status=500)


@require_http_methods(["GET"])
def vehicle_analytics_api(request, registration_number):
    """
    Fetch vehicle data for analytics.
    
    Data Source Strategy:
    - LIVE (today/no date): Use TWINS API exclusively (up to 24 hours of current data)
    - HISTORICAL (past dates): Use Telemetry API exclusively (for specific date data)
    
    Query Parameters:
    - date: YYYY-MM-DD (optional) - determines which API to use
      - If omitted or today: uses TWINS API
      - If past date: uses Telemetry API
    """
    try:
        from livetracker.data_sources import DataSourceManager
        from datetime import date as _date
        import requests
        
        # Get date from query parameters
        date_param = request.GET.get('date')
        today = _date.today().isoformat()
        
        vehicle_data = []
        data_source_used = None
        requested_date = date_param or today
        is_historical = date_param and date_param != today
        
        # ✅ ROUTING: Historical vs Live
        if is_historical:
            # ========================================
            # HISTORICAL DATA: Use Telemetry API
            # ========================================
            logger.info(f"📅 Historical analytics requested for {registration_number} on {date_param} - using Telemetry API")
            try:
                data_response = DataSourceManager.fetch_historical_data(
                    registration_number=registration_number,
                    start_date=date_param,
                    end_date=date_param
                )
                
                if data_response:
                    vehicle_data = data_response.get('points', [])
                    data_source_used = "Telemetry API (historical)"
                    logger.info(f"✅ Telemetry API: Retrieved {len(vehicle_data)} points for {registration_number} on {date_param}")
                else:
                    logger.warning(f"⚠️ Telemetry API returned no data for {registration_number} on {date_param}")
            except Exception as e:
                logger.error(f"❌ Telemetry API error for {registration_number} on {date_param}: {str(e)}")
        else:
            # ========================================
            # LIVE DATA: Use TWINS API
            # ========================================
            logger.info(f"📊 Live analytics for {registration_number} - using TWINS API")
            try:
                twins_url = settings.TWINS_API_URL
                twins_token = settings.TWINS_API_TOKEN
                
                if twins_url and twins_token:
                    _vendor, _spv = _resolve_twins_project(request.GET.get('spv', ''))
                    import pytz as _pytz_a
                    _ist_a = _pytz_a.timezone('Asia/Kolkata')
                    _now_a = datetime.now(_ist_a)
                    _start_a = _now_a.replace(hour=0, minute=0, second=0, microsecond=0).strftime('%Y-%m-%dT%H:%M:%S')
                    _end_a = _now_a.strftime('%Y-%m-%dT%H:%M:%S')
                    # Use TWINS fetch_geo endpoint for 24hr GPS data (lat/lon/speed/heading)
                    api_url = (
                        f"{twins_url}fetch_geo?spv={_spv}&vendor={_vendor}"
                        f"&page_size=5000&registration_number={registration_number}"
                        f"&start_time={_start_a}&end_time={_end_a}"
                    )
                    response = requests.get(
                        api_url,
                        headers={'Authorization': f'Bearer {twins_token}'},
                        timeout=60
                    )
                    if response.status_code in (400, 403, 404):
                        logger.warning(f"⚠️ TWINS fetch_points returned {response.status_code} for {_vendor}/{_spv}/{registration_number}")
                        data = []
                    else:
                        response.raise_for_status()
                        data = response.json()

                    # Extract points — handle flat list (fetch_points) or dict-with-vehicles (fetch_combined)
                    if isinstance(data, list):
                        twins_points = data
                    elif isinstance(data, dict):
                        if 'vehicles' in data:
                            twins_points = data['vehicles'].get(registration_number, [])
                        elif 'data' in data:
                            twins_points = data['data']
                        elif 'points' in data:
                            twins_points = data['points']
                        else:
                            twins_points = []
                    else:
                        twins_points = []
                    
                    if twins_points:
                        # Map TWINS points to analytics-compatible format
                        for point in twins_points:
                            # Parse coordinates safely
                            lat = float(point.get('latitude', 0)) if point.get('latitude') else None
                            lng = float(point.get('longitude', 0)) if point.get('longitude') else None
                            
                            # Only include points with valid GPS coordinates
                            if not (lat and lng and lat != 0 and lng != 0):
                                continue
                            
                            # Get SOC — EKA vendor uses a/b/c_battery_pack_soc (3-pack)
                            _is_eka = point.get('vendor') == 'eka' or 'a_battery_pack_soc' in point
                            if _is_eka:
                                _soc_vals = [point.get(f) for f in ('a_battery_pack_soc', 'b_battery_pack_soc', 'c_battery_pack_soc') if point.get(f) is not None]
                                _raw_soc = round(sum(float(v) for v in _soc_vals) / len(_soc_vals), 1) if _soc_vals else None
                            else:
                                _raw_soc = point.get('soc') or point.get('battery_soc')
                            soc = int(float(_raw_soc)) if _raw_soc is not None else 0
                            
                            # Get speed safely
                            speed = float(point.get('speed', 0)) if point.get('speed') is not None else 0

                            # Normalize gps_time: TWINS may return it as a Unix int (seconds)
                            import pytz as _pytz
                            _ist = _pytz.timezone('Asia/Kolkata')
                            _raw_gps = point.get('gps_time')
                            if isinstance(_raw_gps, int):
                                _gps_time_iso = datetime.fromtimestamp(_raw_gps, tz=_ist).strftime('%Y-%m-%dT%H:%M:%S')
                            else:
                                _gps_time_iso = _raw_gps  # already ISO string or None
                            _last_connected = _gps_time_iso or point.get('event_datetime')
                            
                            mapped_point = {
                                'registration_number': point.get('registration_number', registration_number),
                                'vehicle_no': point.get('registration_number', registration_number),
                                'latitude': lat,
                                'longitude': lng,
                                'gps_location': f"{lat},{lng}",
                                'gps_time': _gps_time_iso,
                                'event_datetime': point.get('event_datetime'),
                                'last_connected': _last_connected,
                                'heading': float(point.get('head', 0)) if point.get('head') else None,
                                'gps_heading': float(point.get('head', 0)) if point.get('head') else None,
                                'speed': speed,
                                'gps_speed': speed,
                                'soc': soc if soc > 0 else None,  # Only include valid SOC > 0
                                'odometer': float(point.get('odometer', 0)) if point.get('odometer') else None,
                                'altitude': float(point.get('altitude', 0)) if point.get('altitude') else None,
                                'satellites': point.get('satellites'),
                                'accuracy_level': point.get('accuracy_level'),
                                'device_id': point.get('device_id'),
                                'account_name': point.get('account_name'),
                                'spv': point.get('spv'),
                                'vendor': point.get('vendor'),
                                # Determine vehicle_status: use API value first, then charging_status, then speed heuristic
                                'vehicle_status': (
                                    point.get('vehicle_status') or
                                    ('Charging' if point.get('charging_status') == 1 else None) or
                                    ('moving' if speed > 1 else 'stopped')
                                ),
                                'raw': point
                            }
                            vehicle_data.append(mapped_point)
                        
                        if vehicle_data:
                            # ✅ IMPORTANT: Reverse to newest-first order
                            # TWINS API returns points in chronological order (oldest-first)
                            # But analytics functions expect newest-first order for proper time calculations
                            vehicle_data.reverse()
                            data_source_used = "TWINS API (live 24h data)"
                            logger.info(f"✅ TWINS API: Retrieved {len(vehicle_data)} points for {registration_number}")
                        else:
                            logger.warning(f"⚠️ TWINS API returned points but none had valid GPS coordinates")
                    else:
                        logger.warning(f"⚠️ TWINS API returned no points for {registration_number}")
            except Exception as e:
                logger.error(f"❌ TWINS API failed for {registration_number}: {str(e)}")
        
        # Format and return analytics (empty data is OK - analytics service handles it gracefully)
        analytics = format_analytics_response(vehicle_data, registration_number)
        analytics['data_source'] = data_source_used or "No Data Available"
        analytics['requested_date'] = requested_date
        
        logger.info(f"Analytics calculated for {registration_number}: source={analytics['data_source']}, points={analytics.get('data_points_count')}")
        return JsonResponse(analytics)
        
        # Format and return analytics
        analytics = format_analytics_response(vehicle_data, registration_number)
        analytics['data_source'] = data_source_used or "No Data"
        logger.info(f"Analytics calculated for {registration_number}: source={analytics['data_source']}, points={analytics.get('data_points_count')}")
        return JsonResponse(analytics)
        
    except Exception as e:
        logger.exception(f"Vehicle analytics error for {registration_number}: {str(e)}")
        return JsonResponse({
            "vehicle_no": registration_number,
            "data_points_count": 0,
            "message": f"Analytics unavailable: {str(e)}",
            "timestamp": datetime.now().isoformat(),
        }, status=500)


@require_http_methods(["GET"])
def api_vehicle_historical_data(request, registration_number):
    """
    API endpoint to fetch historical vehicle data from Telemetry API.
    
    Query Parameters:
    - start_date: YYYY-MM-DD (required)
    - end_date: YYYY-MM-DD (required)
    - spv: Supplier name (optional, default from settings)
    - vendor: Vendor name (optional, default: intangles)
    
    Returns: JSON array of vehicle points with transformed data
    """
    try:
        from livetracker.data_sources import DataSourceManager
        
        start_date = request.GET.get('start_date')
        end_date = request.GET.get('end_date')
        vendor, spv = _resolve_twins_project(request.GET.get('spv', ''))
        
        if not start_date or not end_date:
            return JsonResponse({
                'error': 'Missing required parameters: start_date and end_date',
                'example': '/api/vehicle/MH18BZ3034/historical/?start_date=2026-01-27&end_date=2026-01-28'
            }, status=400)
        
        # Fetch historical data from Telemetry API
        logger.info(f"Fetching historical data for {registration_number} from {start_date} to {end_date}")
        
        result = DataSourceManager.fetch_historical_data(
            registration_number=registration_number,
            start_date=start_date,
            end_date=end_date,
            spv=spv,
            vendor=vendor
        )
        
        if isinstance(result, dict) and 'points' in result:
            points = result.get('points', [])
            logger.info(f"Returned {len(points)} points for {registration_number}")
            return JsonResponse({
                'registration_number': registration_number,
                'vehicle_no': registration_number,
                'points': points,
                'count': len(points),
                'start_date': start_date,
                'end_date': end_date,
            })
        else:
            logger.warning(f"No data returned for {registration_number}")
            return JsonResponse({
                'registration_number': registration_number,
                'points': [],
                'count': 0,
                'message': 'No data available for the specified date range'
            })
    
    except Exception as e:
        logger.exception(f"Historical data fetch error for {registration_number}: {str(e)}")
        return JsonResponse({
            'error': f'Failed to fetch historical data: {str(e)}',
            'registration_number': registration_number
        }, status=500)


@csrf_exempt
@login_required
@require_http_methods(["GET"])
def get_recent_alerts(request):
    """
    API endpoint to fetch recent alerts (last 5 minutes by default).
    Used for polling and displaying alerts in the frontend.
    """
    try:
        # Get time range from query params (default: last 5 minutes)
        minutes = int(request.GET.get("minutes", 5))
        time_threshold = timezone.now() - timedelta(minutes=minutes)

        # Optional filters
        alert_type = request.GET.get("alert_type")
        vehicle_no = request.GET.get("vehicle_no")
        spv = request.GET.get("spv", "").strip()
        limit = int(request.GET.get("limit", 50))

        # Fetch recent alerts with optional filters
        qs = VehicleAlert.objects.filter(created_at__gte=time_threshold)
        if alert_type:
            qs = qs.filter(alert_type=alert_type)
        if vehicle_no:
            qs = qs.filter(vehicle_no=vehicle_no)
        if spv:
            qs = qs.filter(spv=spv)
        recent_alerts = qs.order_by("-created_at")[: max(1, min(limit, 200))]

        # Convert to list of dicts
        alerts_data = []
        for alert in recent_alerts:
            alerts_data.append(
                {
                    "id": alert.id,
                    "vehicle_id": alert.vehicle_id,
                    "vehicle_no": alert.vehicle_no,
                    "driver_name": alert.driver_name,
                    "geofence_name": alert.geofence_name,
                    "gps_location": alert.gps_location,
                    "lat": alert.lat,
                    "lon": alert.lon,
                    "soc": alert.soc,
                    "alert_type": alert.alert_type,
                    "text": alert.text,
                    "created_at": (
                        alert.created_at.isoformat() if alert.created_at else None
                    ),
                }
            )

        return JsonResponse(
            {"success": True, "count": len(alerts_data), "alerts": alerts_data}
        )

    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=500)


@csrf_exempt
@login_required
@require_http_methods(["POST"])
def mark_alert_seen(request, alert_id):
    """
    Mark an alert as seen/acknowledged.
    """
    try:
        alert = VehicleAlert.objects.get(id=alert_id)
        # You can add a 'seen' field to the model if needed
        return JsonResponse(
            {"success": True, "message": f"Alert {alert_id} marked as seen"}
        )
    except VehicleAlert.DoesNotExist:
        return JsonResponse({"success": False, "error": "Alert not found"}, status=404)
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=500)


@login_required
@require_http_methods(["GET"])
def reverse_geocode(request):
    """
    Proxy endpoint for reverse geocoding using Nominatim.
    Solves CORS issues and provides proper User-Agent header.
    Includes caching to reduce API calls and improve response times.
    
    Usage: GET /livetracker/api/geocode/?lat=21.43014&lon=74.98326
    """
    try:
        lat = request.GET.get('lat')
        lon = request.GET.get('lon')
        
        if not lat or not lon:
            return JsonResponse(
                {"success": False, "error": "Missing lat or lon parameters"}, 
                status=400
            )
        
        # Validate coordinates
        try:
            lat_float = float(lat)
            lon_float = float(lon)
            
            if lat_float < -90 or lat_float > 90:
                return JsonResponse(
                    {"success": False, "error": "Latitude must be between -90 and 90"}, 
                    status=400
                )
            
            if lon_float < -180 or lon_float > 180:
                return JsonResponse(
                    {"success": False, "error": "Longitude must be between -180 and 180"}, 
                    status=400
                )
                
        except ValueError:
            return JsonResponse(
                {"success": False, "error": "Invalid coordinate format"}, 
                status=400
            )
        
        # Round coordinates to 4 decimal places for cache key (~11 meters precision)
        # This helps reduce unique API calls for nearby coordinates
        cache_lat = round(lat_float, 4)
        cache_lon = round(lon_float, 4)
        cache_key = f"geocode_{cache_lat}_{cache_lon}"
        
        # Check cache first
        cached_result = cache.get(cache_key)
        if cached_result:
            # logger.info(f"✅ Geocoding cache hit: lat={lat_float}, lon={lon_float}")
            return JsonResponse(cached_result)
        
        # Make request to Nominatim with proper headers
        nominatim_url = f"https://nominatim.openstreetmap.org/reverse"
        params = {
            'format': 'json',
            'lat': lat_float,
            'lon': lon_float,
            'zoom': 18,
            'addressdetails': 1
        }
        
        # Nominatim requires a User-Agent header as per their usage policy
        headers = {
            'Accept': 'application/json',
            'User-Agent': 'LiveTracker'
        }
        
        # logger.info(f"🌐 Geocoding request: lat={lat_float}, lon={lon_float}")
        
        # Respect Nominatim's rate limit (1 request per second)
        _wait_for_rate_limit()
        
        # Make request with timeout (increased to 15 seconds)
        # Also add retry logic with exponential backoff
        max_retries = 2
        retry_delay = 1  # seconds
        
        for attempt in range(max_retries + 1):
            try:
                response = requests.get(
                    nominatim_url, 
                    params=params, 
                    headers=headers,
                    timeout=15  # Increased from 10 to 15 seconds
                )
                break  # Success, exit retry loop
            except requests.exceptions.Timeout:
                if attempt < max_retries:
                    # logger.warning(f"⚠️ Geocoding timeout (attempt {attempt + 1}/{max_retries + 1}), retrying in {retry_delay}s...")
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                    continue
                else:
                    raise  # Re-raise on final attempt
        
        if response.status_code == 200:
            data = response.json()
            
            # Check for API error
            if 'error' in data:
                logger.warning(f"⚠️ Nominatim error: {data['error']}")
                return JsonResponse(
                    {"success": False, "error": data['error']}, 
                    status=400
                )
            
            # Return formatted address
            address = data.get('display_name', 'Address unavailable')
            logger.info(f"✅ Geocoding success: {address[:50]}...")
            
            result = {
                "success": True,
                "address": address,
                "full_data": data
            }
            
            # Cache the successful result
            cache.set(cache_key, result, GEOCODE_CACHE_TIMEOUT)
            
            return JsonResponse(result)
            
        elif response.status_code == 403:
            logger.error(f"❌ Nominatim 403 Forbidden - Rate limit or blocked")
            # Return fallback with coordinates instead of error
            return JsonResponse(
                {"success": True, "address": f"{lat}, {lon}", "fallback": True}, 
                status=200
            )
            
        elif response.status_code == 429:
            logger.error(f"❌ Nominatim 429 Too Many Requests")
            # Return fallback with coordinates instead of error
            return JsonResponse(
                {"success": True, "address": f"{lat}, {lon}", "fallback": True}, 
                status=200
            )
            
        else:
            logger.error(f"❌ Nominatim error: {response.status_code}")
            # Return fallback with coordinates instead of error
            return JsonResponse(
                {"success": True, "address": f"{lat}, {lon}", "fallback": True}, 
                status=200
            )
        
    except requests.exceptions.Timeout:
        logger.error("❌ Geocoding timeout")
        # Return fallback with coordinates
        return JsonResponse(
            {"success": True, "address": f"{lat}, {lon}", "fallback": True}, 
            status=200
        )
        
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Geocoding request error: {str(e)}")
        # Return fallback with coordinates instead of error
        return JsonResponse(
            {"success": True, "address": f"{lat}, {lon}", "fallback": True}, 
            status=200
        )
        
    except Exception as e:
        logger.error(f"❌ Geocoding error: {str(e)}")
        # Return fallback with coordinates
        return JsonResponse(
             {"success": True, "address": f"{lat}, {lon}", "fallback": True}, 
            status=200
        )


@login_required
@require_http_methods(["POST"])
@csrf_exempt
def get_drivers_bulk(request):
    """
    BULK API endpoint to get driver details for multiple vehicles in one call.
    Replaces slow individual API calls with fast batch lookup.
    
    Usage: POST /livetracker/api/drivers/bulk/
    Body: {"registration_numbers": ["TN01AB1234", "TN01CD5678", ...]}
    
    Returns: {
        "TN01AB1234": {"driver_name": "John Doe", "driver_phone": "9876543210", "has_driver": true},
        "TN01CD5678": {"driver_name": "N/A", "driver_phone": "N/A", "has_driver": false},
        ...
    }
    """
    try:
        import json
        from roster.services.driverService import get_all_drivers_bulk
        
        # Parse request body
        body = json.loads(request.body)
        registration_numbers = body.get('registration_numbers', [])
        
        if not registration_numbers:
            return JsonResponse({'error': 'No registration numbers provided'}, status=400)
        
        # Use bulk service function (cached and optimized)
        drivers_data = get_all_drivers_bulk(registration_numbers)
        
        return JsonResponse(drivers_data)
        
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Error in bulk driver fetch: {str(e)}", exc_info=True)
        return JsonResponse({'error': 'Service error'}, status=500)


def process_telemetry_to_timeline(multi_day_data, engine: str | None = 'timebox'):
    """
    Process multi-day telemetry data into timeline format for the UI
    Uses multi-day data for robust direction calculation but only shows today's phases in timeline
    
    Args:
        multi_day_data: Dict with vehicle_no as key and dict containing all_data, today_data, yesterday_data
        
    Returns:
        Dict: Timeline data in the format expected by the UI
    """
    try:
        # Use timebox engine for processing
        from .timebox import build_timebox_for_vehicle as timebox_build
        
        timeline_data = {}
        today = datetime.now().strftime("%Y-%m-%d")
        
        for vehicle_no, vehicle_datasets in multi_day_data.items():
            if not vehicle_datasets or not vehicle_datasets.get('all_data'):
                continue
                
            try:
                # Use ALL data (yesterday + today) for direction calculation
                all_telemetry = vehicle_datasets['all_data']
                today_telemetry = vehicle_datasets['today_data']
                
                if not all_telemetry:
                    continue
                
                # Process with all data to get robust direction using timebox engine
                vehicle_timeline = timebox_build(all_telemetry)
                
                if vehicle_timeline:
                    # Keep direction from multi-day analysis and use complete timeline (multi-day).
                    # Flow enforcement for future boxes happens in the view mapping.
                    direction = vehicle_timeline.get('direction')
                    full_timeline = vehicle_timeline.get('timeline', [])
                    # Add engine-specific extras
                    extra = {'engine': 'timebox'}
                    # expose latest and current trip durations if present
                    ltd = vehicle_timeline.get('latest_trip_duration_seconds')
                    if ltd is not None:
                        extra['latest_trip_duration_seconds'] = ltd
                    ctd = vehicle_timeline.get('current_trip_duration_seconds')
                    if ctd is not None:
                        extra['current_trip_duration_seconds'] = ctd
                    
                    # Add formatted display timestamps and duration for all phases
                    try:
                        import pytz
                        ist_tz = pytz.timezone('Asia/Kolkata')
                        
                        for t in full_timeline:
                            # Add duration in HH:MM format
                            try:
                                dur = t.get('duration_seconds')
                                if isinstance(dur, (int, float)) and dur is not None:
                                    hh = int(dur) // 3600
                                    mm = (int(dur) % 3600) // 60
                                    t['duration_hhmm'] = f"{hh:02d}:{mm:02d}"
                                else:
                                    t['duration_hhmm'] = None
                            except Exception:
                                t['duration_hhmm'] = None
                            
                            # Add formatted display timestamps with date for all phases
                            try:
                                # Format start time
                                start_str = t.get('start')
                                if start_str and isinstance(start_str, str):
                                    start_dt = datetime.fromisoformat(start_str.replace('Z', '+00:00')).astimezone(ist_tz)
                                    t['display_start'] = start_dt.strftime('%Y-%m-%d %H:%M')
                                    if 'time' not in t:
                                        t['time'] = start_dt.strftime('%H:%M')
                                
                                # Format end time  
                                end_str = t.get('end')
                                if end_str and isinstance(end_str, str):
                                    end_dt = datetime.fromisoformat(end_str.replace('Z', '+00:00')).astimezone(ist_tz)
                                    t['display_end'] = end_dt.strftime('%Y-%m-%d %H:%M')
                                    if 'end_time' not in t:
                                        t['end_time'] = end_dt.strftime('%H:%M')
                            except Exception as e:
                                logger.debug(f"Error formatting timestamps for phase: {e}")
                                pass
                    except Exception as e:
                        logger.error(f"Error in timeline post-processing: {e}")
                    
                    # Create timeline data with complete journey (all phases)
                    timeline_data[vehicle_no] = {
                        'direction': direction,
                        'timeline': full_timeline,
                        'vehicle_no': vehicle_no,
                        **extra,
                    }
            except Exception as e:
                logger.error(f"Error processing timeline for {vehicle_no}: {e}")
                continue
        return timeline_data
    except Exception as e:
        logger.error(f"Error in process_telemetry_to_timeline: {e}")
        return {}


@csrf_exempt
@login_required
@require_http_methods(["POST"])
def report_deviation_alert(request):
    """
    Create a route deviation alert from client-side detection.
    Expects JSON body with: vehicle_no, lat, lon, distance_m, message, soc (optional), vehicle_id (optional)
    """
    try:
        import json
        payload = json.loads(request.body.decode("utf-8")) if request.body else {}
        vehicle_no = payload.get("vehicle_no")
        lat = payload.get("lat")
        lon = payload.get("lon")
        distance_m = payload.get("distance_m")
        message = payload.get("message") or "Route deviation detected"
        soc = payload.get("soc")
        vehicle_id = payload.get("vehicle_id")
        spv = payload.get("spv", "")

        if not vehicle_no or lat is None or lon is None:
            return JsonResponse({"error": "vehicle_no, lat and lon are required"}, status=400)

        alert_text = f"Deviation {int(distance_m) if distance_m is not None else ''}m – {message}"

        alert = VehicleAlert.objects.create(
            vehicle_id=str(vehicle_id) if vehicle_id is not None else None,
            vehicle_no=vehicle_no,
            driver_name=None,
            geofence_name="Route Corridor",
            gps_location=f"{lat},{lon}",
            lat=lat,
            lon=lon,
            soc=int(soc) if soc is not None else None,
            alert_type="route_deviation",
            text=alert_text,
            priority="high",
            spv=spv,
        )

        try:
            send_telegram_message(f"⚠️ Route Deviation\nVehicle: {vehicle_no}\nDistance: {int(distance_m) if distance_m is not None else 'N/A'} m\nLocation: {lat:.5f}, {lon:.5f}")
        except Exception:
            logger.warning("Telegram send failed for deviation alert", exc_info=True)

        return JsonResponse({"success": True, "alert_id": alert.id})
    except Exception as e:
        logger.exception("Failed to create deviation alert")
        return JsonResponse({"error": str(e)}, status=500)


def fetch_day(vehicle_no, start_date, end_date):
    """
    Fetch vehicle data for a date range using Telemetry API via DataSourceManager.
    
    This function replaces the deprecated SmartFastAPI with the new Telemetry API.
    
    Args:
        vehicle_no: Vehicle registration number (can be None to fetch all vehicles)
        start_date: Start date as YYYY-MM-DD string
        end_date: End date as YYYY-MM-DD string
    
    Returns:
        List of vehicle data points transformed to SmartFastAPI-compatible format
    """
    try:
        logger.info(f"fetch_day called for {vehicle_no} ({start_date} to {end_date})")
        
        if vehicle_no is None:
            # Fetch all vehicles for the date range using fetch_geo API
            logger.info(f"Fetching all vehicles data for {start_date} to {end_date}")
            try:
                start_dt = datetime.strptime(start_date, '%Y-%m-%d')
                # end_date is exclusive, so we need to parse it as-is (no +1 day)
                # because it's already the day AFTER the data we want
                end_dt = datetime.strptime(end_date, '%Y-%m-%d')
                
                vehicles_data = DataSourceManager.fetch_fetch_geo_data(
                    start_time=start_dt,
                    end_time=end_dt,
                    batch_window_hours=1
                )
                
                # Flatten vehicles data to list of points
                all_points = []
                for vehicle_no_key, points in vehicles_data.items():
                    for point in points:
                        all_points.append({
                            'vehicle_no': vehicle_no_key,
                            'registration_number': vehicle_no_key,
                            'latitude': point.get('latitude'),
                            'longitude': point.get('longitude'),
                            'vehicle_status': point.get('vehicle_status', 'traveling'),
                            'gps_time': point.get('gps_time'),
                            'event_datetime': point.get('event_datetime'),
                            'last_connected': point.get('gps_time'),
                            'speed': point.get('speed', 0),
                            'odometer': point.get('odometer', 0),
                            'gps_location': f"{point.get('latitude', 0)},{point.get('longitude', 0)}",
                        })
                
                logger.info(f"Successfully fetched {len(all_points)} total points for all vehicles")
                return all_points
                
            except Exception as e:
                logger.error(f"Error fetching all vehicles from fetch_geo API: {e}")
                return []
        else:
            # Fetch specific vehicle using Telemetry API
            logger.info(f"Fetching vehicle {vehicle_no} data from {start_date} to {end_date}")
            
            result = DataSourceManager.fetch_historical_data(
                registration_number=vehicle_no,
                start_date=start_date,
                end_date=end_date
            )
            
            if isinstance(result, dict) and 'points' in result:
                points = result.get('points', [])
                logger.info(f"Successfully fetched {len(points)} points for {vehicle_no}")
                
                # Ensure points are in the expected format
                formatted_points = []
                for point in points:
                    formatted_points.append({
                        'vehicle_no': vehicle_no,
                        'registration_number': vehicle_no,
                        'latitude': point.get('latitude'),
                        'longitude': point.get('longitude'),
                        'vehicle_status': point.get('vehicle_status', 'traveling'),
                        'gps_time': point.get('gps_time'),
                        'event_datetime': point.get('event_datetime'),
                        'last_connected': point.get('last_connected') or point.get('gps_time'),
                        'speed': point.get('speed', 0),
                        'odometer': point.get('odometer', 0),
                        'gps_location': f"{point.get('latitude', 0)},{point.get('longitude', 0)}",
                    })
                return formatted_points
            else:
                logger.warning(f"No data returned for {vehicle_no}")
                return []
    
    except Exception as e:
        logger.error(f"Error in fetch_day for {vehicle_no}: {e}")
        return []


def fetch_all_vehicles_from_api():
    """Fetch ALL vehicle data from API for the last 2 days"""
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    
    logger.info(f"Fetching all vehicles data from API for {yesterday} to {today}")
    
    # Fetch data for ALL vehicles (don't specify vehicle_no parameter)
    all_data = fetch_day(None, yesterday, today)  # None means fetch all vehicles
    
    if all_data and isinstance(all_data, list):
        logger.info(f"Successfully fetched {len(all_data)} records from API")
        return all_data
    else:
        logger.warning("No data received from API")
        return []


def auto_sync_vehicles_from_api(api_data):
    """Automatically sync vehicles from API data to database"""
    if not api_data:
        return 0
    
    # Extract unique vehicle numbers from API data
    api_vehicles = set()
    for record in api_data:
        vehicle_no = record.get('vehicle_no')
        if vehicle_no:
            api_vehicles.add(vehicle_no)
    
    logger.info(f"Found {len(api_vehicles)} unique vehicles in API data")
    
    # Get existing vehicles from database
    existing_vehicles = set(Vehicle.objects.values_list('registration_number', flat=True))
    
    # Find vehicles that need to be added
    missing_vehicles = api_vehicles - existing_vehicles
    
    if not missing_vehicles:
        logger.info("All vehicles from API are already in database")
        return 0
    
    logger.info(f"Auto-syncing {len(missing_vehicles)} new vehicles to database")
    
    # Get default model type for new vehicles
    try:
        from dashboard.models import ModelType
        default_model_type = ModelType.objects.first()
        if not default_model_type:
            logger.error("No ModelType found in database. Cannot create new vehicles.")
            return 0
    except Exception as e:
        logger.error(f"Error getting ModelType: {e}")
        return 0
    
    # Create new vehicle records
    new_vehicles = []
    for vehicle_no in missing_vehicles:
        new_vehicles.append(
            Vehicle(
                registration_number=vehicle_no,
                model=default_model_type
            )
        )
    
    try:
        # Bulk create new vehicles
        created_vehicles = Vehicle.objects.bulk_create(new_vehicles, ignore_conflicts=True)
        logger.info(f"Successfully auto-synced {len(created_vehicles)} new vehicles: {', '.join(missing_vehicles)}")
        return len(created_vehicles)
    except Exception as e:
        logger.error(f"Error creating new vehicles: {e}")
        return 0


def process_api_data_to_timeline(api_data, vehicle_numbers, engine: str | None = None):
    """
    Process raw API data directly to timeline format
    """
    if not api_data:
        return {}
    
    # Organize API data by vehicle
    vehicles_data = {}
    for record in api_data:
        vehicle_no = record.get('vehicle_no')
        if vehicle_no in vehicle_numbers:  # Only process vehicles in our database
            if vehicle_no not in vehicles_data:
                vehicles_data[vehicle_no] = []
            vehicles_data[vehicle_no].append(record)
    
    # Sort data by timestamp for each vehicle
    for vehicle_no in vehicles_data:
        vehicles_data[vehicle_no] = sorted(
            vehicles_data[vehicle_no], 
            key=lambda x: x.get('last_connected', '')
        )
    
    # Convert to the same format as multi_day_data for timeline processing
    multi_day_format = {}
    today = datetime.now().strftime("%Y-%m-%d")
    
    for vehicle_no, records in vehicles_data.items():
        today_data = [r for r in records if r.get('last_connected', '').startswith(today)]
        
        multi_day_format[vehicle_no] = {
            'all_data': records,
            'today_data': today_data,
            'yesterday_data': [r for r in records if not r.get('last_connected', '').startswith(today)]
        }
    
    # Process using existing timeline processing function
    return process_telemetry_to_timeline(multi_day_format, engine=engine)

def get_multi_day_data(vehicle_numbers, days_back=1):
    """Fetch data for multiple days for all vehicles to get complete trip data"""
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    
    multi_day_data = {}
    for vehicle_no in vehicle_numbers:
        # Fetch data for the date range (yesterday to today)
        range_data = fetch_day(vehicle_no, yesterday, today)
        if range_data and isinstance(range_data, list):
            # Sort by timestamp (using last_connected field)
            sorted_data = sorted(range_data, key=lambda x: x.get('last_connected', ''))
            
            # Separate data by date for processing
            today_data = []
            yesterday_data = []
            
            for point in sorted_data:
                timestamp = point.get('last_connected', '')
                if timestamp.startswith(today):
                    today_data.append(point)
                elif timestamp.startswith(yesterday):
                    yesterday_data.append(point)
            
            # Store both datasets - all data for direction, today for display
            multi_day_data[vehicle_no] = {
                'all_data': sorted_data,  # For direction calculation
                'today_data': today_data,  # For timeline display
                'yesterday_data': yesterday_data  # For context if needed
            }
        else:
            multi_day_data[vehicle_no] = {
                'all_data': [],
                'today_data': [],
                'yesterday_data': []
            }
    
    return multi_day_data

@require_http_methods(["POST"])
@csrf_exempt
@login_required
def submit_feedback(request):
    """Handle feedback submission from LiveTracker with optional screenshot"""
    import json
    from .models.livetracker_feedback import Feedback
    
    try:
        # Check if it's FormData (with file) or JSON
        if request.content_type and 'multipart/form-data' in request.content_type:
            # FormData submission (with screenshot)
            feedback_type = request.POST.get('feedback_type')
            title = request.POST.get('title', '').strip()
            description = request.POST.get('description', '').strip()
            page_url = request.POST.get('page_url', request.META.get('HTTP_REFERER', ''))
            browser = request.POST.get('browser', '')
            os = request.POST.get('os', '')
            device = request.POST.get('device', '')
            screenshot = request.FILES.get('screenshot')
        else:
            # JSON submission (without screenshot)
            data = json.loads(request.body)
            feedback_type = data.get('feedback_type')
            title = data.get('title', '').strip()
            description = data.get('description', '').strip()
            page_url = data.get('page_url', request.META.get('HTTP_REFERER', ''))
            browser = data.get('browser', '')
            os = data.get('os', '')
            device = data.get('device', '')
            screenshot = None
        
        # Validation
        if not feedback_type or feedback_type not in ['bug', 'feature']:
            return JsonResponse({
                'success': False,
                'error': 'Invalid feedback type'
            }, status=400)
        
        if not title:
            return JsonResponse({
                'success': False,
                'error': 'Title is required'
            }, status=400)
        
        if not description:
            return JsonResponse({
                'success': False,
                'error': 'Description is required'
            }, status=400)
        
        # Create feedback entry
        feedback = Feedback.objects.create(
            feedback_type=feedback_type,
            title=title,
            description=description,
            reported_by=request.user,
            page_url=page_url,
            browser=browser,
            os=os,
            device=device,
            status='open',
            screenshot=screenshot if screenshot else None
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Feedback submitted successfully!',
            'feedback_id': feedback.id,
            'has_screenshot': bool(screenshot)
        })
        
    except Exception as e:
        logger.error(f"Error submitting feedback: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': 'An error occurred while submitting feedback'
        }, status=500)





@login_required
@require_http_methods(["GET"])
def download_charging_report(request, registration_number):
    """
    Download CSV report of charging sessions for a vehicle (optionally for a date).

    Detection logic (vehicle_status-based, accurate method):
    - Detects charging sessions using vehicle_status field (primary indicator of charging state)
    - Groups consecutive telemetry points where vehicle_status contains 'charging' (case-insensitive)
    - Merges sessions with gaps < 5 minutes
    - Calculates SOC gain where available
    - Supports both live and historical data (date parameter optional)
    
    This approach is more reliable than SOC-trend analysis as it uses the vehicle's
    actual reported status rather than derived indicators.
    """
    import logging
    from livetracker.data_sources import DataSourceManager, detect_charging_sessions
    from datetime import datetime
    
    logger = logging.getLogger("livetracker.charging_report")
    date = request.GET.get("date")
    
    try:
        # Fetch historical data from Telemetry API (if date provided) or latest data
        logger.info(f"Fetching charging data for {registration_number} on {date if date else 'today'}")
        
        if date:
            result = DataSourceManager.fetch_historical_data(
                registration_number=registration_number,
                start_date=date,
                end_date=date
            )
        else:
            result = DataSourceManager.fetch_single_vehicle(registration_number)
        
        points = result.get('points', []) if isinstance(result, dict) else []
        logger.info(f"Fetched {len(points)} telemetry points for {registration_number}")

        # Detect charging sessions using improved vehicle_status-based method
        charging_sessions = detect_charging_sessions(points)
        
        # Generate CSV with session details
        import csv
        import io
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Start Time', 'End Time', 'Duration (minutes)', 'Start SOC (%)', 'End SOC (%)', 'SOC Gain (%)'])
        
        for session in charging_sessions:
            writer.writerow([
                session.get('start_time', ''),
                session.get('end_time', ''),
                round(session.get('duration', 0), 2),
                round(session.get('start_soc', 0), 2),
                round(session.get('end_soc', 0), 2),
                round(session.get('soc_gain', 0), 2)
            ])
        
        csv_data = output.getvalue()
        response = HttpResponse(csv_data, content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="charging_report_{registration_number}_{date or "latest"}.csv"'
        logger.info(f"Generated charging report with {len(charging_sessions)} sessions")
        return response
        
    except Exception as e:
        logger.error(f"Error generating charging report: {str(e)}", exc_info=True)
        return HttpResponse(f"Error generating report: {str(e)}", status=500)

@login_required
@require_http_methods(["GET"])
def download_stoppage_report(request, registration_number):
    """
        Download CSV report of stoppage sessions for a vehicle (optionally for a date).

        New detection logic (time-sorted, speed-driven):
        - Sort points by timestamp (ascending)
        - Start when speed is exactly 0 (allowing noise),
            continue while speed <= 5 km/h
        - End when speed > 5 km/h
    """
    import logging
    from livetracker.data_sources import DataSourceManager, detect_stoppage_sessions
    from datetime import datetime
    
    logger = logging.getLogger("livetracker.stoppage_report")
    date = request.GET.get("date")
    
    try:
        # Fetch historical data from Telemetry API
        logger.info(f"Fetching stoppage data for {registration_number} on {date}")
        
        if date:
            result = DataSourceManager.fetch_historical_data(
                registration_number=registration_number,
                start_date=date,
                end_date=date
            )
        else:
            result = DataSourceManager.fetch_single_vehicle(registration_number)
        
        points = result.get('points', []) if isinstance(result, dict) else []
        logger.info(f"Fetched {len(points)} telemetry points for {registration_number}")

        # Use middleware utility for detection
        stoppage_sessions = detect_stoppage_sessions(points)

        # Generate CSV
        import csv
        import io
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Start Time', 'End Time', 'Duration (minutes)', 'Min Speed (km/h)', 'Max Speed (km/h)'])

        for session in stoppage_sessions:
            writer.writerow([
                session.get('start_time', ''),
                session.get('end_time', ''),
                round(session.get('duration', 0), 2),
                round(session.get('min_speed', 0), 2),
                round(session.get('max_speed', 0), 2),
            ])
        
        csv_data = output.getvalue()
        response = HttpResponse(csv_data, content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="stoppage_report_{registration_number}.csv"'
        logger.info(f"Generated stoppage report with {len(stoppage_sessions)} sessions")
        return response
        
    except Exception as e:
        logger.error(f"Error generating stoppage report: {str(e)}", exc_info=True)
        return HttpResponse(f"Error generating report: {str(e)}", status=500)


@login_required
@require_http_methods(["GET"])
def event_page_view(request):
    """
    Event page view - displays webhook events fetched from the event page API.
    """
    from .services.event_page_service import fetch_events
    
    # Fetch events from the API
    events_data = fetch_events(limit=50,)
    
    # Log the response to console
    if events_data:
        logger.info(f"Event page data fetched successfully: {events_data}")
    else:
        logger.warning("Failed to fetch event page data")
    
    context = {
        'events_data': events_data,
    }
    return render(request, 'livetracker/event_page.html', context)


@login_required
@require_http_methods(["GET"])
def smartfastapi_proxy(request):
    """
    Proxy endpoint for SmartFastAPI calls.
    Keeps credentials secure on the backend.
    Returns raw API response directly (not wrapped).
    """
    endpoint = request.GET.get('endpoint')  # e.g., 'vehicleiplt'
    
    if not endpoint:
        return JsonResponse({'error': 'Missing endpoint parameter'}, status=400)
    
    # Build params from request
    params = {}
    if request.GET.get('vehicle_no'):
        params['vehicle_no'] = request.GET.get('vehicle_no')
    if request.GET.get('date'):
        params['date'] = request.GET.get('date')
    if request.GET.get('limit'):
        params['limit'] = request.GET.get('limit')
    
    try:
        # Make request to SmartFastAPI using backend credentials
        base_url = settings.SMARTFASTAPI_DOMAIN
        api_key = getattr(settings, 'SMARTFASTAPI_ACCESS_KEY', '')
        
        logger.info(f"SmartFastAPI Proxy: {endpoint} with params: {params}")
        
        url = f"{base_url}/{endpoint}"
        
        # Use x-api-key header (consistent with other endpoints)
        headers = {}
        if api_key:
            headers['x-api-key'] = api_key
        
        response = requests.get(
            url,
            params=params,
            headers=headers,
            timeout=20
        )
        
        response.raise_for_status()
        data = response.json()
        
        # Return raw data directly (JavaScript expects array, not wrapped object)
        return JsonResponse(data, safe=False)

    except requests.Timeout:
        logger.error("SmartFastAPI proxy timeout")
        return JsonResponse({'error': 'Request timeout'}, status=504)


def _resolve_twins_project(spv_param):
    """Map a frontend project key to the correct TWINS vendor+spv pair."""
    mapping = {
        'ULTRATECH': (getattr(settings, 'TWINS_VENDOR',        'intangles'),
                      getattr(settings, 'TWINS_SPV',           'ultratech')),
        'UMT':       (getattr(settings, 'TWINS_UMT_VENDOR',    'intangles'),
                      getattr(settings, 'TWINS_UMT_SPV',       'UMT')),
        'MBMT':      (getattr(settings, 'TWINS_MBMT_VENDOR',   'intangles'),
                      getattr(settings, 'TWINS_MBMT_SPV',      'MBMT')),
        'NAGPUR':      (getattr(settings, 'TWINS_NAGPUR_VENDOR',      'eka'),
                        getattr(settings, 'TWINS_NAGPUR_SPV',         'nagpur')),
        'VECV':        (getattr(settings, 'TWINS_VECV_VENDOR',        'intangles'),
                        getattr(settings, 'TWINS_VECV_SPV',           'VECV')),
        'STAR_CEMENT': (getattr(settings, 'TWINS_STAR_CEMENT_VENDOR', 'propel'),
                        getattr(settings, 'TWINS_STAR_CEMENT_SPV',    'STAR_CEMENT')),
        'JM_BAXI':     (getattr(settings, 'TWINS_JM_BAXI_VENDOR',     'eim'),
                        getattr(settings, 'TWINS_JM_BAXI_SPV',        'JM_BAXI')),
        'GTI':         (getattr(settings, 'TWINS_GTI_VENDOR',        'eim'),
                        getattr(settings, 'TWINS_GTI_SPV',           'GTI')),
    }
    key = (spv_param or '').strip().upper() or 'ULTRATECH'
    return mapping.get(key, mapping['ULTRATECH'])


@login_required
@require_http_methods(["GET"])
def twins_api_proxy(request):
    """
    Proxy endpoint for TWINS API to avoid CORS and CSP issues.
    Fetches latest vehicle points with configurable limit.
    
    URL: /livetracker/api/twins/latest-points/
    Params: ?limit=1 (optional, default 5)
    
    Returns: { vendor_filter, total_vehicles, vehicles: { reg: [points] } }
    """
    try:
        _twins_limit = getattr(settings, 'TWINS_LIMIT', 5)
        limit = request.GET.get('limit', _twins_limit)
        
        # Validate limit
        try:
            limit = int(limit)
            limit = max(1, min(limit, _twins_limit))  # Clamp between 1 and configured max
        except (ValueError, TypeError):
            limit = _twins_limit
        
        twins_url = settings.TWINS_API_URL
        twins_token = settings.TWINS_API_TOKEN
        
        if not twins_url or not twins_token:
            logger.error("❌ TWINS API credentials not configured")
            return JsonResponse(
                {'error': 'TWINS API not configured'},
                status=500
            )
        
        vendor, spv = _resolve_twins_project(request.GET.get('spv', ''))

        # 'eim' only exposes /latest_points (no spv filter, no combined endpoint) and
        # mixes all its SPVs (JM_BAXI, GTI, ...) together — filter by spv after fetching.
        if vendor == 'eim':
            api_url = f"{twins_url}latest_points?vendor={vendor}"
        else:
            api_url = f"{twins_url}latest_points_combined?vendor={vendor}&spv={spv}&limit={limit}"

        logger.info(f"🔄 Proxying TWINS API request: vendor={vendor}, spv={spv}, limit={limit}")
        
        # Make request to TWINS API with token
        response = requests.get(
            api_url,
            headers={
                'Authorization': f'Bearer {twins_token}',
            },
            timeout=20  # 20 second timeout
        )
        
        if response.status_code == 400:
            logger.warning(f"⚠️ TWINS API returned 400 for vendor={vendor} spv={spv} — project may not be available")
            return JsonResponse({'total_vehicles': 0, 'vehicles': {}, 'vendor_filter': vendor}, safe=True)

        response.raise_for_status()

        data = response.json()

        vehicles_raw = data.get('vehicles', {})

        # 'eim' /latest_points returns all its SPVs mixed together — keep only
        # vehicles whose latest point matches the requested spv (e.g. JM_BAXI, GTI).
        if vendor == 'eim':
            vehicles_raw = {
                reg: pts for reg, pts in vehicles_raw.items()
                if isinstance(pts, list) and pts and pts[0].get('spv') == spv
            }
            data['vehicles'] = vehicles_raw
            data['total_vehicles'] = len(vehicles_raw)

        logger.info(f"✅ TWINS API response: {data.get('total_vehicles', '?')} vehicles (spv={spv})")

        # Normalize gps_time in every point to IST ISO string so the
        # frontend hover card and sidebar show the same time as playback.
        import pytz as _pytz
        _ist_tz = _pytz.timezone('Asia/Kolkata')
        for reg, pts in vehicles_raw.items():
            if not isinstance(pts, list):
                continue
            for pt in pts:
                raw_gps = pt.get('gps_time')
                if isinstance(raw_gps, int):
                    pt['gps_time'] = datetime.fromtimestamp(raw_gps, tz=_ist_tz).strftime('%Y-%m-%dT%H:%M:%S')
                pt['last_connected'] = pt.get('gps_time') or pt.get('event_datetime')
                # Infer vehicle_status for vendors that don't set it (e.g. Star Cement / propel)
                if not pt.get('vehicle_status'):
                    spd = float(pt.get('speed') or 0)
                    if pt.get('charging_status') == 1:
                        pt['vehicle_status'] = 'Charging'
                    elif spd > 1:
                        pt['vehicle_status'] = 'Moving'
                    elif pt.get('ignition_status') == 1:
                        pt['vehicle_status'] = 'Idling'
                    else:
                        pt['vehicle_status'] = 'Stopped'

        return JsonResponse(data, safe=True)
        
    except requests.Timeout:
        logger.error("⏱️ TWINS API proxy timeout")
        return JsonResponse({'error': 'TWINS API timeout'}, status=504)
    except requests.RequestException as e:
        logger.error(f"❌ TWINS API proxy error: {str(e)}")
        return JsonResponse(
            {'error': f'TWINS API error: {str(e)}'},
            status=502
        )
    except ValueError as e:
        logger.error(f"❌ TWINS API response parsing error: {str(e)}")
        return JsonResponse(
            {'error': 'Invalid TWINS API response'},
            status=502
        )
    except Exception as e:
        logger.error(f"❌ TWINS API proxy error: {str(e)}")
        return JsonResponse(
            {'error': 'Internal server error'},
            status=500
        )


def _telemetry_fallback_24hr(registration_number, vendor, spv):
    """
    Fallback for twins_24hr_route_proxy when TWINS fetch_points has no data.
    Uses DataSourceManager.fetch_historical_data (Telemetry API) for today's date.
    Returns a JsonResponse in the same {points: [...]} format.
    """
    try:
        from livetracker.data_sources import DataSourceManager
        import pytz as _pytz_fb
        _ist_fb = _pytz_fb.timezone('Asia/Kolkata')
        today_str = datetime.now(_ist_fb).strftime('%Y-%m-%d')

        logger.info(f"🔄 Telemetry fallback for {registration_number} ({vendor}/{spv}) on {today_str}")

        result = DataSourceManager.fetch_historical_data(
            registration_number=registration_number,
            start_date=today_str,
            end_date=today_str,
            spv=spv,
            vendor=vendor,
        )

        points = result.get('points', []) if isinstance(result, dict) else []

        if not points:
            logger.warning(f"⚠️ Telemetry fallback also returned no data for {registration_number}")
            return JsonResponse({'points': [], 'registration_number': registration_number}, status=200)

        logger.info(f"✅ Telemetry fallback: {len(points)} points for {registration_number}")
        return JsonResponse({'points': points, 'registration_number': registration_number}, status=200)

    except Exception as exc:
        logger.error(f"❌ Telemetry fallback error for {registration_number}: {exc}")
        return JsonResponse({'points': [], 'registration_number': registration_number}, status=200)


@login_required
@require_http_methods(["GET"])
def twins_24hr_route_proxy(request):
    """
    Proxy endpoint for TWINS API to fetch 24-hour route playback data.
    Avoids CORS and CSP issues by proxying through Django backend.
    
    URL: /livetracker/api/twins/24hr-route/
    Params: ?registration_number=ABC123 (required)
    
    Returns: { points: [{timestamp, lat, lon, soc, ...}, ...], vehicle_id, ... }
    """
    try:
        registration_number = request.GET.get('registration_number', '').strip()
        
        # Validate registration_number
        if not registration_number:
            logger.warning("❌ Missing registration_number parameter for TWINS 24hr route")
            return JsonResponse(
                {'error': 'registration_number parameter is required'},
                status=400
            )
        
        twins_url = settings.TWINS_API_URL
        twins_token = settings.TWINS_API_TOKEN
        
        if not twins_url or not twins_token:
            logger.error("❌ TWINS API credentials not configured")
            return JsonResponse(
                {'error': 'TWINS API not configured'},
                status=500
            )
        
        _vendor, _spv = _resolve_twins_project(request.GET.get('spv', ''))

        # Time window: today midnight IST → now IST so route and chart share the same calendar day
        import pytz as _pytz_24hr
        _ist_24hr = _pytz_24hr.timezone('Asia/Kolkata')
        _now_ist = datetime.now(_ist_24hr)
        _start_ist = _now_ist.replace(hour=0, minute=0, second=0, microsecond=0)
        _start_str = _start_ist.strftime('%Y-%m-%dT%H:%M:%S')
        _end_str = _now_ist.strftime('%Y-%m-%dT%H:%M:%S')

        # fetch_geo returns GPS track points (lat/lon/speed/heading) for a vehicle over a time range.
        # fetch_points only has BMS/telemetry data (SOC, odometer) and has no GPS coordinates.
        api_url = (
            f"{twins_url}fetch_geo?spv={_spv}&vendor={_vendor}"
            f"&page_size=5000&registration_number={registration_number}"
            f"&start_time={_start_str}&end_time={_end_str}"
        )

        logger.info(f"🔄 Proxying TWINS 24hr route request: registration_number={registration_number}, vendor={_vendor}, spv={_spv}")
        
        # Make request to TWINS API with token
        # Use stream=True to handle large responses better and avoid timeout during download
        response = requests.get(
            api_url,
            headers={
                'Authorization': f'Bearer {twins_token}',
            },
            timeout=90,  # 90 second timeout: 60s for API processing + 30s for download
            stream=True
        )
        
        # Handle non-success statuses gracefully (project may not be available in TWINS)
        if response.status_code in (400, 403):
            logger.warning(f"⚠️ TWINS returned {response.status_code} for vendor={_vendor} spv={_spv} reg={registration_number} — trying Telemetry API fallback")
            return _telemetry_fallback_24hr(registration_number, _vendor, _spv)

        # Handle 404 errors gracefully — vehicle not in TWINS, try Telemetry fallback
        if response.status_code == 404:
            logger.warning(f"⚠️ Vehicle {registration_number} not found in TWINS 24hr data — trying Telemetry API fallback")
            return _telemetry_fallback_24hr(registration_number, _vendor, _spv)
        
        response.raise_for_status()
        
        data = response.json()
        
        # Extract points — handle both fetch_points (flat list) and fetch_combined (vehicles dict) formats
        if isinstance(data, list):
            # fetch_points returns a flat list of point dicts
            vehicle_points = data
        elif isinstance(data, dict):
            if 'vehicles' in data:
                # fetch_combined format: { vehicles: { reg_no: [points...] } }
                vehicles = data.get('vehicles', {})
                vehicle_points = vehicles.get(registration_number, [])
            elif 'data' in data:
                vehicle_points = data['data']
            elif 'points' in data:
                vehicle_points = data['points']
            else:
                vehicle_points = []
        else:
            vehicle_points = []
        
        if not vehicle_points:
            logger.warning(f"⚠️ No points returned from TWINS fetch_points for {registration_number} ({_vendor}/{_spv}) — trying Telemetry API fallback")
            return _telemetry_fallback_24hr(registration_number, _vendor, _spv)
        
        point_count = len(vehicle_points)
        logger.info(f"✅ TWINS 24hr route response: {point_count} points for {registration_number}")
        if vehicle_points:
            logger.info(f"🔍 fetch_points first point keys: {list(vehicle_points[0].keys())}")
        
        # Map TWINS API points to frontend-compatible format
        # TWINS fields: head, speed, soc, event_datetime, gps_time, latitude, longitude, altitude, etc.
        # Frontend expects: heading, gps_speed, soc, event_datetime, gps_time, latitude, longitude, etc.
        import pytz as _pytz
        _ist = _pytz.timezone('Asia/Kolkata')

        def _normalize_gps_time(raw):
            """Convert Unix int or ISO string gps_time to IST ISO string."""
            if isinstance(raw, int):
                return datetime.fromtimestamp(raw, tz=_ist).strftime('%Y-%m-%dT%H:%M:%S')
            return raw  # already ISO string or None

        def _point_soc(p):
            if p.get('vendor') == 'eka' or 'a_battery_pack_soc' in p:
                vals = [float(p[f]) for f in ('a_battery_pack_soc', 'b_battery_pack_soc', 'c_battery_pack_soc') if p.get(f) is not None]
                return round(sum(vals) / len(vals)) if vals else None
            raw = p.get('soc') if p.get('soc') is not None else p.get('battery_soc')
            return int(float(raw)) if raw is not None else None

        mapped_points = []
        for point in vehicle_points:
            _gps_time = _normalize_gps_time(point.get('gps_time'))
            _last_connected = _gps_time or point.get('event_datetime')
            mapped_point = {
                'registration_number': point.get('registration_number', registration_number),
                'vehicle_no': point.get('registration_number', registration_number),
                'latitude': float(point.get('latitude', 0)) if point.get('latitude') else 0,
                'longitude': float(point.get('longitude', 0)) if point.get('longitude') else 0,
                'gps_time': _gps_time,
                'event_datetime': point.get('event_datetime'),
                'last_connected': _last_connected,
                'heading': float(point.get('head', 0)) if point.get('head') else None,
                'gps_heading': float(point.get('head', 0)) if point.get('head') else None,
                'speed': float(point.get('speed', 0)) if point.get('speed') is not None else 0,
                'gps_speed': float(point.get('speed', 0)) if point.get('speed') is not None else 0,
                'soc': _point_soc(point),
                'odometer': float(point.get('vcu_odometer') or point.get('odometer') or 0) or None,
                'altitude': float(point.get('altitude', 0)) if point.get('altitude') else None,
                'satellites': point.get('satellites'),
                'accuracy_level': point.get('accuracy_level'),
                'device_id': point.get('device_id'),
                'account_name': point.get('account_name'),
                'spv': point.get('spv'),
                'vendor': point.get('vendor'),
                'vehicle_status': point.get('vehicle_status'),  # Status from TWINS (Moving, Idle, Charging, etc.)
                'raw': point
            }
            mapped_points.append(mapped_point)
        
        return JsonResponse({'points': mapped_points, 'registration_number': registration_number}, safe=True)
        
    except requests.Timeout:
        logger.error("⏱️ TWINS 24hr route proxy timeout - TWINS API or network too slow")
        return JsonResponse({'error': 'TWINS API timeout - request took too long'}, status=504)
    except requests.RequestException as e:
        logger.error(f"❌ TWINS 24hr route proxy error: {str(e)}")
        return JsonResponse(
            {'error': f'TWINS API error: {str(e)}'},
            status=502
        )
    except ValueError as e:
        logger.error(f"❌ TWINS 24hr route response parsing error: {str(e)}")
        return JsonResponse(
            {'error': 'Invalid TWINS API response'},
            status=502
        )
    except Exception as e:
        logger.error(f"❌ TWINS 24hr route proxy unexpected error: {str(e)}")
        return JsonResponse(
            {'error': 'Internal server error'},
            status=500
        )


@login_required
@require_http_methods(["GET"])
def twins_temp_soc_proxy(request):
    """
    Proxy for TWINS fetch_temp_soc endpoint.
    Single-page per call; frontend drives pagination via cursor param.

    URL:    /livetracker/api/twins/temp-soc/
    Params: registration_number (required), spv, start_time, end_time, page_size, cursor
    Returns: { points, has_more, next_cursor, registration_number }
    """
    import pytz as _pytz
    _ist = _pytz.timezone('Asia/Kolkata')

    registration_number = request.GET.get('registration_number', '').strip()
    if not registration_number:
        return JsonResponse({'error': 'registration_number required'}, status=400)

    twins_url   = getattr(settings, 'TWINS_API_URL', '')
    twins_token = getattr(settings, 'TWINS_API_TOKEN', '')
    if not twins_url or not twins_token:
        return JsonResponse({'error': 'TWINS API not configured'}, status=500)

    _vendor, _spv = _resolve_twins_project(request.GET.get('spv', ''))
    start_time = request.GET.get('start_time', '')
    end_time   = request.GET.get('end_time', '')
    page_size  = int(request.GET.get('page_size', 1000))
    cursor     = request.GET.get('cursor', '')

    def _norm(raw):
        if raw is None:
            return None
        try:
            ts = int(raw)
            # fetch_temp_soc always uses epoch seconds (confirmed empirically)
            dt = datetime.fromtimestamp(ts, tz=_ist)
            return dt.strftime('%Y-%m-%dT%H:%M:%S')
        except (ValueError, TypeError):
            return str(raw)

    params = {
        'vendor': _vendor, 'spv': _spv,
        'registration_number': registration_number,
        'page_size': page_size,
    }
    if start_time:  params['start_time'] = start_time
    if end_time:    params['end_time']   = end_time
    if cursor:      params['cursor']     = cursor

    try:
        resp = requests.get(
            f"{twins_url}fetch_temp_soc",
            headers={'Authorization': f'Bearer {twins_token}'},
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning(f"[temp_soc] fetch error: {exc}")
        return JsonResponse({'error': str(exc)}, status=502)

    if isinstance(data, list):
        page_points = data
        has_more    = False
        next_cursor = None
    else:
        vehicles    = data.get('vehicles', {})
        # Exact match first, then any key
        page_points = vehicles.get(registration_number) or (next(iter(vehicles.values()), []) if vehicles else [])
        has_more    = data.get('has_more', False)
        next_cursor = data.get('next_cursor') or None

    def _avg(*vals):
        nums = [v for v in vals if v is not None]
        return round(sum(nums) / len(nums), 2) if nums else None

    def _max(*vals):
        nums = [v for v in vals if v is not None]
        return max(nums) if nums else None

    points = []
    for pt in page_points:
        # intangles: soc, temperature_highest, voltage, current
        # eka: a/b/c_battery_pack_soc, a/b/c_cell_temperature_highest, a/b/c_battery_pack_voltage, a/b/c_battery_pack_current
        is_eka = pt.get('vendor') == 'eka' or 'a_battery_pack_soc' in pt

        if is_eka:
            soc   = _avg(pt.get('a_battery_pack_soc'), pt.get('b_battery_pack_soc'), pt.get('c_battery_pack_soc'))
            soh   = _avg(pt.get('soh_a_battery'), pt.get('soh_b_battery'), pt.get('soh_c_battery'))
            temp  = _max(pt.get('a_cell_temperature_highest'), pt.get('b_cell_temperature_highest'), pt.get('c_cell_temperature_highest'))
            volt  = _avg(pt.get('a_battery_pack_voltage'), pt.get('b_battery_pack_voltage'), pt.get('c_battery_pack_voltage'))
            curr  = _avg(pt.get('a_battery_pack_current'), pt.get('b_battery_pack_current'), pt.get('c_battery_pack_current'))
        else:
            soc   = pt.get('soc')
            soh   = pt.get('soh')
            temp  = pt.get('temperature_highest')
            volt  = pt.get('voltage')
            curr  = pt.get('current')

        points.append({
            'gps_time':            _norm(pt.get('gps_time')),
            'soc':                 soc,
            'soh':                 soh,
            'battery_temperature': temp,
            'battery_voltage':     volt,
            'battery_current':     curr,
            'speed':               pt.get('speed'),
            'latitude':            pt.get('latitude'),
            'longitude':           pt.get('longitude'),
        })

    logger.info(f"[temp_soc] {registration_number}: {len(points)} pts page, has_more={has_more}")
    return JsonResponse({
        'points':              points,
        'has_more':            has_more,
        'next_cursor':         next_cursor,
        'registration_number': registration_number,
    })


@login_required
@login_required
@require_http_methods(["GET", "POST"])
def geofences_list_create(request):
    if request.method == 'GET':
        spv_filter = request.GET.get('spv', '').strip()
        qs = Geofence.objects.all()
        if spv_filter:
            qs = qs.filter(spv=spv_filter)
        data = [
            {
                'id': g.id,
                'name': g.name,
                'geometry': g.geometry,
                'spv': g.spv,
                'color': g.color,
                'created_at': g.created_at.isoformat(),
            }
            for g in qs
        ]
        return JsonResponse({'geofences': data})

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    name = str(body.get('name', '')).strip()
    geometry = body.get('geometry')
    spv = str(body.get('spv', '')).strip()[:50]
    color = str(body.get('color', '#3b82f6')).strip()[:20]

    if not name:
        return JsonResponse({'error': 'name is required'}, status=400)
    if not geometry or not isinstance(geometry, dict):
        return JsonResponse({'error': 'geometry (GeoJSON) is required'}, status=400)

    geofence = Geofence.objects.create(
        name=name,
        geometry=geometry,
        spv=spv,
        color=color,
        created_by=request.user,
    )
    return JsonResponse({
        'id': geofence.id,
        'name': geofence.name,
        'geometry': geofence.geometry,
        'spv': geofence.spv,
        'color': geofence.color,
        'created_at': geofence.created_at.isoformat(),
    }, status=201)


@login_required
@require_http_methods(["GET", "PUT", "DELETE"])
def geofence_detail(request, pk):
    geofence = get_object_or_404(Geofence, pk=pk)

    if request.method == 'GET':
        return JsonResponse({
            'id': geofence.id,
            'name': geofence.name,
            'geometry': geofence.geometry,
            'spv': geofence.spv,
            'color': geofence.color,
            'created_at': geofence.created_at.isoformat(),
        })

    if request.method == 'DELETE':
        geofence.delete()
        return JsonResponse({'deleted': True})

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    if 'name' in body:
        geofence.name = str(body['name']).strip()
    if 'color' in body:
        geofence.color = str(body['color']).strip()[:20]
    if 'spv' in body:
        geofence.spv = str(body['spv']).strip()[:50]
    geofence.save()
    return JsonResponse({
        'id': geofence.id,
        'name': geofence.name,
        'geometry': geofence.geometry,
        'spv': geofence.spv,
        'color': geofence.color,
    })


# ── Fleet Trend API ───────────────────────────────────────────────────────────

def _fetch_soc_discharge_all(spv, vendor, start_date, end_date, vehicle_no=None, cache_ttl=900):
    """Fetch all pages from /analytics/soc-discharge and return flat list of records."""
    from dashboard.services.dashboard_kpi_services import fetch_voltrack_api
    all_records = []
    cursor = None
    for _ in range(30):
        params = {'spv': spv, 'vendor': vendor, 'start_date': start_date, 'end_date': end_date}
        if cursor:
            params['cursor'] = cursor
        if vehicle_no:
            params['registration_number'] = vehicle_no
        resp = fetch_voltrack_api('/analytics/soc-discharge', params=params, cache_ttl=cache_ttl)
        if not resp:
            break
        all_records.extend(resp.get('data', []))
        cursor = (resp.get('pagination') or {}).get('next_cursor')
        if not cursor:
            break
    return all_records


def _records_to_daily_averages(all_records, filter_vehicle=None):
    """Group records by date and compute average distance, energy, efficiency."""
    from collections import defaultdict
    BATTERY_KWH = 282
    daily = defaultdict(lambda: {'dist': [], 'energy': [], 'eff': []})
    for rec in all_records:
        if not isinstance(rec, dict):
            continue
        if filter_vehicle:
            rec_vehicle = rec.get('registration_number', '') or ''
            if rec_vehicle.upper() != filter_vehicle.upper():
                continue
        date_key = str(rec.get('dt') or rec.get('date') or rec.get('data_date') or rec.get('record_date') or '')[:10]
        if not date_key:
            continue
        try:
            dist = float(rec.get('distance_km', 0) or 0)
            discharge = float(rec.get('total_discharge_pct', 0) or 0)
        except (ValueError, TypeError):
            continue
        if dist < 10 or discharge < 10:
            continue
        daily[date_key]['dist'].append(dist)
        raw_energy = rec.get('energy_consumed_kwh') or rec.get('energy_kwh')
        energy = float(raw_energy) if raw_energy not in (None, '', 0) else (discharge / 100) * BATTERY_KWH
        daily[date_key]['energy'].append(energy)
        try:
            eff = float(rec.get('efficiency_kwh_per_km', 0) or 0)
            if eff > 0:
                daily[date_key]['eff'].append(eff)
        except (ValueError, TypeError):
            pass
    return daily


def _build_7day_output(daily, today):
    """Build ordered 7-day lists: labels, distances, energies, efficiencies."""
    def avg(lst): return round(sum(lst) / len(lst), 3) if lst else None
    labels, distances, energies, efficiencies = [], [], [], []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i + 1)
        labels.append(d.strftime('%d %b'))
        key = d.strftime('%Y-%m-%d')
        dv = daily.get(key, {})
        distances.append(avg(dv.get('dist', [])))
        energies.append(avg(dv.get('energy', [])))
        efficiencies.append(avg(dv.get('eff', [])))
    return labels, distances, energies, efficiencies


@login_required
def fleet_trend_api(request):
    """
    Returns 7-day daily averages: distance, energy, efficiency.
    ?vehicle_no=REG — vehicle-specific trend (live API, short cache)
    No param — fleet-wide average, served from DB if precomputed by scheduler
    """
    from dashboard.vendor_spv_list import VENDOR_SPV_LIST

    # Accept ?spv= from the URL (baked in by the template at render time) so that
    # project-switching works without relying on session/redirect ordering.
    # Fall back to session if not provided. Validate against known SPVs to prevent
    # cross-project data leakage.
    requested_spv = request.GET.get('spv', '').strip().upper()
    session_spv = request.session.get('selected_project', 'ULTRATECH')
    spv = requested_spv if requested_spv in VENDOR_SPV_LIST else session_spv

    vendors = VENDOR_SPV_LIST.get(spv, [])
    if not vendors:
        return JsonResponse({'error': 'No vendor for project'}, status=400)
    vendor = vendors[0]
    vehicle_no = request.GET.get('vehicle_no', '').strip().upper()
    today = datetime.now().date()
    start_date = (today - timedelta(days=7)).strftime('%Y-%m-%d')
    end_date = (today - timedelta(days=1)).strftime('%Y-%m-%d')

    def _db_rows_to_output(db_rows):
        from collections import defaultdict
        d = defaultdict(lambda: {'dist': [], 'energy': [], 'eff': []})
        for date_str, row in db_rows.items():
            if row.avg_distance_km is not None:
                d[date_str]['dist'] = [row.avg_distance_km]
            if row.avg_energy_kwh is not None:
                d[date_str]['energy'] = [row.avg_energy_kwh]
            if row.avg_efficiency_kwh_per_km is not None:
                d[date_str]['eff'] = [row.avg_efficiency_kwh_per_km]
        return _build_7day_output(d, today)

    if vehicle_no:
        # Vehicle-specific: DB fast path first (populated by nightly scheduler)
        db_rows = {
            str(row.date): row
            for row in FleetTrendDaily.objects.filter(
                spv=spv, vehicle_no=vehicle_no,
                date__gte=start_date, date__lte=end_date
            )
        }
        if len(db_rows) >= 3:
            labels, distances, energies, efficiencies = _db_rows_to_output(db_rows)
            return JsonResponse({'dates': labels, 'distance': distances, 'energy': energies, 'efficiency': efficiencies, 'vehicle_no': vehicle_no, 'source': 'db'})

        # Fall back: Django short-cache then live API
        cache_key = f'fleet_trend_v:{spv}:{vehicle_no}'
        cached = cache.get(cache_key)
        if cached:
            return JsonResponse(cached)
        all_records = _fetch_soc_discharge_all(spv, vendor, start_date, end_date, cache_ttl=300)
        daily = _records_to_daily_averages(all_records, filter_vehicle=vehicle_no)
        labels, distances, energies, efficiencies = _build_7day_output(daily, today)
        result = {'dates': labels, 'distance': distances, 'energy': energies, 'efficiency': efficiencies, 'vehicle_no': vehicle_no}
        cache.set(cache_key, result, 1800)
        return JsonResponse(result)

    # Fleet average — DB fast path (vehicle_no IS NULL)
    db_rows = {
        str(row.date): row
        for row in FleetTrendDaily.objects.filter(
            spv=spv, vehicle_no__isnull=True,
            date__gte=start_date, date__lte=end_date
        )
    }
    if len(db_rows) >= 5:
        labels, distances, energies, efficiencies = _db_rows_to_output(db_rows)
        return JsonResponse({'dates': labels, 'distance': distances, 'energy': energies, 'efficiency': efficiencies, 'source': 'db'})

    # Fall back to live API and save any missing days to DB
    all_records = _fetch_soc_discharge_all(spv, vendor, start_date, end_date, cache_ttl=900)
    daily = _records_to_daily_averages(all_records)
    labels, distances, energies, efficiencies = _build_7day_output(daily, today)

    # Backfill DB for missing days (fleet average, vehicle_no=None)
    def _avg(lst): return round(sum(lst) / len(lst), 4) if lst else None
    for date_str, vals in daily.items():
        if date_str not in db_rows:
            try:
                FleetTrendDaily.objects.update_or_create(
                    date=date_str, spv=spv, vehicle_no=None,
                    defaults={
                        'avg_distance_km': _avg(vals['dist']),
                        'avg_energy_kwh': _avg(vals['energy']),
                        'avg_efficiency_kwh_per_km': _avg(vals['eff']),
                        'vehicle_count': len(vals['dist']),
                    }
                )
            except Exception:
                pass

    return JsonResponse({'dates': labels, 'distance': distances, 'energy': energies, 'efficiency': efficiencies, 'source': 'live'})
