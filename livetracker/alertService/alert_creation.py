"""Alert notification sender: sends alerts through all notification channels.

This module centralises alert notifications (LiveNotif, Telegram, Webhook)
without saving to local database. All alerts go directly to notification services.
"""

import logging
from typing import Optional

import json
import os

from livetracker.alertService.geocoding_utils import reverse_geocode

logger = logging.getLogger(__name__)

TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "alert_templates.json")

# Cache templates after first load
_alert_templates_cache = None


def load_alert_templates():
    global _alert_templates_cache
    if _alert_templates_cache is None:
        with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
            _alert_templates_cache = json.load(f)
    return _alert_templates_cache


def format_alert_message(alert_type, context):
    templates = load_alert_templates()
    template_info = templates.get(alert_type)
    if not template_info:
        return None, None
    template = template_info["template"]
    priority = template_info.get("priority", "medium")
    try:
        text = template.format(**context)
        return text, priority
    except Exception:
        # If formatting fails (missing keys etc.) return None so caller
        # can fall back to the original text instead of returning a
        # partially-formatted template string.
        logger.debug(
            "Alert template formatting failed for %s with context %s",
            alert_type,
            context,
        )
        return None, priority


def send_unified_notification(
    event_id: str,
    alert_text: str,
    priority: str,
    vehicle_id: str,
    vehicle_no: str,
    additional_data: dict = None,
    spv: str = None,
):
    """
    Send alert through unified notification service (livenotif + telegram + webhook).
    
    Args:
        event_id: Event ID (e.g., "EVT-101")
        alert_text: Alert message text
        priority: Alert priority ("high", "medium", "low")
        vehicle_id: Vehicle identifier
        vehicle_no: Vehicle number
        additional_data: Additional metadata to include
    """
    try:
        from livetracker.alertService.notification_service import send_alert_notification
        from datetime import datetime

        event_trigger_timestamp = int(datetime.now().timestamp())

        results = send_alert_notification(
            event_id=event_id,
            alert_text=alert_text,
            priority=priority,
            vehicle_id=vehicle_id,
            vehicle_no=vehicle_no,
            event_trigger_timestamp=event_trigger_timestamp,
            additional_data=additional_data,
            spv=spv,
        )
        
        logger.debug(
            f"Unified notification sent for {event_id}: "
            f"livenotif={results['livenotif']}, "
            f"telegram={results['telegram']}, "
            f"webhook={results['webhook']}"
        )
        
    except ImportError:
        logger.warning("notification_service not available - skipping notifications")
    except Exception:
        logger.exception("Error sending unified notification")


def create_alert_row(
    vehicle_id: Optional[str],
    vehicle_no: str,
    driver_name: Optional[str],
    gps_location: str,
    geofence_name: Optional[str],
    lat: Optional[float],
    lon: Optional[float],
    soc: Optional[int],
    event_id: str,
    text: str,
    context: dict = None,
    spv: str = None,
) -> dict:
    """Send alert notification through all channels (LiveNotif, Telegram, Webhook).
    Does NOT save to local database - only sends notifications.
    Uses alert_templates.json for formatting and priority.
    
    Args:
        vehicle_id: Vehicle identifier
        vehicle_no: Vehicle number
        driver_name: Driver name
        gps_location: GPS location string
        geofence_name: Name of geofence
        lat: Latitude
        lon: Longitude
        soc: State of charge
        event_id: Event ID (e.g., "EVT-101") - primary identifier
        text: Alert text message
        context: Additional context for template formatting
        
    Returns:
        Alert data dictionary (not saved to DB, just for reference)
    """
    from livetracker.alertService.event_mapping import EventMapping
    
    # Derive alert_type from event_id for backward compatibility with DB and templates
    alert_type = EventMapping.get_alert_type_from_event_id(event_id)
    
    address = None
    if lat is not None and lon is not None:
        address = reverse_geocode(lat, lon)

    # Build a minimal context from available params so templates that
    # reference common keys (vehicle_no, geofence, lat, lon) still work
    # even when callers don't supply an explicit `context` dict.
    priority = "medium"
    built_context = {
        "vehicle_no": vehicle_no or vehicle_id or "",
        "geofence": geofence_name or "",
        "lat": lat,
        "lon": lon,
    }
    if context:
        built_context.update(context)

    formatted_text, tpl_priority = format_alert_message(alert_type, built_context)
    if tpl_priority:
        priority = tpl_priority
    if formatted_text:
        text = formatted_text

    # Format location with address (simple text only, no embedded links)
    location_display = ""
    
    if address:
        # Format: "Address (lat, lon)"
        coordinates_str = f"({lat}, {lon})"
        location_display = f"{address} {coordinates_str}"
        if f"{lat},{lon}" in text:
            text = text.replace(f"{lat},{lon}", location_display)
        if gps_location and gps_location in text:
            text = text.replace(gps_location, location_display)
    elif lat is not None and lon is not None:
        # Only coordinates available
        location_display = f"{lat}, {lon}"
    elif gps_location:
        location_display = gps_location
    
    # Add readable timestamp to message (not raw ISO format)
    from datetime import datetime
    current_time = datetime.now().strftime("%d %b %Y, %I:%M %p")
    
    # NEW FORMAT:
    # Title will be: "VehicleNo — EventName" (extracted by utils.py)
    # Body will show: "Location: ... | Time: ..."
    # This avoids repeating vehicle and event in the message body
    
    # Clean up text: remove [EVENT], [ALERT], or any other prefixes
    text = text.replace("[EVENT]", "").replace("[ALERT]", "").strip()
    
    # Convert any ISO format timestamps in the text to readable format
    # Pattern: (entered 2025-12-10T14:30:00) -> (entered 10 Dec 2025, 02:30 PM)
    import re
    from dateutil import parser as dateparser
    
    def convert_timestamp(match):
        try:
            iso_time = match.group(1)
            dt = dateparser.isoparse(iso_time)
            return f"(entered {dt.strftime('%d %b %Y, %I:%M %p')})"
        except:
            return match.group(0)  # Return original if parsing fails
    
    # Replace ISO timestamps in format "(entered YYYY-MM-DD...)"
    text = re.sub(r'\(entered ([0-9T:\-+\.]+)\)', convert_timestamp, text)
    
    # Also handle "Last connected at YYYY-MM-DD..." format
    def convert_last_connected(match):
        try:
            iso_time = match.group(1)
            dt = dateparser.isoparse(iso_time)
            return f"Last connected at {dt.strftime('%d %b %Y, %I:%M %p')}"
        except:
            return match.group(0)
    
    text = re.sub(r'Last connected at ([0-9T:\-+\.]+)', convert_last_connected, text)
    
    # Extract event name from text (everything after vehicle_no and —)
    if " — " in text:
        parts = text.split(" — ", 1)
        event_info = parts[1]
    else:
        # If no dash, try to extract after vehicle number
        event_info = text.replace(vehicle_no, "").strip()
        # Remove any leading dashes or spaces
        event_info = event_info.lstrip("—").strip()
    
    # Ensure event_info is not too long for title field (will be truncated in utils.py)
    if len(event_info) > 80:
        event_info_short = event_info[:77] + "..."
    else:
        event_info_short = event_info
    
    # Build structured message: "VehicleNo | EventName | Location: ... | Time: ..."
    # Frontend will split this and display:
    #   - Title: VehicleNo — EventName
    #   - Body: Location: ... | Time: ...
    message_parts = [vehicle_no, event_info_short]
    
    if location_display:
        message_parts.append(f"Location: {location_display}")
    
    message_parts.append(f"Time: {current_time}")
    
    # Join with separator
    text = " | ".join(message_parts)

    # Prepare additional metadata for webhook
    webhook_metadata = {
        "geofence": geofence_name or "",
        "soc": soc,
        "priority": priority,
        "driver_name": driver_name or "",
        "alert_type": alert_type,
    }
    if lat is not None and lon is not None:
        webhook_metadata["latitude"] = lat
        webhook_metadata["longitude"] = lon
    if address:
        webhook_metadata["address"] = address
        webhook_metadata["gps_location"] = f"{address} ({lat}, {lon})"
    elif gps_location:
        webhook_metadata["gps_location"] = gps_location

    # Send unified notification: livenotif toast -> telegram -> webhook
    # NO DATABASE SAVE - Just send notifications
    try:
        send_unified_notification(
            event_id=event_id,
            alert_text=text,
            priority=priority,
            vehicle_id=vehicle_id or "",
            vehicle_no=vehicle_no or "",
            additional_data=webhook_metadata,
            spv=spv,
        )
    except Exception:
        pass  # Silent failure

    # Return a dict instead of VehicleAlert model instance
    # This allows the rest of the code to work without DB dependency
    return {
        "vehicle_id": vehicle_id or "",
        "vehicle_no": vehicle_no or "",
        "driver_name": driver_name or "",
        "gps_location": address or gps_location or "",
        "geofence_name": geofence_name,
        "lat": lat,
        "lon": lon,
        "soc": soc,
        "alert_type": alert_type,
        "text": text,
        "priority": priority,
        "event_id": event_id,
    }
