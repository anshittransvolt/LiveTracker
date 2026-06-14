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
from .models import TimeBoxDailyAvgDelay, Geofence
from .analytics.analytics_service import format_analytics_response
from .analytics.charging_sessions import aggregate_charging_sessions, charging_sessions_to_dataframe
from .analytics.stoppage_sessions import aggregate_stoppage_sessions, stoppage_sessions_to_dataframe
from .analytics.dashboard_report import download_dashboard_report
from .timebox import build_timebox_for_vehicle
from .data_sources import DataSourceManager
from mis.services.route_corridor import load_corridor
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


def fetch_timebox_data_from_fetch_geo(
    start_time: datetime = None,
    end_time: datetime = None,
    hours_back: int = 6,
    batch_window_hours: int = 1
) -> dict:
    """
    Fetch vehicle location data using fetch_geo API with proper pagination.
    Designed specifically for timebox processing with consistent time ranges.
    
    Uses automatic pagination to handle server-side limitations:
    - Splits time windows into smaller batches (default: 1-hour windows)
    - Ensures complete data retrieval without gaps
    - Handles all vehicles in a single call
    
    Args:
        start_time: Explicit start datetime (optional)
        end_time: Explicit end datetime (optional)
        hours_back: If start/end not provided, fetch last N hours from now (default: 6)
        batch_window_hours: Size of pagination batches in hours (default: 1)
                           Smaller = safer but slower, Larger = faster but may fail
    
    Returns:
        Dict[registration_number] = [
            {
                'latitude': float,
                'longitude': float,
                'vehicle_status': str,
                'gps_time': datetime,
                'event_datetime': datetime,
                'speed': float,
                'odometer': float,
                'registration_number': str,
                'last_connected': datetime,
                'gps_location': str (lat,lon)
            },
            ...
        ]
    """
    try:
        # Determine time window
        if start_time is None or end_time is None:
            end_time = datetime.now()
            start_time = end_time - timedelta(hours=hours_back)
        
        logger.info(
            f"🔄 Fetching timebox data from fetch_geo API: "
            f"{start_time} to {end_time} "
            f"({(end_time - start_time).total_seconds() / 3600:.1f}h window, "
            f"{batch_window_hours}h batch windows)"
        )
        
        # Fetch data with automatic pagination
        vehicles_data = DataSourceManager.fetch_fetch_geo_data(
            start_time=start_time,
            end_time=end_time,
            batch_window_hours=batch_window_hours
        )
        
        # Transform to timebox-compatible format
        timebox_data = {}
        for reg_no, points in vehicles_data.items():
            timebox_points = []
            for point in points:
                timebox_points.append({
                    'latitude': point.get('latitude'),
                    'longitude': point.get('longitude'),
                    'vehicle_status': point.get('vehicle_status', 'traveling'),
                    'gps_time': point.get('gps_time'),
                    'event_datetime': point.get('event_datetime'),
                    'speed': point.get('speed', 0),
                    'odometer': point.get('odometer', 0),
                    'registration_number': reg_no,
                    'last_connected': point.get('gps_time'),  # Use gps_time as last_connected
                    'gps_location': f"{point.get('latitude', 0)},{point.get('longitude', 0)}",
                })
            timebox_data[reg_no] = timebox_points
        
        logger.info(
            f"✅ Fetched timebox data: {len(timebox_data)} vehicles, "
            f"{sum(len(p) for p in timebox_data.values())} total points"
        )
        
        return timebox_data
        
    except Exception as e:
        logger.error(f"❌ Error fetching timebox data from fetch_geo: {type(e).__name__}: {str(e)}")
        return {}
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
@login_required
def logs_view(request):
    # Returns the message logs page
    # Uses TWINS API via Django proxies
    return render(request, "livetracker/logs.html", {})


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
                    # Use TWINS fetch_points endpoint for 24hr data
                    api_url = f"{twins_url}fetch_points?spv={_spv}&vendor={_vendor}&page_size=5000&registration_number={registration_number}"
                    response = requests.get(
                        api_url,
                        headers={'Authorization': f'Bearer {twins_token}'},
                        timeout=60
                    )
                    response.raise_for_status()
                    data = response.json()
                    
                    # Extract points for the vehicle
                    vehicles = data.get('vehicles', {})
                    twins_points = vehicles.get(registration_number, [])
                    
                    if twins_points:
                        # Map TWINS points to analytics-compatible format
                        for point in twins_points:
                            # Parse coordinates safely
                            lat = float(point.get('latitude', 0)) if point.get('latitude') else None
                            lng = float(point.get('longitude', 0)) if point.get('longitude') else None
                            
                            # Only include points with valid GPS coordinates
                            if not (lat and lng and lat != 0 and lng != 0):
                                continue
                            
                            # Get SOC and ensure it's a valid positive number
                            _raw_soc = point.get('soc')
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
                                # Set vehicle_status based on speed heuristic if not provided
                                'vehicle_status': point.get('vehicle_status', 'moving' if speed > 1 else 'stopped'),
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
        limit = int(request.GET.get("limit", 50))

        # Fetch recent alerts with optional filters
        qs = VehicleAlert.objects.filter(created_at__gte=time_threshold)
        if alert_type:
            qs = qs.filter(alert_type=alert_type)
        if vehicle_no:
            qs = qs.filter(vehicle_no=vehicle_no)
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

@login_required
def timeline_table_view(request):
    """
    TIME BOX View - Shows checkpoint status for all trucks.
    
    This view displays a table with vehicle numbers and their TIME BOX status.
    Each truck has checkpoints that are color-coded (green=on-time, red=delayed).
    
    Trucks are automatically sorted by delay in descending order (highest delay first).
    
    Routes:
    - Dhar to Dhule: Yard → Charging → Loading → Jhulwania Charging → Maharashtra Border → Yard → Charging → Unloading
    - Dhule to Dhar: Yard → Charging → Loading → Maharashtra Border → Jhulwania Charging → Yard → Charging → Unloading
    
    Data source: Real-time multi-day API data with automatic vehicle sync
    """
    
    import json
    import os
    
    # Check if specific vehicle is requested
    requested_vehicle = request.GET.get('vehicleNumber') or request.GET.get('vehicle')
    
    # Always use real-time API data with multi-day fetching
    timeline_data = {}
    
    try:
        # Step 1: Fetch vehicle data from fetch_geo API with proper pagination
        logger.info("🔄 Fetching vehicle data from fetch_geo API with pagination")
        
        # Get last 24 hours of FRESH data for complete timeline
        # Fetches from 24h ago to NOW (ensures fresh batches, not stale history)
        # Live indicator only shows on latest detected phase (within 2-3 hours)
        timebox_vehicles_data = fetch_timebox_data_from_fetch_geo(
            hours_back=24,
            batch_window_hours=1
        )
        
        if not timebox_vehicles_data:
            logger.warning("❌ fetch_geo API returned no data")
            timeline_data = {}
        else:
            logger.info(f"✅ fetch_geo API: {len(timebox_vehicles_data)} vehicles, {sum(len(p) for p in timebox_vehicles_data.values())} total points")
            
            # Step 2: Auto-sync vehicles from fetch_geo data to database
            api_vehicles = set(timebox_vehicles_data.keys())
            existing_vehicles = set(Vehicle.objects.values_list('registration_number', flat=True))
            new_vehicles = api_vehicles - existing_vehicles
            
            synced_vehicles = 0
            if new_vehicles:
                try:
                    from dashboard.models import ModelType
                    default_model_type = ModelType.objects.first()
                    if default_model_type:
                        vehicles_to_create = [
                            Vehicle(registration_number=v, model=default_model_type)
                            for v in new_vehicles
                        ]
                        created = Vehicle.objects.bulk_create(vehicles_to_create, ignore_conflicts=True)
                        synced_vehicles = len(created)
                        logger.info(f"✅ Auto-synced {synced_vehicles} new vehicles from fetch_geo API")
                except Exception as e:
                    logger.warning(f"⚠️ Could not auto-sync vehicles: {e}")
            
            # Step 3: Get updated vehicle list from database
            vehicle_numbers = list(api_vehicles)  # Use vehicles we actually got data for
            
            # Filter to specific vehicle if requested
            if requested_vehicle:
                if requested_vehicle in vehicle_numbers:
                    vehicle_numbers = [requested_vehicle]
                    logger.info(f"Filtering timeline data for specific vehicle: {requested_vehicle}")
                else:
                    logger.warning(f"Requested vehicle {requested_vehicle} not found in fetch_geo data")
                    vehicle_numbers = []
            
            if not vehicle_numbers:
                logger.warning("No vehicles to process")
                timeline_data = {}
            else:
                logger.info(f"🚀 Processing timeline data for {len(vehicle_numbers)} vehicles (including {synced_vehicles} newly synced)")
                
                # Step 4: Convert fetch_geo data to timeline format and process with timebox
                # Feature flag: choose engine via query param; default to timebox
                engine = request.GET.get('engine') or 'timebox'
                logger.info(f"Timeline engine selected: {engine}")
                
                # Fetch dense 24hr data for all vehicles in ONE batch fetch_combined call
                # (no registration_number = returns all vehicles, same as fetch_geo but denser)
                twins_url = settings.TWINS_API_URL
                twins_token = settings.TWINS_API_TOKEN
                timebox_input = {}

                def _normalize_pt(pt, vehicle_no):
                    lat = float(pt.get('latitude', 0)) if pt.get('latitude') else 0
                    lon = float(pt.get('longitude', 0)) if pt.get('longitude') else 0
                    speed = float(pt.get('speed', 0)) if pt.get('speed') is not None else 0
                    raw_status = pt.get('vehicle_status', '')
                    vehicle_status = raw_status if raw_status else ('traveling' if speed > 1 else 'yard')
                    raw_gps_time = pt.get('gps_time')
                    if isinstance(raw_gps_time, int):
                        from datetime import timezone as _tz
                        gps_time_str = datetime.fromtimestamp(raw_gps_time, tz=_tz.utc).isoformat()
                    elif isinstance(raw_gps_time, datetime):
                        gps_time_str = raw_gps_time.isoformat()
                    else:
                        gps_time_str = raw_gps_time
                    return {
                        'latitude': lat,
                        'longitude': lon,
                        'vehicle_status': vehicle_status,
                        'gps_time': gps_time_str,
                        'event_datetime': pt.get('event_datetime'),
                        'speed': speed,
                        'odometer': float(pt.get('odometer', 0)) if pt.get('odometer') else 0,
                        'registration_number': vehicle_no,
                        'last_connected': gps_time_str,
                        'gps_location': f"{lat},{lon}",
                        'soc': int(pt.get('soc', 0)) if pt.get('soc') else 0,
                    }

                _FC_CACHE_KEY = 'timebox_fc_batch'
                _FC_CACHE_TTL = 300  # 5 minutes

                all_vehicles_raw = cache.get(_FC_CACHE_KEY)
                if all_vehicles_raw is not None:
                    logger.info(f"✅ fetch_combined cache hit: {len(all_vehicles_raw)} vehicles")
                    for vno in vehicle_numbers:
                        vdata = all_vehicles_raw.get(vno, [])
                        if vdata:
                            timebox_input[vno] = [_normalize_pt(pt, vno) for pt in vdata]
                        else:
                            timebox_input[vno] = timebox_vehicles_data.get(vno, [])
                else:
                    # Cache miss — render immediately with fetch_geo data, warm cache in background
                    logger.info("⏩ fetch_combined cache miss — using fetch_geo data now, warming cache in background")
                    for vno in vehicle_numbers:
                        timebox_input[vno] = timebox_vehicles_data.get(vno, [])

                    import threading
                    _tw_url = twins_url
                    _tw_tok = twins_token

                    def _warm_fc_cache():
                        try:
                            _vendor, _spv = _resolve_twins_project('')
                            resp = requests.get(
                                f"{_tw_url}fetch_points?spv={_spv}&vendor={_vendor}&page_size=5000",
                                headers={'Authorization': f'Bearer {_tw_tok}'},
                                timeout=90,
                            )
                            resp.raise_for_status()
                            raw = resp.json().get('vehicles', {})
                            cache.set(_FC_CACHE_KEY, raw, _FC_CACHE_TTL)
                            logger.info(f"✅ Background fetch_combined cache warmed: {len(raw)} vehicles")
                        except Exception as exc:
                            logger.warning(f"⚠️ Background fetch_combined cache warm failed: {exc}")

                    try:
                        threading.Thread(target=_warm_fc_cache, daemon=True).start()
                    except RuntimeError:
                        pass  # Interpreter shutting down (dev server reload) — skip background warm

                # Process with timebox engine
                timeline_data = {}
                for vehicle_no, records in timebox_input.items():
                    try:
                        from .timebox import build_timebox_for_vehicle
                        result = build_timebox_for_vehicle(records)
                        timeline_data[vehicle_no] = {
                            'direction': result.get('direction'),
                            'timeline': result.get('timeline', []),
                            'latest_trip_duration_seconds': result.get('latest_trip_duration_seconds'),
                            'current_trip_duration_seconds': result.get('current_trip_duration_seconds'),
                            'current_segment_start_ts': result.get('current_segment_start_ts'),
                            'data_source': 'fetch_combined (real-time GPS)'
                        }
                    except Exception as e:
                        logger.warning(f"⚠️ Timebox processing failed for {vehicle_no}: {e}")
                        timeline_data[vehicle_no] = {'timeline': [], 'direction': None, 'data_source': 'fetch_geo (error)'}
                
                logger.info(f"✅ Successfully processed timeline data for {len(timeline_data)} vehicles")
        
    except Exception as e:
        logger.error(f"Error fetching real-time data: {e}")
        # Fallback to empty timeline data if API fails
        timeline_data = {}
        
        # Try to get existing vehicles as backup
        try:
            vehicles = Vehicle.objects.all().values_list('registration_number', flat=True)
            vehicle_numbers = list(vehicles)
            logger.info(f"API failed, showing empty timeline for {len(vehicle_numbers)} existing vehicles")
            # Create empty timeline entries for existing vehicles
            for vehicle_no in vehicle_numbers:
                timeline_data[vehicle_no] = {
                    'checkpoints': [],
                    'total_delay': 0,
                    'status': 'No Data Available'
                }
        except Exception as fallback_error:
            logger.error(f"Fallback also failed: {fallback_error}")
            # Final fallback to mock data
            timeline_path = os.path.join(os.path.dirname(__file__), 'test_data', 'route_timeline.json')
            try:
                if os.path.exists(timeline_path):
                    with open(timeline_path) as f:
                        timeline_data = json.load(f)
                    logger.info(f"Final fallback to mock data with {len(timeline_data)} vehicles")
                    
                    # Debug: Check for historical flags
                    historical_count = 0
                    for vehicle_key, vehicle_data in timeline_data.items():
                        timeline = vehicle_data.get('timeline', [])
                        for phase in timeline:
                            if phase.get('historical', False):
                                historical_count += 1
                    # print(f"VIEWS DEBUG: Found {historical_count} historical phases in JSON data")
                    logger.info(f"DEBUG: Found {historical_count} historical phases in JSON data")
                else:
                    timeline_data = {}
                    logger.warning("No mock data available, showing empty timeline")
            except Exception as mock_error:
                logger.error(f"Error loading fallback mock data: {mock_error}")
                timeline_data = {}

    def map_timeline_to_truck(vehicle_number, entry):
        # Map the timeline JSON entry to the format expected by the template
        from .alertService import alert_constants as ac

        PHASE_SLA = {
            'manawar_loading': ac.LOADING_DWELL_SECONDS,
            'dhule_unloading': ac.UNLOADING_DWELL_SECONDS,
            'manawar_charging': ac.CHARGING_OVER_SECONDS,
            'dhule_charging': ac.CHARGING_OVER_SECONDS,
            'jhulwania_charging': ac.CHARGING_OVER_SECONDS,
            'maha_border': ac.MAHA_BORDER_DWELL_SECONDS,
            # Transit phases - using correct phase keys from timeline data
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

        # UI box order and friendly names for each direction
        # Explicit mapping tables for each direction
        dhar_to_dhule_map = {
            'manawar_yard':      ('manawar_yard', 'Manawar Yard'),
            'manawar_loading':   ('manawar_loading', 'Loading'),
            'manawar_charging':  ('manawar_charging', 'Charging'),
            'manawar_to_jhulwania': ('manawar_to_jhulwania', 'Manawar to Jhulwania'),
            'jhulwania_yard':    ('jhulwania_yard', 'Jhulwania Yard'),
            'jhulwania_charging':('jhulwania_charging', 'Jhulwania Charging'),
            'jhulwania_to_maha_border': ('jhulwania_to_maha_border', 'Jhulwania to MH Border'),
            'maha_border':       ('maha_border', 'MH Border'),
            'maha_border_to_dhule': ('maha_border_to_dhule', 'MH Border to Dhule'),
            'dhule_yard':        ('dhule_yard', 'Dhule Yard'),
            'dhule_charging':    ('dhule_charging', 'Dhule Charging'),
            'dhule_unloading':   ('dhule_unloading', 'Unloading'),
        }
        dhule_to_dhar_map = {
            'dhule_yard':        ('dhule_yard', 'Dhule Yard'),
            'dhule_unloading':   ('dhule_unloading', 'Unloading'),
            'dhule_charging':    ('dhule_charging', 'Dhule Charging'),
            'dhule_to_maha_border': ('dhule_to_maha_border', 'Dhule to MH Border'),
            'maha_border':       ('maha_border', 'MH Border'),
            'maha_border_to_jhulwania': ('maha_border_to_jhulwania', 'MH Border to Jhulwania'),
            'jhulwania_yard':    ('jhulwania_yard', 'Jhulwania Yard'),
            'jhulwania_charging':('jhulwania_charging', 'Jhulwania Charging'),
            'jhulwania_to_manawar': ('jhulwania_to_manawar', 'Jhulwania to Manawar'),
            'manawar_yard':      ('manawar_yard', 'Manawar Yard'),
            'manawar_charging':  ('manawar_charging', 'Manawar Charging'),
            'manawar_loading':   ('manawar_loading', 'Loading'),
        }
        direction = (entry.get('direction') or '').lower()
        timeline = entry.get('timeline', [])
        checkpoints = []
        current_transit = None

        def parse_timestamp(time_str):
            if not time_str:
                return None
            try:
                # Handle ISO format with timezone (e.g., 2025-12-16T15:18:00+05:30)
                if 'T' in time_str and '+' in time_str:
                    # Parse ISO format with timezone and convert to IST
                    dt = datetime.fromisoformat(time_str)
                    # Convert to IST and then make naive for comparison
                    ist_dt = dt.astimezone(ist)
                    return ist_dt.replace(tzinfo=None)
                elif 'T' in time_str:
                    # ISO format without timezone - assume IST
                    dt = datetime.fromisoformat(time_str.replace('Z', ''))
                    return dt.replace(tzinfo=None)
                else:
                    # Standard format - assume already IST
                    # Try with seconds, then with minutes-only
                    try:
                        dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
                    except Exception:
                        dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M")
                    return dt.replace(tzinfo=None)
            except Exception as e:
                # Fallback: try to extract just the datetime part
                try:
                    # Remove timezone info and try again
                    clean_time = time_str.split('+')[0].split('Z')[0].replace('T', ' ')
                    try:
                        return datetime.strptime(clean_time, "%Y-%m-%d %H:%M:%S")
                    except Exception:
                        return datetime.strptime(clean_time, "%Y-%m-%d %H:%M")
                except:
                    return None

        # Safety override: if timebox reported dhar_to_dhule but the data contains
        # return-trip transit phases from the CURRENT segment, the vehicle has already
        # left Dhule heading back.  Switch direction so the return canonical order is used.
        # IMPORTANT: only check phases from the current trip segment (after
        # current_segment_start_ts) to avoid false positives from a prior return leg
        # that are still in the 24-hour timeline window.
        if direction == 'dhar_to_dhule':
            _return_signals = {'dhule_to_maha_border', 'maha_border_to_jhulwania', 'jhulwania_to_manawar'}
            _seg_start_str = entry.get('current_segment_start_ts')
            _seg_start_dt = parse_timestamp(_seg_start_str) if _seg_start_str else None
            if _seg_start_dt:
                # Only consider phases that begin at or after the current segment start
                _data_phases = set()
                for _p in timeline:
                    _ps = parse_timestamp(_p.get('start')) or parse_timestamp(_p.get('end'))
                    if _ps and _ps >= _seg_start_dt:
                        _data_phases.add(_p.get('phase', '').lower())
            else:
                _data_phases = {p.get('phase', '').lower() for p in timeline}
            if _data_phases & _return_signals:
                direction = 'dhule_to_dhar'
                logger.info(f"Direction override for {vehicle_number}: dhar_to_dhule → dhule_to_dhar (return phases: {_data_phases & _return_signals})")

        # Get the canonical UI order and mapping first
        if direction == 'dhar_to_dhule':
            canonical_order = list(dhar_to_dhule_map.keys())
            phase_map = dhar_to_dhule_map
        elif direction == 'dhule_to_dhar':
            canonical_order = list(dhule_to_dhar_map.keys())
            phase_map = dhule_to_dhar_map
        else:
            # Default to dhule_to_dhar if direction is unclear
            canonical_order = list(dhule_to_dhar_map.keys())
            phase_map = dhule_to_dhar_map
        
        # Build a lookup for all phases in the timeline
        # Handle both exact matches and normalized transit phase matches
        # For duplicate phase names, keep the entry with the longest duration_seconds
        phase_data_map = {}
        for p in timeline:
            phase_name = p.get('phase', '')
            if not phase_name:
                continue
            
            # Add exact match (lowercased) — keep longest duration if duplicate
            key_lower = phase_name.lower()
            existing = phase_data_map.get(key_lower)
            if existing is None or (p.get('duration_seconds') or 0) > (existing.get('duration_seconds') or 0):
                phase_data_map[key_lower] = p
            
            # Handle transit phases - normalize different naming conventions
            if '_to_' in phase_name:
                # Normalize transit phase names to match canonical order
                normalized = phase_name.lower()
                existing_transit = phase_data_map.get(normalized)
                if existing_transit is None or (p.get('duration_seconds') or 0) > (existing_transit.get('duration_seconds') or 0):
                    phase_data_map[normalized] = p
        
        # Debug: Log phase mapping for troubleshooting
        if vehicle_number and timeline:
            logger.info(f"Phase mapping for {vehicle_number}: phases in data={list(phase_data_map.keys())}, canonical_order={canonical_order}")
        # Find the current phase based on actual timestamps
        import pytz
        
        # Get current time in IST (India Standard Time) since API data is in IST
        ist = pytz.timezone('Asia/Kolkata')
        current_time = datetime.now(ist).replace(tzinfo=None)  # Convert to naive IST time
        current_phase_idx = -1
        
        # Helper function to parse timestamps
        # Find the most recent activity across ALL phases, then map it to canonical order
        most_recent_activity = None
        most_recent_phase_key = None
        
        # First pass: Find the most recent activity timestamp across all phases
        for key, phase in phase_data_map.items():
            end_time = parse_timestamp(phase.get('end', ''))
            start_time = parse_timestamp(phase.get('start', ''))
            
            # Check for currently active phase (between start and end)
            if start_time and end_time and start_time <= current_time <= end_time:
                most_recent_activity = current_time  # Currently active - highest priority
                most_recent_phase_key = key
                break
            elif start_time and not end_time and start_time <= current_time:
                # Ongoing phase (no end time) - second highest priority
                most_recent_activity = current_time
                most_recent_phase_key = key
                break
            elif end_time and end_time <= current_time:
                # Completed phase - track the most recent completion
                if most_recent_activity is None or end_time > most_recent_activity:
                    most_recent_activity = end_time
                    most_recent_phase_key = key
        
        # Second pass: Map the most recent phase back to canonical order
        current_phase_idx = -1
        latest_phase_idx = -1
        if most_recent_phase_key and most_recent_activity:
            # Check if the most recent activity is within 3 hours (show live blue flickering only for recent phases)
            if most_recent_activity == current_time:
                # Currently active - always show as live
                live_eligible = True
            else:
                # Recently completed - check recency (only show live for activity within last 3 hours)
                time_since_activity = (current_time - most_recent_activity).total_seconds() / 3600
                live_eligible = (time_since_activity <= 3.0)
            
            if live_eligible:
                # Find this phase in the canonical order
                for idx, canonical_key in enumerate(canonical_order):
                    if canonical_key.lower() == most_recent_phase_key:
                        current_phase_idx = idx
                        break
            else:
                # Not live, but still remember the latest phase index for fallback gating
                for idx, canonical_key in enumerate(canonical_order):
                    if canonical_key.lower() == most_recent_phase_key:
                        latest_phase_idx = idx
                        break

        # Compute pivot time: latest non-transit phase start/end
        pivot_dt = None
        for p in timeline:
            phase_name = p.get('phase', '')
            if not phase_name or '_to_' in phase_name:
                continue
            s = parse_timestamp(p.get('start'))
            e = parse_timestamp(p.get('end'))
            candidate = e or s or None
            if candidate is not None and (pivot_dt is None or candidate > pivot_dt):
                pivot_dt = candidate
        
        # Determine trip chain start for display gating (avoid older trip dates)
        chain_start_dt = None
        try:
            # Primary: use the segment start exposed by the timebox engine.
            # This is the START of the last source-cluster visit (last Manawar visit for
            # dhar_to_dhule, last Dhule visit for dhule_to_dhar).  It is the authoritative
            # anchor: all phase data from before this point belongs to a prior trip and
            # should be treated as "pending" on the current canonical sequence.
            current_seg_start = entry.get('current_segment_start_ts')
            if current_seg_start:
                chain_start_dt = parse_timestamp(current_seg_start)

            if chain_start_dt is None:
                latest_start = entry.get('latest_trip_start_ts')
                current_start = entry.get('current_trip_start_ts')
                # Identify if current phase is at Manawar; if so, prefer latest trip start
                try:
                    if current_phase_idx != -1:
                        current_key = canonical_order[current_phase_idx].lower()
                    elif latest_phase_idx != -1:
                        current_key = canonical_order[latest_phase_idx].lower()
                    else:
                        current_key = ''
                except Exception:
                    current_key = ''
                is_in_manawar = current_key.startswith('manawar')
                if is_in_manawar and latest_start:
                    chain_start_dt = parse_timestamp(latest_start)
                elif current_start:
                    chain_start_dt = parse_timestamp(current_start)
                elif latest_start:
                    chain_start_dt = parse_timestamp(latest_start)
            # Fallback: if chain_start_dt is still None, derive earliest timestamp from today
            if chain_start_dt is None:
                try:
                    # Look back up to 36 hours to support cross-midnight trips
                    lookback_cutoff = current_time - timedelta(hours=36)
                    earliest_chain_dt = None
                    cutoff_idx = current_phase_idx if current_phase_idx != -1 else (latest_phase_idx if latest_phase_idx != -1 else len(canonical_order)-1)
                    for idx2 in range(0, cutoff_idx + 1):
                        key2 = canonical_order[idx2]
                        p2 = phase_data_map.get(key2.lower())
                        if not p2:
                            continue
                        s2 = parse_timestamp(p2.get('start'))
                        e2 = parse_timestamp(p2.get('end'))
                        for dtx in [s2, e2]:
                            if dtx and dtx >= lookback_cutoff:
                                if earliest_chain_dt is None or dtx < earliest_chain_dt:
                                    earliest_chain_dt = dtx
                    chain_start_dt = earliest_chain_dt
                    try:
                        logger.info(f"Chain gating fallback for {vehicle_number}: earliest_chain_dt={earliest_chain_dt}")
                    except Exception:
                        pass
                except Exception:
                    pass
            try:
                logger.info(f"Chain gating for {vehicle_number}: current_segment_start_ts={current_seg_start}, chain_start_dt={chain_start_dt}")
            except Exception:
                pass
        except Exception:
            chain_start_dt = None

        # Build checkpoints in canonical order - show all phases (existing + pending)
        checkpoints = []
        last_dt = None  # Ensure displayed times progress forward

        # Prune phase_data_map: remove any phase whose data is entirely from a previous trip
        # (all timestamps predate chain_start_dt). This prevents forward-trip phases that
        # overlap into the return canonical order (e.g. jhulwania_yard at 15:32 showing as
        # "completed" when the vehicle is on the return leg with chain_start_dt=19:00).
        if chain_start_dt is not None:
            _pruned = {}
            for _k, _p in phase_data_map.items():
                _dt_s = parse_timestamp(_p.get('start'))
                _dt_e = parse_timestamp(_p.get('end'))
                if (_dt_s and _dt_s >= chain_start_dt) or (_dt_e and _dt_e >= chain_start_dt):
                    _pruned[_k] = _p
                elif not _dt_s and not _dt_e:
                    _pruned[_k] = _p  # no timestamps → keep
            phase_data_map = _pruned

        # Find the last canonical index that has real phase data (post-pruning).
        last_data_idx = -1
        for _idx2, _ck2 in enumerate(canonical_order):
            if _ck2.lower() in phase_data_map:
                last_data_idx = _idx2

        for idx, key in enumerate(canonical_order):
            # Strict flow: mark any box after the most recent phase (live or latest) as pending.
            # Advance the cutoff to cover every canonical phase that has real data so that
            # a return-journey vehicle doesn't show forward phases as pending.
            base_cutoff = current_phase_idx if current_phase_idx != -1 else (latest_phase_idx if latest_phase_idx != -1 else -1)
            cutoff_idx = max(base_cutoff, last_data_idx)
            if cutoff_idx != -1 and idx > cutoff_idx:
                highlight_key, friendly_name = phase_map[key]
                checkpoints.append({
                    'name': friendly_name,
                    'time': '',
                    'end_time': '',
                    'status': 'pending',
                    'is_current': False,
                    'duration_minutes': 0,
                    'duration_hhmm': '',
                    'delay_minutes': 0,
                    'delay_hhmm': '',
                    'phase_key': key,
                })
                continue

            if key.lower() in phase_data_map:
                # Phase exists in data - show actual data
                phase = phase_data_map[key.lower()]
                dur = phase.get('duration_seconds') or 0
                # If duration_seconds is zero, try computing from raw start/end timestamps
                if dur == 0:
                    _raw_s = phase.get('start') or phase.get('display_start')
                    _raw_e = phase.get('end') or phase.get('display_end')
                    if _raw_s and _raw_e:
                        try:
                            _ts = parse_timestamp(_raw_s)
                            _te = parse_timestamp(_raw_e)
                            if _ts and _te and _te > _ts:
                                dur = int((_te - _ts).total_seconds())
                        except Exception:
                            pass
                highlight_key, friendly_name = phase_map[key]
                
                # Check if this is a gap-filled historical phase
                is_gap_filled = phase.get('gap_filled', False)
                is_historical = phase.get('historical', False)
                
                # Calculate duration in minutes
                duration_text = int(dur // 60) if dur > 0 else 0
                # Calculate duration HH:MM string ('-' when truly unknown/zero)
                duration_hhmm = f"{int(dur)//3600:02d}:{(int(dur)%3600)//60:02d}" if dur > 0 else "-"
                
                if is_gap_filled:
                    # Gap-filled phase - show as completed historical with proper data
                    status = 'completed_historical'
                    # Gap-filled phases may have minimal duration, calculate delay if SLA available
                    phase_key = highlight_key
                    sla = PHASE_SLA.get(phase_key)
                    delay_seconds = 0
                    if sla == 0 and phase_key in ['manawar_yard', 'jhulwania_yard', 'dhule_yard']:
                        delay_seconds = dur
                    elif sla and dur > sla:
                        delay_seconds = dur - sla
                    is_current = False
                else:
                    # Regular current phase - apply SLA logic
                    phase_key = highlight_key
                    sla = PHASE_SLA.get(phase_key)
                    status = 'on_time'
                    delay_seconds = 0
                    if sla == 0 and phase_key in ['manawar_yard', 'jhulwania_yard', 'dhule_yard']:
                        if dur > 0:
                            status = 'delayed'
                            delay_seconds = dur
                    elif sla:
                        if dur > sla:
                            status = 'delayed'
                            delay_seconds = dur - sla
                    # Determine if this is the live highlighted box
                    is_current = (idx == current_phase_idx)
                    # Only show 'warning' (amber) on the live highlighted box
                    if status == 'on_time' and is_current and sla and dur > 0 and dur > sla * 0.9:
                        status = 'warning'
                    
                if is_current:
                    current_transit = highlight_key
                
                # Extract time in HH:MM format from start/end timestamps
                def format_time_from_iso(iso_str):
                    if not iso_str or iso_str in ['Historical', 'Gap Filled', '']:
                        return ''
                    try:
                        # Try parsing ISO format
                        if 'T' in iso_str:
                            dt = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
                            return dt.strftime('%H:%M')
                        return iso_str  # Already formatted
                    except:
                        return iso_str
                
                # Use displayed times only if non-decreasing and before pivot (allow past dates for passed phases)
                dt_start = parse_timestamp(phase.get('display_start') or phase.get('start'))
                dt_end = parse_timestamp(phase.get('display_end') or phase.get('end'))
                display_time = ''
                display_end_time = ''
                display_ts = None
                # Location dwell phases (yard/charging/loading/unloading) are exempt from strict
                # ascending order — they can appear in any order within their location group.
                # All other phases (transits, maha_border) must have strictly ascending times.
                LOCATION_DWELL_KEYS = {
                    'manawar_yard', 'manawar_charging', 'manawar_loading',
                    'jhulwania_yard', 'jhulwania_charging',
                    'dhule_yard', 'dhule_charging', 'dhule_unloading',
                }
                is_location_dwell = key.lower() in LOCATION_DWELL_KEYS

                if is_location_dwell:
                    # Within a location: show time even if earlier than last_dt.
                    # Gate only on chain_start_dt and pivot_dt.
                    # Advance last_dt to the maximum time seen so transits after the group are gated correctly.
                    if dt_start and (pivot_dt is None or dt_start <= pivot_dt) and (chain_start_dt is None or dt_start >= chain_start_dt):
                        display_time = phase.get('display_start', '') or phase.get('time', '') or format_time_from_iso(phase.get('start', ''))
                        display_ts = int(dt_start.timestamp())
                        if last_dt is None or dt_start > last_dt:
                            last_dt = dt_start
                    elif dt_end and (pivot_dt is None or dt_end <= pivot_dt) and (chain_start_dt is None or dt_end >= chain_start_dt):
                        display_end_time = phase.get('display_end', '') or phase.get('end_time', '') or format_time_from_iso(phase.get('end', ''))
                        display_ts = int(dt_end.timestamp())
                        if last_dt is None or dt_end > last_dt:
                            last_dt = dt_end
                else:
                    # Transit and checkpoint phases: strictly ascending time order.
                    if dt_start and (pivot_dt is None or dt_start <= pivot_dt) and (last_dt is None or dt_start >= last_dt) and (chain_start_dt is None or dt_start >= chain_start_dt):
                        display_time = phase.get('display_start', '') or phase.get('time', '') or format_time_from_iso(phase.get('start', ''))
                        last_dt = dt_start
                        display_ts = int(dt_start.timestamp())
                    elif dt_end and (pivot_dt is None or dt_end <= pivot_dt) and (last_dt is None or dt_end >= last_dt) and (chain_start_dt is None or dt_end >= chain_start_dt):
                        display_end_time = phase.get('display_end', '') or phase.get('end_time', '') or format_time_from_iso(phase.get('end', ''))
                        last_dt = dt_end
                        display_ts = int(dt_end.timestamp())
                    else:
                        # Log suppression for debugging
                        try:
                            if chain_start_dt is not None:
                                if (dt_start and dt_start < chain_start_dt) or (dt_end and dt_end < chain_start_dt):
                                    logger.info(
                                        f"Chain suppression for {vehicle_number}: phase_key={key}, phase_name={phase.get('phase')}, dt_start={dt_start}, dt_end={dt_end}, chain_start_dt={chain_start_dt}"
                                    )
                        except Exception:
                            pass
                    
                # Add raw timestamp fields for template access
                raw_start = phase.get('start', '')
                raw_end = phase.get('end', '')
                raw_display_start = phase.get('display_start', '')
                raw_display_end = phase.get('display_end', '')
                    
                checkpoints.append({
                    'name': friendly_name,
                    'time': display_time,
                    'end_time': display_end_time,
                    'raw_start': raw_start,
                    'raw_end': raw_end,
                    'raw_display_start': raw_display_start,
                    'raw_display_end': raw_display_end,
                    'status': status,
                    'is_current': is_current,
                    'duration_minutes': duration_text,
                    'duration_hhmm': duration_hhmm,
                    'delay_seconds': int(delay_seconds) if delay_seconds > 0 else 0,
                    'delay_minutes': int(delay_seconds // 60) if delay_seconds > 0 else 0,
                    'delay_hhmm': (f"{int(delay_seconds)//3600:02d}:{(int(delay_seconds)%3600)//60:02d}" if delay_seconds and int(delay_seconds) > 0 else "00:00"),
                    'phase_key': key,  # Add phase key for grouping
                    'is_historical': is_historical,
                    'is_gap_filled': is_gap_filled,
                    'display_ts': display_ts,
                })
            else:
                # Phase not yet reached - ALWAYS show as pending (gray)
                # Do NOT predict colors for unvisited phases
                highlight_key, friendly_name = phase_map[key]
                
                checkpoints.append({
                    'name': friendly_name,
                    'time': '',  # No time for unvisited phases
                    'end_time': '',
                    'status': 'pending',  # ALWAYS pending (gray) for unvisited phases
                    'is_current': False,
                    'duration_minutes': 0,  # No duration data
                    'duration_hhmm': '',
                    'delay_minutes': 0,  # No delay data
                    'delay_hhmm': '',
                    'phase_key': key  # Add phase key for grouping
                })
        
        # Group checkpoints by location
        grouped_checkpoints = []
        # Define location groups
        location_groups = {
            'manawar': ['manawar_yard', 'manawar_charging', 'manawar_loading'],
            'jhulwania': ['jhulwania_yard', 'jhulwania_charging'],
            'dhule': ['dhule_yard', 'dhule_charging', 'dhule_unloading']
        }
        
        # Build grouped structure
        i = 0
        while i < len(checkpoints):
            current_checkpoint = checkpoints[i]
            phase_key = current_checkpoint['phase_key']
            
            # Check if this phase belongs to a location group
            location_name = None
            for loc, phases in location_groups.items():
                if phase_key in phases:
                    location_name = loc
                    break
            
            if location_name:
                # This is part of a location group
                group_phases = location_groups[location_name]
                group_checkpoints = []
                
                # Collect all checkpoints for this location that appear in order
                j = i
                while j < len(checkpoints) and checkpoints[j]['phase_key'] in group_phases:
                    group_checkpoints.append(checkpoints[j])
                    j += 1
                # Sort within the group by display_ts (ascending), keeping None at end
                group_checkpoints.sort(key=lambda cp: (cp.get('display_ts') is None, cp.get('display_ts') or 0))
                
                # Add the group
                grouped_checkpoints.append({
                    'type': 'group',
                    'location': location_name.capitalize(),
                    'checkpoints': group_checkpoints
                })
                
                i = j  # Move to next ungrouped checkpoint
            else:
                # This is a standalone checkpoint (transit)
                grouped_checkpoints.append({
                    'type': 'single',
                    'checkpoint': current_checkpoint
                })
                i += 1
        # Mark which transit box should be highlighted
        transit_highlight = None
        if current_transit:
            if 'manawar_to_jhulwania' in current_transit or 'jhulwania_to_manawar' in current_transit:
                transit_highlight = 'dhar_to_jhulwania'
            elif 'jhulwania_to_dhule' in current_transit or 'dhule_to_jhulwania' in current_transit:
                transit_highlight = 'jhulwania_to_dhule'
            elif 'dhule_to_maha_border' in current_transit or 'maha_border_to_dhule' in current_transit:
                transit_highlight = 'dhule_to_mh'
            elif 'maha_border_to_jhulwania' in current_transit or 'jhulwania_to_maha_border' in current_transit:
                transit_highlight = 'mh_to_jhulwania'
            elif 'jhulwania_to_dhar' in current_transit or 'dhar_to_jhulwania' in current_transit:
                transit_highlight = 'jhulwania_to_dhar'
        # Calculate total duration for display
        # Prefer current trip duration when positive; otherwise fall back to latest completed trip.
        # If neither is available, fallback to sum of phase durations.
        total_duration_seconds = 0
        try:
            if isinstance(entry, dict):
                ctd_raw = entry.get('current_trip_duration_seconds')
                ltd_raw = entry.get('latest_trip_duration_seconds')
                ctd = int(ctd_raw or 0)
                ltd = int(ltd_raw or 0)
                # If current box is within Manawar (yard/charging/loading), prefer latest trip over current
                try:
                    current_key = canonical_order[current_phase_idx].lower() if current_phase_idx != -1 else (canonical_order[latest_phase_idx].lower() if latest_phase_idx != -1 else '')
                except Exception:
                    current_key = ''
                is_in_manawar = current_key.startswith('manawar')
                # Fallback: derive current chain duration from today's phase timestamps up to cutoff when ctd is missing/zero
                cutoff_idx = current_phase_idx if current_phase_idx != -1 else (latest_phase_idx if latest_phase_idx != -1 else -1)
                ctd_fallback = 0
                try:
                    today_date = current_time.date()
                    min_dt = None
                    max_dt = None
                    if cutoff_idx != -1:
                        for idx2 in range(0, cutoff_idx + 1):
                            key2 = canonical_order[idx2]
                            p2 = phase_data_map.get(key2.lower())
                            if not p2:
                                continue
                            s2 = parse_timestamp(p2.get('start'))
                            e2 = parse_timestamp(p2.get('end'))
                            for dtx in [s2, e2]:
                                if dtx and dtx.date() == today_date:
                                    if min_dt is None or dtx < min_dt:
                                        min_dt = dtx
                                    if max_dt is None or dtx > max_dt:
                                        max_dt = dtx
                    if min_dt and max_dt and max_dt >= min_dt:
                        ctd_fallback = int((max_dt - min_dt).total_seconds())
                except Exception:
                    ctd_fallback = 0
                # Selection rules:
                # - At Manawar: prefer latest; if missing, fallback to sum (not current dwell)
                # - Away from Manawar: prefer current; else latest; else sum
                chosen_source = 'sum'
                if is_in_manawar:
                    if ltd > 0:
                        total_duration_seconds = ltd
                        chosen_source = 'latest'
                    elif ctd > 0:
                        total_duration_seconds = ctd
                        chosen_source = 'current'
                    elif ctd_fallback > 0:
                        total_duration_seconds = ctd_fallback
                        chosen_source = 'current_fallback_today'
                    else:
                        total_duration_seconds = int(sum(cp.get('duration_seconds', 0) for cp in entry.get('timeline', [])))
                        chosen_source = 'sum'
                else:
                    if ctd > 0:
                        total_duration_seconds = ctd
                        chosen_source = 'current'
                    elif ctd_fallback > 0:
                        total_duration_seconds = ctd_fallback
                        chosen_source = 'current_fallback_today'
                    elif ltd > 0:
                        total_duration_seconds = ltd
                        chosen_source = 'latest'
                    else:
                        total_duration_seconds = int(sum(cp.get('duration_seconds', 0) for cp in entry.get('timeline', [])))
                        chosen_source = 'sum'
                try:
                    logger.info(f"Duration selection for {vehicle_number}: ctd={ctd}, ctd_fallback_today={ctd_fallback}, ltd={ltd}, current_key={current_key}, is_in_manawar={is_in_manawar}, chosen={chosen_source}, total_seconds={total_duration_seconds}")
                except Exception:
                    pass
            else:
                total_duration_seconds = int(sum(cp.get('duration_seconds', 0) for cp in entry.get('timeline', [])))
        except Exception:
            total_duration_seconds = int(sum(cp.get('duration_seconds', 0) for cp in entry.get('timeline', [])))
        total_duration = f"{total_duration_seconds//3600:02d}:{(total_duration_seconds%3600)//60:02d}"
        # Calculate total drive time (sum of transit phases only)
        # Prefer current trip drive time, else latest completed, else fallback sum across phases
        if isinstance(entry, dict) and entry.get('current_trip_drive_seconds') is not None:
            drive_seconds = int(entry.get('current_trip_drive_seconds') or 0)
        elif isinstance(entry, dict) and entry.get('latest_trip_drive_seconds') is not None:
            drive_seconds = int(entry.get('latest_trip_drive_seconds') or 0)
        else:
            drive_seconds = 0
            for cp in entry.get('timeline', []):
                phase_name = cp.get('phase', '')
                if isinstance(phase_name, str) and '_to_' in phase_name:
                    drive_seconds += int(cp.get('duration_seconds') or 0)
        # Sanity: drive time cannot exceed total trip duration
        try:
            if total_duration_seconds is not None:
                drive_seconds = max(0, min(drive_seconds, total_duration_seconds))
        except Exception:
            pass
        total_drive_time = f"{drive_seconds//3600:02d}:{(drive_seconds%3600)//60:02d}"

        # Moving time since trip start (first box filled): prefer current trip drive seconds
        moving_since_start_seconds = None
        moving_since_start = "00:00"
        try:
            if isinstance(entry, dict) and entry.get('current_trip_drive_seconds') is not None:
                moving_since_start_seconds = int(entry.get('current_trip_drive_seconds') or 0)
                # Clamp to total duration
                if total_duration_seconds is not None:
                    moving_since_start_seconds = max(0, min(moving_since_start_seconds, total_duration_seconds))
                moving_since_start = f"{moving_since_start_seconds//3600:02d}:{(moving_since_start_seconds%3600)//60:02d}"
        except Exception:
            pass
        # Sum all per-phase delays (in seconds) - need to extract from grouped structure
        def extract_all_checkpoints(grouped_checkpoints):
            all_checkpoints = []
            for item in grouped_checkpoints:
                if item['type'] == 'group':
                    all_checkpoints.extend(item['checkpoints'])
                else:
                    all_checkpoints.append(item['checkpoint'])
            return all_checkpoints
        
        all_flat_checkpoints = extract_all_checkpoints(grouped_checkpoints)
        # Calculate total delay properly: delay per phase should not exceed that phase's duration
        # Total delay = sum of (max(0, phase_duration - phase_sla)) for all phases
        total_delay_seconds = 0
        ultratech_delay_seconds = 0
        driver_delay_seconds = 0
        
        # Phase SLA map for reference
        phase_sla_map = {
            'manawar_loading': PHASE_SLA.get('manawar_loading', 0),
            'dhule_unloading': PHASE_SLA.get('dhule_unloading', 0),
            'manawar_charging': PHASE_SLA.get('manawar_charging', 0),
            'dhule_charging': PHASE_SLA.get('dhule_charging', 0),
            'jhulwania_charging': PHASE_SLA.get('jhulwania_charging', 0),
            'maha_border': PHASE_SLA.get('maha_border', 0),
            'manawar_to_jhulwania': PHASE_SLA.get('manawar_to_jhulwania', 0),
            'jhulwania_to_manawar': PHASE_SLA.get('jhulwania_to_manawar', 0),
            'jhulwania_to_maha_border': PHASE_SLA.get('jhulwania_to_maha_border', 0),
            'maha_border_to_dhule': PHASE_SLA.get('maha_border_to_dhule', 0),
            'dhule_to_maha_border': PHASE_SLA.get('dhule_to_maha_border', 0),
            'maha_border_to_jhulwania': PHASE_SLA.get('maha_border_to_jhulwania', 0),
            'manawar_yard': PHASE_SLA.get('manawar_yard', 0),
            'jhulwania_yard': PHASE_SLA.get('jhulwania_yard', 0),
            'dhule_yard': PHASE_SLA.get('dhule_yard', 0),
        }
        
        # Split delay into Ultratech (Manawar + Dhule locations) vs Driver (rest)
        ultratech_phase_keys = set([
            'manawar_yard', 'manawar_charging', 'manawar_loading',
            'dhule_yard', 'dhule_charging', 'dhule_unloading'
        ])
        
        # Use pre-computed delay_seconds stored on each checkpoint (avoids precision
        # loss from converting dur → minutes → seconds in the previous approach).
        for cp in all_flat_checkpoints:
            phase_key = cp.get('phase_key', '')
            phase_delay_seconds = cp.get('delay_seconds', 0)
            
            # Add to totals
            total_delay_seconds += phase_delay_seconds
            
            if phase_key in ultratech_phase_keys:
                ultratech_delay_seconds += phase_delay_seconds
            else:
                driver_delay_seconds += phase_delay_seconds
        
        # Ensure total delay doesn't exceed total duration
        if total_duration_seconds is not None:
            total_delay_seconds = min(total_delay_seconds, total_duration_seconds)
        total_delay = f"{total_delay_seconds//3600:02d}:{(total_delay_seconds%3600)//60:02d}"
        ultratech_delay = f"{ultratech_delay_seconds//3600:02d}:{(ultratech_delay_seconds%3600)//60:02d}"
        driver_delay = f"{driver_delay_seconds//3600:02d}:{(driver_delay_seconds%3600)//60:02d}"
        transit_status = 'delayed' if any(cp['status']=='delayed' for cp in all_flat_checkpoints) else ('warning' if any(cp['status']=='warning' for cp in all_flat_checkpoints) else 'on_time')

        # Targeted flow debug for specific vehicle
        try:
            if vehicle_number and vehicle_number.lower().strip() in ['mh18bz3386','mh 18 bz 3386'] or (vehicle_number and vehicle_number.endswith('3386')):
                try:
                    debug_rows = [
                        f"{cp.get('phase_key')}: {cp.get('status')} time={cp.get('time')} end={cp.get('end_time')}"
                        for cp in all_flat_checkpoints
                    ]
                    logger.info(
                        f"Flow debug for {vehicle_number}: current_phase_idx={current_phase_idx}, canonical_order={canonical_order}, rows={debug_rows}"
                    )
                except Exception:
                    pass
        except Exception:
            pass
        
        return {
            'vehicle_number': vehicle_number,
            'route': entry.get('direction', ''),
            'total_duration': total_duration,
            'total_duration_seconds': total_duration_seconds,
            'total_delay': total_delay,
            'total_drive_time': total_drive_time,
            'total_drive_seconds': drive_seconds,
            'moving_since_start': moving_since_start,
            'moving_since_start_seconds': moving_since_start_seconds,
            'ultratech_delay': ultratech_delay,
            'driver_delay': driver_delay,
            'checkpoints': grouped_checkpoints,  # Use grouped checkpoints
            'transit_status': transit_status,
            'transit_highlight': transit_highlight
        }

    trucks = []
    for vn, entry in timeline_data.items():
        truck = map_timeline_to_truck(vn, entry)
        # Surface engine info to the UI JSON for verification
        if isinstance(entry, dict) and entry.get('engine'):
            truck['engine'] = entry.get('engine')
        if isinstance(entry, dict) and entry.get('latest_trip_duration_seconds') is not None:
            truck['latest_trip_duration_seconds'] = entry.get('latest_trip_duration_seconds')
        trucks.append(truck)
    
    # Fetch driver information for all trucks
    from roster.models import HorseTrolleyAssignment
    
    # Get all assignments with driver details in a single query
    assignments = HorseTrolleyAssignment.objects.select_related('driver').filter(
        horse__horse_number__in=[truck['vehicle_number'] for truck in trucks]
    )
    
    # Create a mapping of vehicle number to driver details
    driver_map = {}
    for assignment in assignments:
        driver_map[assignment.horse.horse_number] = {
            'driver_name': assignment.driver.employee_name if assignment.driver else None,
            'driver_phone': assignment.driver.phone if assignment.driver else None,
        }
    
    # Add driver information to each truck
    for truck in trucks:
        driver_info = driver_map.get(truck['vehicle_number'], {})
        truck['driver_name'] = driver_info.get('driver_name')
        truck['driver_phone'] = driver_info.get('driver_phone')
    
    # Sort by delay (delayed first)
    trucks.sort(key=lambda x: x['total_delay'], reverse=True)
    on_time_count = sum(1 for truck in trucks if truck['total_delay'] == '00:00')
    delayed_count = len(trucks) - on_time_count
    
    # Compute averages for Duration, Delay, and Drive Time across trucks
    def _hhmm_to_seconds(hhmm: str) -> int:
        try:
            if not hhmm or ':' not in hhmm:
                return 0
            h, m = hhmm.split(':', 1)
            return int(h) * 3600 + int(m) * 60
        except Exception:
            return 0
    def _sec_to_hhmm(seconds: int) -> str:
        seconds = max(0, int(seconds))
        return f"{seconds//3600:02d}:{(seconds%3600)//60:02d}"

    n = max(1, len(trucks))
    total_duration_avg = _sec_to_hhmm(sum(_hhmm_to_seconds(t['total_duration']) for t in trucks) // n)
    total_delay_avg = _sec_to_hhmm(sum(_hhmm_to_seconds(t['total_delay']) for t in trucks) // n)
    total_drive_time_avg = _sec_to_hhmm(sum(_hhmm_to_seconds(t.get('total_drive_time', '00:00')) for t in trucks) // n)
    
    # Add JSON output support for testing
    if request.GET.get('format') == 'json':
        return JsonResponse({
            'trucks': trucks,
            'on_time_count': on_time_count,
            'delayed_count': delayed_count,
            'total_trucks': len(trucks)
        })
    
    return render(request, 'livetracker/timelineTable.html', {
        'trucks': trucks,
        'on_time_count': on_time_count,
        'delayed_count': delayed_count,
        'total_trucks': len(trucks),
        'avg_total_duration': total_duration_avg,
        'avg_total_delay': total_delay_avg,
        'avg_total_drive_time': total_drive_time_avg,
    })



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
def timebox_avg_delay_series(request):
    """
    Return average delay time series.
    Query params:
      - group_by: 'day' (default) or 'month'
      - days: when group_by=day (default 7, max 31)
      - months: when group_by=month (default 3, max 12)
      - month: YYYY-MM to get a specific month's day-wise series (overrides days)
    Response:
      { series: [{label,date,avg_delay,avg_delay_minutes}], unit: 'minutes', group_by: 'day'|'month' }
    """
    group_by = request.GET.get('group_by', 'day').lower()
    month_param = request.GET.get('month')

    # SLA thresholds per phase (seconds)
    from .alertService import alert_constants as ac
    PHASE_SLA = {
        'manawar_loading': ac.LOADING_DWELL_SECONDS,
        'dhule_unloading': ac.UNLOADING_DWELL_SECONDS,
        'manawar_charging': ac.CHARGING_OVER_SECONDS,
        'dhule_charging': ac.CHARGING_OVER_SECONDS,
        'jhulwania_charging': ac.CHARGING_OVER_SECONDS,
        'maha_border': ac.MAHA_BORDER_DWELL_SECONDS,
        # Transit phases targets
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

    def _calc_vehicle_delay_seconds(timeline: list) -> int:
        """
        Calculate total delay for a vehicle journey.
        
        Delay = time spent OVER the SLA for each phase.
        - Transit phases (sla=0): No delay counted
        - Yard phases (sla=0): No delay counted  
        - Charging/Loading phases (sla>0): Delay = max(0, duration - sla)
        """
        total = 0
        for phase in timeline or []:
            name = (phase.get('phase') or '').lower()
            dur = int(phase.get('duration_seconds') or 0)
            if not name or dur <= 0:
                continue
            
            # Normalize phase name
            key = name.replace('mahaborder', 'maha_border').replace('maha border', 'maha_border')
            
            # Get SLA for this phase
            sla = PHASE_SLA.get(key)
            if sla is None:
                # If not in PHASE_SLA dict, check if it's a transit phase
                if '_to_' in key:
                    sla = 0  # Transit phases have no SLA
                else:
                    continue  # Unknown phase, skip
            
            # Calculate delay: only count time OVER the SLA threshold
            # sla can be 0 (for yards/transit) or positive (for charging/loading)
            if sla is not None and sla > 0 and dur > sla:
                # Count only the excess time beyond SLA
                total += (dur - sla)
            # Note: sla=0 phases (yards, transit) don't contribute to delay
        
        return max(0, int(total))

    def _serialize_day_obj(date_obj, avg_minutes: int) -> dict:
        return {
            'date': date_obj.strftime('%Y-%m-%d'),
            'avg_delay': f"{(avg_minutes//60):02d}:{(avg_minutes%60):02d}",
            'avg_delay_minutes': avg_minutes,
        }

    def _compute_day_avg(date_obj) -> dict:
        start = date_obj.strftime('%Y-%m-%d')
        end = (date_obj + timedelta(days=1)).strftime('%Y-%m-%d')
        cache_key = f"tb:day:{start}"
        # Prefer DB cache first
        try:
            db_row = TimeBoxDailyAvgDelay.objects.filter(date=date_obj).first()
            if db_row:
                result = _serialize_day_obj(date_obj, int(db_row.avg_delay_minutes or 0))
                cache.set(cache_key, result, timeout=60 * 60 * 24)
                return result
        except Exception:
            pass
        # Fallback: mem cache
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
        for vn, points in by_vehicle.items():
            try:
                journey = build_timebox_for_vehicle(points)
                timeline = journey.get('timeline', [])
                delay_sec = _calc_vehicle_delay_seconds(timeline)
                delays.append(delay_sec)
            except Exception:
                continue
        avg_sec = (sum(delays) // len(delays)) if delays else 0
        result = _serialize_day_obj(date_obj, (avg_sec // 60))
        # Best-effort persist to DB for future fast loads
        try:
            TimeBoxDailyAvgDelay.objects.update_or_create(
                date=date_obj,
                defaults={
                    'avg_delay_minutes': (avg_sec // 60),
                    'vehicle_count': len(delays),
                }
            )
        except Exception:
            pass
        cache.set(cache_key, result, timeout=60 * 60 * 24)  # cache 24h
        return result

    def _compute_month_day_series(year: int, month: int):
        month_key = f"tb:month_days:{year:04d}-{month:02d}"
        cached = cache.get(month_key)
        if cached is not None:
            return cached
        # iterate all days in the month
        first = datetime(year, month, 1).date()
        if month == 12:
            next_month = datetime(year + 1, 1, 1).date()
        else:
            next_month = datetime(year, month + 1, 1).date()
        days = []
        d = first
        while d < next_month:
            days.append(_compute_day_avg(d))
            d += timedelta(days=1)
        cache.set(month_key, days, timeout=60 * 60 * 6)  # 6 hours
        return days

    if group_by == 'month':
        try:
            months = int(request.GET.get('months', 3))
            months = max(1, min(months, 12))
        except Exception:
            months = 3
        # series-level cache
        cache_key = f"tb:series:month:{months}"
        cached = cache.get(cache_key)
        if cached is not None:
            return JsonResponse({ 'series': cached, 'unit': 'minutes', 'group_by': 'month' })
        # compute last N calendar months
        today = datetime.now().date().replace(day=1)
        series = []
        for i in range(months - 1, -1, -1):
            # target month start
            month_index = (today.year * 12 + (today.month - 1)) - i
            year = month_index // 12
            month = (month_index % 12) + 1
            label = f"{year:04d}-{month:02d}"
            # Prefer DB for day-wise series
            try:
                month_days_db = TimeBoxDailyAvgDelay.objects.filter(
                    date__gte=datetime(year, month, 1).date(),
                    date__lt=(datetime(year, month, 1) + timedelta(days=32)).replace(day=1).date()
                ).order_by('date')
                if month_days_db.exists():
                    mins = [int(row.avg_delay_minutes or 0) for row in month_days_db]
                else:
                    # Fallback to compute+cache
                    days = _compute_month_day_series(year, month)
                    mins = [p['avg_delay_minutes'] for p in days if p]
            except Exception:
                days = _compute_month_day_series(year, month)
                mins = [p['avg_delay_minutes'] for p in days if p]
            avg_m = (sum(mins) // len(mins)) if mins else 0
            series.append({ 'date': label, 'label': label, 'avg_delay': f"{(avg_m//60):02d}:{(avg_m%60):02d}", 'avg_delay_minutes': avg_m })
        cache.set(cache_key, series, timeout=60 * 60 * 6)
        return JsonResponse({ 'series': series, 'unit': 'minutes', 'group_by': 'month' })

    # group_by day
    # If a specific month is requested, return that month's day-wise series
    if month_param:
        try:
            year, month = map(int, month_param.split('-'))
            # Prefer DB day rows for the month
            try:
                month_days_db = TimeBoxDailyAvgDelay.objects.filter(
                    date__gte=datetime(year, month, 1).date(),
                    date__lt=(datetime(year, month, 1) + timedelta(days=32)).replace(day=1).date()
                ).order_by('date')
                if month_days_db.exists():
                    days = [
                        _serialize_day_obj(row.date, int(row.avg_delay_minutes or 0))
                        for row in month_days_db
                    ]
                else:
                    days = _compute_month_day_series(year, month)
            except Exception:
                days = _compute_month_day_series(year, month)
            return JsonResponse({ 'series': days, 'unit': 'minutes', 'group_by': 'day', 'month': month_param })
        except Exception:
            pass
    try:
        days_count = int(request.GET.get('days', 7))
        days_count = max(1, min(days_count, 31))
    except Exception:
        days_count = 7
    cache_key = f"tb:series:day:{days_count}"
    cached = cache.get(cache_key)
    if cached is not None:
        return JsonResponse({ 'series': cached, 'unit': 'minutes', 'group_by': 'day' })
    # Prefer DB for last N days
    try:
        today = datetime.now().date()
        start = today - timedelta(days=days_count - 1)
        db_rows = TimeBoxDailyAvgDelay.objects.filter(date__gte=start, date__lte=today).order_by('date')
        if db_rows.exists() and db_rows.count() == days_count:
            series = [
                _serialize_day_obj(row.date, int(row.avg_delay_minutes or 0))
                for row in db_rows
            ]
            cache.set(cache_key, series, timeout=60 * 30)
            return JsonResponse({ 'series': series, 'unit': 'minutes', 'group_by': 'day' })
    except Exception:
        pass
    # Fallback: compute+cache
    series = []
    today = datetime.now().date()
    for i in range(days_count - 1, -1, -1):
        d = today - timedelta(days=i)
        series.append(_compute_day_avg(d))
    cache.set(cache_key, series, timeout=60 * 30)  # 30 minutes
    return JsonResponse({ 'series': series, 'unit': 'minutes', 'group_by': 'day' })


@login_required
@require_http_methods(["GET"])
def timebox_avg_delay_series_v2(request):
    """
    ⚡ OPTIMIZED trend graph API - uses pre-computed delay data from CalculatedTrip
    
    🚀 Performance improvement: Uses fast SQL aggregation instead of real-time GPS processing
    Response time: 50-200ms (vs 30-60s for original) = 100-300x faster!
    
    Query params: Same as original (group_by, days, months, month)
    Response: Same format as original for frontend compatibility  
    """
    from mis.models import CalculatedTrip
    from django.db.models import Avg, Count, Q, F
    from django.core.cache import cache
    from datetime import datetime, timedelta
    import logging

    logger = logging.getLogger(__name__)
    group_by = request.GET.get('group_by', 'day').lower()
    month_param = request.GET.get('month')

    def _serialize_day_obj(date_obj, avg_minutes: int, trip_count: int = 0) -> dict:
        return {
            'date': date_obj.strftime('%Y-%m-%d'),
            'avg_delay': f"{(avg_minutes//60):02d}:{(avg_minutes%60):02d}",
            'avg_delay_minutes': avg_minutes,
            'trip_count': trip_count,
            'data_source': 'calculated_trip_v2'
        }

    def _compute_day_avg_optimized(date_obj) -> dict:
        """
        🔥 FAST path: Use pre-computed delay data from CalculatedTrip table
        
        Performance: ~5ms SQL query vs ~30+ seconds real-time GPS processing
        """
        cache_key = f"tb:v2:day:{date_obj.strftime('%Y-%m-%d')}"
        
        # Check cache first  
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
            
        # Query pre-computed trip delays for this date
        trips = CalculatedTrip.objects.filter(
            log_date=date_obj,
            total_delay_s__isnull=False  # Only trips with computed delays
        ).aggregate(
            avg_delay_seconds=Avg('total_delay_s'),
            trip_count=Count('id')
        )
        
        avg_delay_seconds = trips['avg_delay_seconds'] or 0
        trip_count = trips['trip_count'] or 0
        avg_delay_minutes = int(avg_delay_seconds // 60)
        
        result = _serialize_day_obj(date_obj, avg_delay_minutes, trip_count)
        
        # Cache for 6 hours (shorter than original since data updates frequently)
        cache.set(cache_key, result, timeout=60 * 60 * 6)
        return result

    # Handle different grouping modes (same logic as original)
    if group_by == 'month':
        try:
            months = int(request.GET.get('months', 3))
            months = max(1, min(months, 12))
        except Exception:
            months = 3
            
        cache_key = f"tb:v2:series:month:{months}"
        cached = cache.get(cache_key)
        if cached is not None:
            return JsonResponse({ 'series': cached, 'unit': 'minutes', 'group_by': 'month' })
            
        # Compute monthly averages using optimized daily data
        today = datetime.now().date().replace(day=1)
        series = []
        
        for i in range(months - 1, -1, -1):
            month_index = (today.year * 12 + (today.month - 1)) - i
            year = month_index // 12
            month = (month_index % 12) + 1
            label = f"{year:04d}-{month:02d}"
            
            # Get all days in this month from CalculatedTrip
            first_day = datetime(year, month, 1).date()
            if month == 12:
                last_day = datetime(year + 1, 1, 1).date()
            else:
                last_day = datetime(year, month + 1, 1).date()
                
            month_trips = CalculatedTrip.objects.filter(
                log_date__gte=first_day,
                log_date__lt=last_day,
                total_delay_s__isnull=False
            ).aggregate(
                avg_delay_seconds=Avg('total_delay_s'),
                trip_count=Count('id')
            )
            
            avg_seconds = month_trips['avg_delay_seconds'] or 0
            avg_minutes = int(avg_seconds // 60)
            
            series.append({
                'date': label,
                'label': label, 
                'avg_delay': f"{(avg_minutes//60):02d}:{(avg_minutes%60):02d}",
                'avg_delay_minutes': avg_minutes,
                'trip_count': month_trips['trip_count'],
                'data_source': 'calculated_trip_v2'
            })
            
        cache.set(cache_key, series, timeout=60 * 60 * 6)
        return JsonResponse({ 'series': series, 'unit': 'minutes', 'group_by': 'month' })

    # Daily grouping 
    if month_param:
        # Specific month day-wise series
        try:
            year, month = map(int, month_param.split('-'))
            first_day = datetime(year, month, 1).date()
            if month == 12:
                last_day = datetime(year + 1, 1, 1).date()
            else:
                last_day = datetime(year, month + 1, 1).date()
                
            # Get daily averages for the entire month
            daily_data = CalculatedTrip.objects.filter(
                log_date__gte=first_day,
                log_date__lt=last_day,
                total_delay_s__isnull=False
            ).values('log_date').annotate(
                avg_delay_seconds=Avg('total_delay_s'),
                trip_count=Count('id')
            ).order_by('log_date')
            
            series = []
            for day_data in daily_data:
                avg_seconds = day_data['avg_delay_seconds'] or 0
                avg_minutes = int(avg_seconds // 60)
                series.append({
                    'date': day_data['log_date'].strftime('%Y-%m-%d'),
                    'avg_delay': f"{(avg_minutes//60):02d}:{(avg_minutes%60):02d}",
                    'avg_delay_minutes': avg_minutes,
                    'trip_count': day_data['trip_count'],
                    'data_source': 'calculated_trip_v2'
                })
                
            return JsonResponse({ 'series': series, 'unit': 'minutes', 'group_by': 'day', 'month': month_param })
        except Exception:
            pass
    
    # Last N days series (default)
    try:
        days_count = int(request.GET.get('days', 7))
        days_count = max(1, min(days_count, 31))
    except Exception:
        days_count = 7
        
    cache_key = f"tb:v2:series:day:{days_count}"
    cached = cache.get(cache_key)
    if cached is not None:
        return JsonResponse({ 'series': cached, 'unit': 'minutes', 'group_by': 'day' })
        
    # Get daily averages for last N days
    today = datetime.now().date()
    start_date = today - timedelta(days=days_count - 1)
    
    daily_data = CalculatedTrip.objects.filter(
        log_date__gte=start_date,
        log_date__lte=today,
        total_delay_s__isnull=False
    ).values('log_date').annotate(
        avg_delay_seconds=Avg('total_delay_s'),
        trip_count=Count('id')
    ).order_by('log_date')
    
    # Convert to series format
    series = []
    for day_data in daily_data:
        avg_seconds = day_data['avg_delay_seconds'] or 0
        avg_minutes = int(avg_seconds // 60)
        series.append({
            'date': day_data['log_date'].strftime('%Y-%m-%d'),
            'avg_delay': f"{(avg_minutes//60):02d}:{(avg_minutes%60):02d}",
            'avg_delay_minutes': avg_minutes,
            'trip_count': day_data['trip_count'],
            'data_source': 'calculated_trip_v2'
        })
    
    cache.set(cache_key, series, timeout=60 * 30)
    return JsonResponse({ 'series': series, 'unit': 'minutes', 'group_by': 'day' })


@login_required
@require_http_methods(["GET"])  
def timebox_phase_breakdown_api(request):
    """
    🆕 NEW API: Phase-wise delay breakdown for detailed trend analysis
    
    Returns delay breakdown by phase (loading, unloading, charging, etc.)
    Enables drill-down analysis of which operations cause most delays
    """
    from mis.models import CalculatedTrip
    from django.db.models import Avg, Sum, Count, F
    
    days = int(request.GET.get('days', 7))
    days = max(1, min(days, 31))
    
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=days - 1)
    
    # Get phase-wise delay averages
    phase_breakdown = CalculatedTrip.objects.filter(
        log_date__gte=start_date,
        log_date__lte=end_date,
        total_delay_s__isnull=False
    ).aggregate(
        avg_manawar_loading_delay_min=Avg(F('manawar_loading_delay_s') / 60),
        avg_dhule_unloading_delay_min=Avg(F('dhule_unloading_delay_s') / 60), 
        avg_manawar_charging_delay_min=Avg(F('manawar_charging_delay_s') / 60),
        avg_dhule_charging_delay_min=Avg(F('dhule_charging_delay_s') / 60),
        avg_jhulwania_charging_delay_min=Avg(F('jhulwania_charging_delay_s') / 60),
        avg_maha_border_delay_min=Avg(F('maha_border_delay_s') / 60),
        avg_ultratech_delay_min=Avg(F('ultratech_delay_s') / 60),
        avg_driver_delay_min=Avg(F('driver_delay_s') / 60),
        total_trips=Count('id')
    )
    
    # Format response
    breakdown = {
        'manawar_loading': {
            'name': 'Manawar Loading',
            'avg_delay_minutes': int(phase_breakdown['avg_manawar_loading_delay_min'] or 0),
            'category': 'ultratech'
        },
        'dhule_unloading': {
            'name': 'Dhule Unloading', 
            'avg_delay_minutes': int(phase_breakdown['avg_dhule_unloading_delay_min'] or 0),
            'category': 'ultratech'
        },
        'manawar_charging': {
            'name': 'Manawar Charging',
            'avg_delay_minutes': int(phase_breakdown['avg_manawar_charging_delay_min'] or 0),
            'category': 'ultratech'
        },
        'dhule_charging': {
            'name': 'Dhule Charging',
            'avg_delay_minutes': int(phase_breakdown['avg_dhule_charging_delay_min'] or 0), 
            'category': 'ultratech'
        },
        'jhulwania_charging': {
            'name': 'Jhulwania Charging',
            'avg_delay_minutes': int(phase_breakdown['avg_jhulwania_charging_delay_min'] or 0),
            'category': 'driver'
        },
        'maha_border': {
            'name': 'MH Border Crossing',
            'avg_delay_minutes': int(phase_breakdown['avg_maha_border_delay_min'] or 0),
            'category': 'driver'
        }
    }
    
    return JsonResponse({
        'breakdown': breakdown,
        'summary': {
            'ultratech_avg_delay_minutes': int(phase_breakdown['avg_ultratech_delay_min'] or 0),
            'driver_avg_delay_minutes': int(phase_breakdown['avg_driver_delay_min'] or 0),
            'total_trips': phase_breakdown['total_trips'],
            'period_days': days,
            'start_date': start_date.strftime('%Y-%m-%d'),
            'end_date': end_date.strftime('%Y-%m-%d')
        }
    })


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
        logger.info(f"✅ TWINS API response: {data.get('total_vehicles', '?')} vehicles (spv={spv})")

        # Normalize gps_time in every point to IST ISO string so the
        # frontend hover card and sidebar show the same time as playback.
        import pytz as _pytz
        _ist_tz = _pytz.timezone('Asia/Kolkata')
        vehicles_raw = data.get('vehicles', {})
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
        # Build URL for 24hr full route data with vendor and spv filters
        api_url = f"{twins_url}fetch_points?spv={_spv}&vendor={_vendor}&page_size=5000&registration_number={registration_number}"
        
        logger.info(f"🔄 Proxying TWINS 24hr route request: registration_number={registration_number}")
        
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
        
        # Handle 404 errors gracefully - vehicle may not have 24hr data available
        if response.status_code == 404:
            logger.warning(f"⚠️ Vehicle {registration_number} not found in TWINS 24hr data - may not have historical data available")
            return JsonResponse({
                'error': f'No 24-hour playback data available for vehicle {registration_number}. This vehicle may not have location tracking enabled or sufficient data.',
                'points': [],
                'registration_number': registration_number
            }, status=200)  # Return 200 with empty points instead of 404
        
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
            logger.warning(f"⚠️ No points returned from TWINS API for {registration_number}")
            return JsonResponse({'points': [], 'registration_number': registration_number}, safe=True)
        
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
                'heading': float(point.get('head', 0)) if point.get('head') else None,  # TWINS uses 'head' for heading
                'gps_heading': float(point.get('head', 0)) if point.get('head') else None,
                'speed': float(point.get('speed', 0)) if point.get('speed') is not None else 0,
                'gps_speed': float(point.get('speed', 0)) if point.get('speed') is not None else 0,
                'soc': (int(float(point['soc'])) if point.get('soc') is not None else (int(float(point['battery_soc'])) if point.get('battery_soc') is not None else None)),
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
def timebox_avg_delay_series_v2(request):
    """
    OPTIMIZED trend graph API - uses pre-computed delay data from CalculatedTrip
    
    🚀 Performance improvement: Uses fast SQL aggregation instead of real-time GPS processing
    
    Query params: Same as original (group_by, days, months, month)
    Response: Same format as original for frontend compatibility  
    """
    from mis.models import CalculatedTrip
    from django.db.models import Avg, Count, Q, F
    
    group_by = request.GET.get('group_by', 'day').lower()
    month_param = request.GET.get('month')

    def _serialize_day_obj(date_obj, avg_minutes: int) -> dict:
        return {
            'date': date_obj.strftime('%Y-%m-%d'),
            'avg_delay': f"{(avg_minutes//60):02d}:{(avg_minutes%60):02d}",
            'avg_delay_minutes': avg_minutes,
        }

    def _compute_day_avg_optimized(date_obj) -> dict:
        """
        FAST path: Use pre-computed delay data from CalculatedTrip table
        
        Performance: ~5ms SQL query vs ~30+ seconds real-time GPS processing
        """
        cache_key = f"tb:v2:day:{date_obj.strftime('%Y-%m-%d')}"
        
        # Check cache first  
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
            
        # Query pre-computed trip delays for this date
        trips = CalculatedTrip.objects.filter(
            log_date=date_obj,
            total_delay_s__isnull=False  # Only trips with computed delays
        ).aggregate(
            avg_delay_seconds=Avg('total_delay_s'),
            trip_count=Count('id')
        )
        
        avg_delay_seconds = trips['avg_delay_seconds'] or 0
        trip_count = trips['trip_count'] or 0
        avg_delay_minutes = int(avg_delay_seconds // 60)
        
        result = _serialize_day_obj(date_obj, avg_delay_minutes)
        
        # Add metadata for debugging 
        result['trip_count'] = trip_count
        result['data_source'] = 'calculated_trip_v2'
        
        # Cache for 6 hours (shorter than original since data updates frequently)
        cache.set(cache_key, result, timeout=60 * 60 * 6)
        return result

    # Handle different grouping modes (same logic as original)
    if group_by == 'month':
        try:
            months = int(request.GET.get('months', 3))
            months = max(1, min(months, 12))
        except Exception:
            months = 3
            
        cache_key = f"tb:v2:series:month:{months}"
        cached = cache.get(cache_key)
        if cached is not None:
            return JsonResponse({ 'series': cached, 'unit': 'minutes', 'group_by': 'month' })
            
        # Compute monthly averages using optimized daily data
        today = datetime.now().date().replace(day=1)
        series = []
        
        for i in range(months - 1, -1, -1):
            month_index = (today.year * 12 + (today.month - 1)) - i
            year = month_index // 12
            month = (month_index % 12) + 1
            label = f"{year:04d}-{month:02d}"
            
            # Get all days in this month from CalculatedTrip
            first_day = datetime(year, month, 1).date()
            if month == 12:
                last_day = datetime(year + 1, 1, 1).date()
            else:
                last_day = datetime(year, month + 1, 1).date()
                
            month_trips = CalculatedTrip.objects.filter(
                log_date__gte=first_day,
                log_date__lt=last_day,
                total_delay_s__isnull=False
            ).aggregate(
                avg_delay_seconds=Avg('total_delay_s'),
                trip_count=Count('id')
            )
            
            avg_seconds = month_trips['avg_delay_seconds'] or 0
            avg_minutes = int(avg_seconds // 60)
            
            series.append({
                'date': label,
                'label': label, 
                'avg_delay': f"{(avg_minutes//60):02d}:{(avg_minutes%60):02d}",
                'avg_delay_minutes': avg_minutes,
                'trip_count': month_trips['trip_count'],
                'data_source': 'calculated_trip_v2'
            })
            
        cache.set(cache_key, series, timeout=60 * 60 * 6)
        return JsonResponse({ 'series': series, 'unit': 'minutes', 'group_by': 'month' })

    # Daily grouping 
    if month_param:
        # Specific month day-wise series
        try:
            year, month = map(int, month_param.split('-'))
            first_day = datetime(year, month, 1).date()
            if month == 12:
                last_day = datetime(year + 1, 1, 1).date()
            else:
                last_day = datetime(year, month + 1, 1).date()
                
            # Get daily averages for the entire month
            daily_data = CalculatedTrip.objects.filter(
                log_date__gte=first_day,
                log_date__lt=last_day,
                total_delay_s__isnull=False
            ).values('log_date').annotate(
                avg_delay_seconds=Avg('total_delay_s'),
                trip_count=Count('id')
            ).order_by('log_date')
            
            series = []
            for day_data in daily_data:
                avg_seconds = day_data['avg_delay_seconds'] or 0
                avg_minutes = int(avg_seconds // 60)
                series.append({
                    'date': day_data['log_date'].strftime('%Y-%m-%d'),
                    'avg_delay': f"{(avg_minutes//60):02d}:{(avg_minutes%60):02d}",
                    'avg_delay_minutes': avg_minutes,
                    'trip_count': day_data['trip_count'],
                    'data_source': 'calculated_trip_v2'
                })
                
            return JsonResponse({ 'series': series, 'unit': 'minutes', 'group_by': 'day', 'month': month_param })
        except Exception:
            pass
    
    # Last N days series (default)
    try:
        days_count = int(request.GET.get('days', 7))
        days_count = max(1, min(days_count, 31))
    except Exception:
        days_count = 7
        
    cache_key = f"tb:v2:series:day:{days_count}"
    cached = cache.get(cache_key)
    if cached is not None:
        return JsonResponse({ 'series': cached, 'unit': 'minutes', 'group_by': 'day' })
        
    # Get daily averages for last N days
    today = datetime.now().date()
    start_date = today - timedelta(days=days_count - 1)
    
    daily_data = CalculatedTrip.objects.filter(
        log_date__gte=start_date,
        log_date__lte=today,
        total_delay_s__isnull=False
    ).values('log_date').annotate(
        avg_delay_seconds=Avg('total_delay_s'),
        trip_count=Count('id')
    ).order_by('log_date')
    
    # Convert to series format
    series = []
    for day_data in daily_data:
        avg_seconds = day_data['avg_delay_seconds'] or 0
        avg_minutes = int(avg_seconds // 60)
        series.append({
            'date': day_data['log_date'].strftime('%Y-%m-%d'),
            'avg_delay': f"{(avg_minutes//60):02d}:{(avg_minutes%60):02d}",
            'avg_delay_minutes': avg_minutes,
            'trip_count': day_data['trip_count'],
            'data_source': 'calculated_trip_v2'
        })
    
    cache.set(cache_key, series, timeout=60 * 30)
    return JsonResponse({ 'series': series, 'unit': 'minutes', 'group_by': 'day' })


@login_required
@require_http_methods(["GET"])  
def timebox_phase_breakdown_api(request):
    """
    NEW API: Phase-wise delay breakdown for detailed trend analysis
    
    Returns delay breakdown by phase (loading, unloading, charging, etc.)
    Enables drill-down analysis of which operations cause most delays
    """
    from mis.models import CalculatedTrip
    from django.db.models import Avg, Sum, Count
    
    days = int(request.GET.get('days', 7))
    days = max(1, min(days, 31))
    
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=days - 1)
    
    # Get phase-wise delay averages
    phase_breakdown = CalculatedTrip.objects.filter(
        log_date__gte=start_date,
        log_date__lte=end_date
    ).aggregate(
        avg_manawar_loading_delay_min=Avg(F('manawar_loading_delay_s') / 60),
        avg_dhule_unloading_delay_min=Avg(F('dhule_unloading_delay_s') / 60), 
        avg_manawar_charging_delay_min=Avg(F('manawar_charging_delay_s') / 60),
        avg_dhule_charging_delay_min=Avg(F('dhule_charging_delay_s') / 60),
        avg_jhulwania_charging_delay_min=Avg(F('jhulwania_charging_delay_s') / 60),
        avg_maha_border_delay_min=Avg(F('maha_border_delay_s') / 60),
        avg_ultratech_delay_min=Avg(F('ultratech_delay_s') / 60),
        avg_driver_delay_min=Avg(F('driver_delay_s') / 60),
        total_trips=Count('id')
    )
    
    # Format response
    breakdown = {
        'manawar_loading': {
            'name': 'Manawar Loading',
            'avg_delay_minutes': int(phase_breakdown['avg_manawar_loading_delay_min'] or 0),
            'category': 'ultratech'
        },
        'dhule_unloading': {
            'name': 'Dhule Unloading', 
            'avg_delay_minutes': int(phase_breakdown['avg_dhule_unloading_delay_min'] or 0),
            'category': 'ultratech'
        },
        'manawar_charging': {
            'name': 'Manawar Charging',
            'avg_delay_minutes': int(phase_breakdown['avg_manawar_charging_delay_min'] or 0),
            'category': 'ultratech'
        },
        'dhule_charging': {
            'name': 'Dhule Charging',
            'avg_delay_minutes': int(phase_breakdown['avg_dhule_charging_delay_min'] or 0), 
            'category': 'ultratech'
        },
        'jhulwania_charging': {
            'name': 'Jhulwania Charging',
            'avg_delay_minutes': int(phase_breakdown['avg_jhulwania_charging_delay_min'] or 0),
            'category': 'driver'
        },
        'maha_border': {
            'name': 'MH Border Crossing',
            'avg_delay_minutes': int(phase_breakdown['avg_maha_border_delay_min'] or 0),
            'category': 'driver'
        }
    }
    
    return JsonResponse({
        'breakdown': breakdown,
        'summary': {
            'ultratech_avg_delay_minutes': int(phase_breakdown['avg_ultratech_delay_min'] or 0),
            'driver_avg_delay_minutes': int(phase_breakdown['avg_driver_delay_min'] or 0),
            'total_trips': phase_breakdown['total_trips'],
            'period_days': days,
            'start_date': start_date.strftime('%Y-%m-%d'),
            'end_date': end_date.strftime('%Y-%m-%d')
        }
    })

# ======================
# GEOFENCE ENDPOINTS
# ======================

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
