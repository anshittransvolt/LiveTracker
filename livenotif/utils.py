"""
LiveNotif Alert System - Simple API for pushing real-time alerts

Usage:
    from livenotif import utils as livenotif
    
    livenotif.high('ALERT-001', 'Engine Overheat', '2025-11-29T10:30:00')
    livenotif.medium('ALERT-002', 'Battery Low', '2025-11-29T10:35:00')
    livenotif.low('ALERT-003', 'Maintenance Due', '2025-11-29T10:40:00')

Legacy functions (backward compatibility):
    - push_toast(): Create and trigger event/toast notification
    - create_event_type(): Create reusable event type definition
    - trigger_event(): Trigger event from existing event type
"""

from .models import EventType, Event
from datetime import datetime


def high(alert_code, content, timestamp=None, lat=None, lon=None, spv=None):
    """Push HIGH priority alert"""
    return _push_alert(alert_code, content, 'high', timestamp, lat, lon, spv=spv)


def medium(alert_code, content, timestamp=None, lat=None, lon=None, spv=None):
    """Push MEDIUM priority alert"""
    return _push_alert(alert_code, content, 'medium', timestamp, lat, lon, spv=spv)


def low(alert_code, content, timestamp=None, lat=None, lon=None, spv=None):
    """Push LOW priority alert"""
    return _push_alert(alert_code, content, 'low', timestamp, lat, lon, spv=spv)


def _push_alert(alert_code, content, severity, timestamp=None, lat=None, lon=None, spv=None):
    """Internal function to push alerts with specified severity and location"""
    # Parse timestamp
    if timestamp is None:
        alert_time = datetime.now()
    elif isinstance(timestamp, str):
        try:
            alert_time = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        except ValueError:
            alert_time = datetime.now()
    else:
        alert_time = timestamp
    
    # Extract title and description from content
    # New format: VehicleNo | EventName | Location: ... | Time: ...
    # Old format: VehicleNo — EventName
    
    # Title must be short (max 100 chars for database field)
    # Description should NOT repeat vehicle/event (they're already in title)
    
    if ' | ' in content:
        # New structured format
        parts = content.split(' | ')
        if len(parts) >= 2:
            # Title: "Vehicle — Event" (first 2 parts only)
            short_title = f"{parts[0]} — {parts[1]}"
            # Truncate if still too long (safety check)
            title = short_title[:95] + "..." if len(short_title) > 95 else short_title
            
            # Description: Only Location and Time (parts 3+)
            # Don't repeat vehicle and event info
            if len(parts) > 2:
                description = " | ".join(parts[2:])  # Only Location and Time
            else:
                description = content  # Fallback to full content
        else:
            title = parts[0][:95] + "..." if len(parts[0]) > 95 else parts[0]
            description = content
    elif '—' in content:
        # Legacy format
        title_parts = content.split('—', 1)
        short_title = title_parts[0].strip()
        title = short_title[:95] + "..." if len(short_title) > 95 else short_title
        description = content
    else:
        title = alert_code[:95] if len(alert_code) > 95 else alert_code
        description = content
    
    # Note: LiveNotif manages its own database through Event/EventType models
    # This function just pushes the alert data - LiveNotif handles persistence
    
    # Get or create event type
    event_type, created = EventType.objects.get_or_create(
        event_id=alert_code,
        defaults={
            'event_name': title,
            'event_description': description,
            'severity': severity,
        }
    )
    
    # Update event type if it already exists
    if not created:
        event_type.event_name = title
        event_type.event_description = description
        event_type.severity = severity
        event_type.save()
    
    # Create active event instance with location data
    event = Event.objects.create(
        event_type=event_type,
        is_active=True,
        source='alert_service',
        latitude=lat,
        longitude=lon,
        spv=spv or '',
    )
    
    return event


def push_toast(title, message, severity="normal", icon="ℹ️", event_id=None):
    """Legacy: Create and trigger an event/toast notification"""
    # Auto-generate event_id if not provided
    if not event_id:
        # Get the highest event number and increment
        last_event = (
            EventType.objects.filter(event_id__startswith="EVT-")
            .order_by("-event_id")
            .first()
        )
        if last_event:
            try:
                last_num = int(last_event.event_id.split("-")[1])
                event_id = f"EVT-{last_num + 1:03d}"
            except (ValueError, IndexError):
                event_id = "EVT-001"
        else:
            event_id = "EVT-001"

    # Get or create the event type
    event_type, created = EventType.objects.get_or_create(
        event_id=event_id,
        defaults={
            "event_name": title,
            "event_description": message,
            "severity": severity,
            "icon": icon,
        },
    )

    # If event type already exists, update it
    if not created:
        event_type.event_name = title
        event_type.event_description = message
        event_type.severity = severity
        event_type.icon = icon
        event_type.save()

    # Create a new event instance
    event = Event.objects.create(event_type=event_type, is_active=True)

    return event


def create_event_type(
    event_id, event_name, event_description, severity="normal", icon="ℹ️"
):
    """Legacy: Create a reusable event type definition"""
    event_type, created = EventType.objects.get_or_create(
        event_id=event_id,
        defaults={
            "event_name": event_name,
            "event_description": event_description,
            "severity": severity,
            "icon": icon,
        },
    )
    return event_type


def trigger_event(event_id):
    """Legacy: Trigger an event instance from an existing event type"""
    try:
        event_type = EventType.objects.get(event_id=event_id)
        event = Event.objects.create(event_type=event_type, is_active=True)
        return event
    except EventType.DoesNotExist:
        return None
