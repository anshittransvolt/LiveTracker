"""
Global Tracker Views

Secure views for global vehicle tracking system using external API proxy pattern.
Works exactly like livetracker by proxying external TWINS API calls.

All external API calls are proxied through Django backend for security.
"""

import json

from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.conf import settings
import requests
import logging

from .models import Geofence

logger = logging.getLogger(__name__)


@login_required
def dashboard_view(request):
    """
    Main dashboard showing all vehicles with real-time positions on map.
    Uses same external API proxy pattern as livetracker.
    """
    context = {
        'page_title': 'Global Tracker Dashboard - Testing EKA Nagpur'
    }
    
    return render(request, 'globaltracker/dashboard.html', context)


@login_required
@require_http_methods(["GET"])
def health_check(request):
    """
    Simple health check endpoint to verify backend is running.
    Useful for debugging connectivity issues.
    """
    return JsonResponse({
        'status': 'ok',
        'message': 'Backend is running',
        'debug': settings.DEBUG,
        'twins_configured': bool(settings.TWINS_API_URL and settings.TWINS_API_TOKEN)
    })


# ======================
# API PROXY ENDPOINTS (Same as livetracker)
# ======================

@require_http_methods(["GET"])
def twins_api_proxy(request):
    """
    Proxy endpoint for TWINS API to avoid CORS and CSP issues.
    Fetches latest vehicle points with configurable limit.
    
    URL: /globaltracker/api/twins/latest-points/
    Params: ?limit=3 (optional, default 3)
    
    Returns: { vendor_filter, total_vehicles, vehicles: { reg: [points] } }
    """
    try:
        limit = request.GET.get('limit', 3)
        api_url = None  # Initialize for error handling

        # Validate limit
        try:
            limit = int(limit)
            limit = max(1, min(limit, 5))  # Clamp between 1-200
        except (ValueError, TypeError):
            limit = 5

        # Map frontend project names to the vendor+spv values the TWINS API expects
        PROJECT_TO_TWINS = {
            'UMT':      (getattr(settings, 'TWINS_UMT_VENDOR', 'intangles'),      getattr(settings, 'TWINS_UMT_SPV', 'UMT')),
            'ULTRATECH':(getattr(settings, 'TWINS_VENDOR', 'intangles'),           getattr(settings, 'TWINS_SPV', 'ultratech')),
            'MBMT':     (getattr(settings, 'TWINS_MBMT_VENDOR', 'intangles'),     getattr(settings, 'TWINS_MBMT_SPV', 'mbmt')),
            'nagpur':   (getattr(settings, 'TWINS_NAGPUR_VENDOR', 'eka'),         getattr(settings, 'TWINS_NAGPUR_SPV', 'nagpur')),
            'NAGPUR':   (getattr(settings, 'TWINS_NAGPUR_VENDOR', 'eka'),         getattr(settings, 'TWINS_NAGPUR_SPV', 'nagpur')),
        }
        raw_spv = request.GET.get('spv', 'UMT').strip()
        raw_vendor = request.GET.get('vendor', 'intangles').strip()
        if raw_spv in PROJECT_TO_TWINS:
            vendor, spv = PROJECT_TO_TWINS[raw_spv]
        else:
            # Unknown project — fall back to primary configured project
            vendor = getattr(settings, 'TWINS_VENDOR', 'intangles')
            spv = getattr(settings, 'TWINS_SPV', 'ultratech')

        twins_url = settings.TWINS_API_URL
        twins_token = settings.TWINS_API_TOKEN

        if not twins_url or not twins_token:
            logger.error("❌ TWINS API credentials not configured")
            logger.error(f"   TWINS_API_URL set: {bool(twins_url)}")
            logger.error(f"   TWINS_API_TOKEN set: {bool(twins_token)}")
            return JsonResponse(
                {'error': 'TWINS API not configured'},
                status=500
            )

        # Build URL with dynamic vendor/spv
        api_url = f"{twins_url}latest_points_combined?vendor={vendor}&spv={spv}&limit={limit}"

        logger.info(f"🔄 Proxying TWINS API request: vendor={vendor}, spv={spv}, limit={limit}")
        logger.debug(f"   TWINS API URL: {twins_url}")
        logger.debug(f"   Full request URL: {api_url}")
        
        # Make request to TWINS API with token
        response = requests.get(
            api_url,
            headers={
                'Authorization': f'Bearer {twins_token}',
            },
            timeout=20  # 20 second timeout
        )

        # A 400 from the TWINS API means the vendor/spv combination is not
        # supported by that API instance. Return an empty-but-valid response
        # so the frontend renders a "no vehicles" state instead of an error.
        if response.status_code == 400:
            logger.warning(f"⚠️ TWINS API returned 400 for vendor={vendor} spv={spv} — project may not be available")
            return JsonResponse({'total_vehicles': 0, 'vehicles': {}, 'vendor_filter': vendor}, safe=True)

        response.raise_for_status()
        
        data = response.json()
        logger.info(f"✅ TWINS API response received")
        logger.debug(f"   Response keys: {list(data.keys())}")
        logger.debug(f"   Total vehicles: {data.get('total_vehicles', 'N/A')}")
        logger.debug(f"   Vendor filter: {data.get('vendor_filter', 'N/A')}")
        logger.debug(f"   Has 'vehicles' key: {'vehicles' in data}")
        if 'vehicles' in data:
            logger.debug(f"   Vehicles count: {len(data.get('vehicles', {}))}")
        logger.info(f"   Proxying response back to client")

        # Normalise field names: EKA returns 'lat'/'lon', Intangles returns 'latitude'/'longitude'.
        # Always emit 'latitude'/'longitude' so the frontend can use a single field name.
        if 'vehicles' in data:
            for reg, points in data['vehicles'].items():
                if isinstance(points, list):
                    for p in points:
                        if 'latitude' not in p and 'lat' in p:
                            p['latitude'] = p['lat']
                        if 'longitude' not in p and 'lon' in p:
                            p['longitude'] = p['lon']

        return JsonResponse(data, safe=True)
        
    except requests.Timeout:
        logger.error("⏱️ TWINS API proxy timeout")
        if api_url:
            logger.error(f"   API URL: {api_url}")
        return JsonResponse({'error': 'TWINS API timeout'}, status=504)
    except requests.RequestException as e:
        logger.error(f"❌ TWINS API proxy error: {str(e)}")
        logger.error(f"   Error type: {type(e).__name__}")
        if api_url:
            logger.error(f"   API URL attempted: {api_url}")
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
    
    URL: /globaltracker/api/twins/24hr-route/
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

        # Map frontend project names to the vendor+spv values the TWINS API expects
        PROJECT_TO_TWINS = {
            'UMT':      (getattr(settings, 'TWINS_UMT_VENDOR', 'intangles'),      getattr(settings, 'TWINS_UMT_SPV', 'UMT')),
            'ULTRATECH':(getattr(settings, 'TWINS_VENDOR', 'intangles'),           getattr(settings, 'TWINS_SPV', 'ultratech')),
            'MBMT':     (getattr(settings, 'TWINS_MBMT_VENDOR', 'intangles'),     getattr(settings, 'TWINS_MBMT_SPV', 'mbmt')),
            'nagpur':   (getattr(settings, 'TWINS_NAGPUR_VENDOR', 'eka'),         getattr(settings, 'TWINS_NAGPUR_SPV', 'nagpur')),
            'NAGPUR':   (getattr(settings, 'TWINS_NAGPUR_VENDOR', 'eka'),         getattr(settings, 'TWINS_NAGPUR_SPV', 'nagpur')),
        }
        raw_spv = request.GET.get('spv', 'UMT').strip()
        if raw_spv in PROJECT_TO_TWINS:
            vendor, spv = PROJECT_TO_TWINS[raw_spv]
        else:
            vendor = getattr(settings, 'TWINS_VENDOR', 'intangles')
            spv = getattr(settings, 'TWINS_SPV', 'ultratech')

        twins_url = settings.TWINS_API_URL
        twins_token = settings.TWINS_API_TOKEN

        if not twins_url or not twins_token:
            logger.error("❌ TWINS API credentials not configured")
            return JsonResponse(
                {'error': 'TWINS API not configured'},
                status=500
            )

        # Build URL for 24hr full route data with dynamic vendor and spv
        api_url = f"{twins_url}fetch_combined?vendor={vendor}&spv={spv}&registration_number={registration_number}"

        logger.info(f"🔄 Proxying TWINS 24hr route request: vendor={vendor}, spv={spv}, registration_number={registration_number}")
        
        # Make request to TWINS API with token
        response = requests.get(
            api_url,
            headers={
                'Authorization': f'Bearer {twins_token}',
            },
            timeout=90  # 90 second timeout for large datasets
        )
        
        # Handle 404 errors gracefully - vehicle may not have 24hr data available
        if response.status_code == 404:
            logger.warning(f"⚠️ Vehicle {registration_number} not found in TWINS 24hr data")
            return JsonResponse({
                'error': f'No 24-hour playback data available for vehicle {registration_number}.',
                'points': [],
                'registration_number': registration_number
            }, status=200)

        # A 400 means the vendor/spv is not supported by this API instance
        if response.status_code == 400:
            logger.warning(f"⚠️ TWINS API returned 400 for vendor={vendor} spv={spv} — project may not be available")
            return JsonResponse({'points': [], 'registration_number': registration_number}, safe=True)

        response.raise_for_status()
        
        data = response.json()
        
        # Extract points for the specific vehicle from the response
        vehicles = data.get('vehicles', {})
        vehicle_points = vehicles.get(registration_number, [])
        
        if not vehicle_points:
            logger.warning(f"⚠️ No points returned from TWINS API for {registration_number}")
            return JsonResponse({'points': [], 'registration_number': registration_number}, safe=True)
        
        point_count = len(vehicle_points)
        logger.info(f"✅ TWINS 24hr route response: {point_count} points for {registration_number}")
        
        # Map TWINS API points to frontend-compatible format
        mapped_points = []
        for point in vehicle_points:
            # Normalize gps_time: TWINS may return it as a Unix int (seconds)
            _raw_gps_time = point.get('gps_time')
            if isinstance(_raw_gps_time, int):
                import pytz as _pytz
                _ist = _pytz.timezone('Asia/Kolkata')
                _gps_time_iso = datetime.fromtimestamp(_raw_gps_time, tz=_ist).strftime('%Y-%m-%dT%H:%M:%S')
            else:
                _gps_time_iso = _raw_gps_time  # already ISO string or None
            _last_connected = _gps_time_iso or point.get('event_datetime')
            mapped_point = {
                'registration_number': point.get('registration_number', registration_number),
                'vehicle_no': point.get('registration_number', registration_number),
                'latitude': float(point.get('latitude', 0)) if point.get('latitude') else 0,
                'longitude': float(point.get('longitude', 0)) if point.get('longitude') else 0,
                'gps_time': _gps_time_iso,
                'event_datetime': point.get('event_datetime'),
                'last_connected': _last_connected,
                'heading': float(point.get('head', 0)) if point.get('head') else None,
                'gps_heading': float(point.get('head', 0)) if point.get('head') else None,
                'speed': float(point.get('speed', 0)) if point.get('speed') is not None else 0,
                'gps_speed': float(point.get('speed', 0)) if point.get('speed') is not None else 0,
                'soc': int(point.get('soc', 0)) if point.get('soc') else None,
                'odometer': float(point.get('odometer', 0)) if point.get('odometer') else None,
                'altitude': float(point.get('altitude', 0)) if point.get('altitude') else None,
                'vehicle_status': point.get('vehicle_status'),
                'raw': point
            }
            mapped_points.append(mapped_point)
        
        return JsonResponse({'points': mapped_points, 'registration_number': registration_number}, safe=True)
        
    except requests.Timeout:
        logger.error("⏱️ TWINS 24hr route proxy timeout")
        return JsonResponse({'error': 'TWINS API timeout'}, status=504)
    except requests.RequestException as e:
        logger.error(f"❌ TWINS 24hr route proxy error: {str(e)}")
        return JsonResponse(
            {'error': f'TWINS API error: {str(e)}'},
            status=502
        )
    except Exception as e:
        logger.error(f"❌ TWINS 24hr route proxy error: {str(e)}")
        return JsonResponse(
            {'error': 'Internal server error'},
            status=500
        )


# ======================
# GEOFENCE ENDPOINTS
# ======================

@login_required
@require_http_methods(["GET", "POST"])
def geofences_list_create(request):
    """
    GET  /globaltracker/api/geofences/  — list all geofences
    POST /globaltracker/api/geofences/  — create a new geofence
    """
    if request.method == 'GET':
        qs = Geofence.objects.all()
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

    # POST — create
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
    """
    GET    /globaltracker/api/geofences/<id>/  — retrieve
    PUT    /globaltracker/api/geofences/<id>/  — update name/color/spv
    DELETE /globaltracker/api/geofences/<id>/  — delete
    """
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

    # PUT
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
