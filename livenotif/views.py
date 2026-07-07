from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
import json
import re
from .models import Event
from roster.models import HorseTrolleyAssignment
from livetracker.models import LiveTrackerAlertAction


@login_required
@require_http_methods(["GET"])
def get_active_toasts(request):
    """Get all active events for toast display"""
    spv = request.GET.get('spv', '').strip()
    qs = Event.objects.filter(is_active=True).select_related("event_type")
    if spv:
        qs = qs.filter(spv=spv)
    events = list(qs.order_by("-created_at"))

    # Resolve vehicle numbers from event content
    vehicle_numbers = set()
    for event in events:
        vehicle_no = extract_vehicle_number(
            f"{event.event_type.event_name} {event.event_type.event_description}"
        )
        if vehicle_no:
            vehicle_numbers.add(vehicle_no)

    # Map vehicle -> assigned driver details
    driver_by_vehicle = {}
    if vehicle_numbers:
        assignments = (
            HorseTrolleyAssignment.objects
            .select_related("horse", "driver")
            .filter(horse__horse_number__in=vehicle_numbers)
        )
        for assignment in assignments:
            horse_no = assignment.horse.horse_number if assignment.horse else None
            if not horse_no:
                continue
            driver_by_vehicle[horse_no] = {
                "driver_name": assignment.driver.employee_name if assignment.driver else None,
                "driver_phone": assignment.driver.phone if assignment.driver else None,
            }

    toasts = []
    for event in events:
        vehicle_no = extract_vehicle_number(
            f"{event.event_type.event_name} {event.event_type.event_description}"
        )
        driver_data = driver_by_vehicle.get(vehicle_no, {})

        toasts.append(
            {
                "id": event.id,
                "event_id": event.event_type.event_id,
                "title": event.event_type.event_name,
                "message": event.event_type.event_description,
                "severity": event.event_type.severity,
                "created_at": event.created_at.isoformat(),
                "vehicle_no": vehicle_no,
                "driver_name": driver_data.get("driver_name"),
                "driver_phone": driver_data.get("driver_phone"),
                "latitude": float(event.latitude) if event.latitude else None,
                "longitude": float(event.longitude) if event.longitude else None,
            }
        )

    data = {
        "toasts": toasts
    }

    return JsonResponse(data)


@login_required
@require_http_methods(["GET"])
def get_latest_alerts(request):
    """Get latest active alerts for notification sidebar"""
    # Get optional limit parameter (default to 50)
    limit = int(request.GET.get('limit', 50))
    
    # Get optional severity filter
    severity = request.GET.get('severity', None)
    
    # Base query for active events
    query = Event.objects.filter(is_active=True).select_related("event_type")
    
    # Apply severity filter if provided
    if severity and severity in ['high', 'medium', 'low']:
        query = query.filter(event_type__severity=severity)
    
    # Order by created_at descending and limit
    events = query.order_by("-created_at")[:limit]

    # Format alerts for notification sidebar
    alerts = [
        {
            "id": event.id,
            "event_id": event.event_type.event_id,
            "type": event.event_type.severity,  # 'high', 'medium', 'low' -> maps to 'alert', 'warning', 'info'
            "title": event.event_type.event_name,
            "message": event.event_type.event_description,
            "severity": event.event_type.severity,
            "timestamp": event.created_at.isoformat(),
            "vehicle": extract_vehicle_number(event.event_type.event_description),
            "latitude": float(event.latitude) if event.latitude else None,
            "longitude": float(event.longitude) if event.longitude else None,
        }
        for event in events
    ]

    return JsonResponse({
        "success": True,
        "count": len(alerts),
        "alerts": alerts
    })


def extract_vehicle_number(description):
    """Extract vehicle number from event description (e.g., 'MH18BZ2648')"""
    match = re.search(r'\b[A-Z]{2}\d{2}[A-Z]{2}\d{4}\b', description)
    return match.group(0) if match else None


@login_required
@require_http_methods(["POST"])
def log_toast_action(request):
    """Log user action on alert and save to LiveTrackerAlertAction model"""
    try:
        data = json.loads(request.body)
        event_db_id = data.get("toast_id")  # Database ID of the Event
        action = data.get("action")  # 'acknowledged' or 'action_taken'
        notes = data.get("notes", "")

        # Get the event to retrieve event_id and alert details
        event = Event.objects.select_related('event_type').get(id=event_db_id)
        event_id = event.event_type.event_id  # e.g., 'EVT-001', 'ALERT-201'
        
        # Extract vehicle_no from event name or description if available
        vehicle_no = ""
        # Try to extract vehicle number from event name (e.g., "T20 - Alert")
        event_name = event.event_type.event_name
        vehicle_match = re.search(r'(T\d+|TR\d+)', event_name)
        if vehicle_match:
            vehicle_no = vehicle_match.group(1)

        # Determine action_type based on action
        if action == 'ignored' or action == 'acknowledged':
            action_type = 'ack'
        elif action == 'action' or action == 'action_taken':
            action_type = 'action'
        else:
            action_type = 'ack'

        # Create LiveTrackerAlertAction entry
        LiveTrackerAlertAction.objects.create(
            alert_id=str(event_db_id),  # Use event DB ID as alert_id
            alert_type=event_id,  # Event type ID (e.g., 'EVT-001')
            vehicle_no=vehicle_no,
            user=request.user,
            action_type=action_type,
            action_note=notes if notes else ""
        )

        # Mark event as inactive after user interaction
        event.is_active = False
        event.save()

        return JsonResponse({
            "success": True,
            "message": f"Alert {action_type} successfully"
        })
    except Event.DoesNotExist:
        return JsonResponse({"success": False, "error": "Event not found"}, status=404)
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=400)
