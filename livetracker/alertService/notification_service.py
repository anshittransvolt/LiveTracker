"""
Unified Alert Notification Service
Coordinates all alert notifications in the correct order:
1. LiveNotif Toast (real-time UI notifications)
2. Telegram (instant messaging)
3. Webhook (external integrations)

This module provides a single entry point for sending alerts across all channels,
ensuring consistent notification flow and proper error handling.
"""

import logging
from typing import Optional, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)

# =============================================================================
# NOTIFICATION SERVICE CONFIGURATION
# Enable/Disable notification channels here
# =============================================================================
ENABLE_TOAST_SERVICE = True      # LiveNotif real-time UI notifications
ENABLE_TELEGRAM_SERVICE = True   # Telegram instant messaging
ENABLE_WEBHOOK_SERVICE = True    # External webhook integration
# =============================================================================


class NotificationService:
    """Unified service for sending alerts across all notification channels."""

    def __init__(self):
        self.livenotif_enabled = ENABLE_TOAST_SERVICE
        self.telegram_enabled = ENABLE_TELEGRAM_SERVICE
        self.webhook_enabled = ENABLE_WEBHOOK_SERVICE

    def send_alert(
        self,
        event_id: str,
        alert_text: str,
        priority: str = "medium",
        vehicle_id: Optional[str] = None,
        vehicle_no: Optional[str] = None,
        event_trigger_timestamp: Optional[int] = None,
        additional_data: Optional[Dict[str, Any]] = None,
        spv: Optional[str] = None,
    ) -> Dict[str, bool]:
        """
        Send alert through all configured notification channels.

        Args:
            event_id: Event ID (e.g., "EVT-101")
            alert_text: The alert message text
            priority: Alert priority ("high", "medium", "low")
            vehicle_id: Vehicle identifier
            vehicle_no: Vehicle number
            event_trigger_timestamp: Unix timestamp when alert was triggered
            additional_data: Additional metadata for webhook

        Returns:
            Dictionary with success status for each channel:
            {
                "livenotif": bool,
                "telegram": bool,
                "webhook": bool
            }
        """
        results = {
            "livenotif": False,
            "telegram": False,
            "webhook": False,
        }

        # Default timestamp if not provided
        if event_trigger_timestamp is None:
            event_trigger_timestamp = int(datetime.now().timestamp())

        # Extract lat/lon from additional_data if available
        lat = None
        lon = None
        if additional_data:
            lat = additional_data.get("latitude") or additional_data.get("lat")
            lon = additional_data.get("longitude") or additional_data.get("lon")
        
        # 1. Send LiveNotif Toast (highest priority - real-time UI)
        if self.livenotif_enabled:
            results["livenotif"] = self._send_livenotif(
                event_id, alert_text, priority, lat, lon, vehicle_no, spv=spv
            )
        else:
            logger.debug("LiveNotif notifications disabled")

        # 2. Send Telegram notification
        if self.telegram_enabled:
            results["telegram"] = self._send_telegram(alert_text)
        else:
            logger.debug("Telegram notifications disabled")

        # 3. Post to webhook endpoint
        if self.webhook_enabled:
            results["webhook"] = self._post_webhook(
                event_id=event_id,
                vehicle_id=vehicle_id,
                vehicle_no=vehicle_no,
                event_trigger_timestamp=event_trigger_timestamp,
                additional_data=additional_data,
            )
        else:
            logger.debug("Webhook notifications disabled")

        # Return results without logging

        return results

    def _send_livenotif(
        self,
        event_id: str,
        alert_text: str,
        priority: str,
        lat=None,
        lon=None,
        vehicle_no: Optional[str] = None,
        spv: Optional[str] = None,
    ) -> bool:
        """
        Send toast notification via livenotif system.

        Args:
            event_id: Event ID (e.g., "EVT-101")
            alert_text: Alert message text
            priority: Priority level ("high", "medium", "low")
            lat: Latitude coordinate (optional)
            lon: Longitude coordinate (optional)

        Returns:
            True if successful, False otherwise
        """
        try:
            from livenotif import utils as livenotif

            # Enrich toast text with driver info from assignment (if available)
            enriched_text = self._append_driver_info_to_alert_text(alert_text, vehicle_no)

            # Map priority to livenotif severity
            severity_map = {
                "high": "high",
                "medium": "medium",
                "low": "low",
                "normal": "normal",
            }
            severity = severity_map.get(priority, "medium")

            # Send notification using the appropriate priority function with location
            timestamp = datetime.now().isoformat()
            
            if severity == "high":
                event = livenotif.high(event_id, enriched_text, timestamp, lat, lon, spv=spv)
            elif severity == "low":
                event = livenotif.low(event_id, enriched_text, timestamp, lat, lon, spv=spv)
            else:  # medium or normal
                event = livenotif.medium(event_id, enriched_text, timestamp, lat, lon, spv=spv)

            if event:
                return True
            else:
                return False

        except ImportError:
            logger.warning("LiveNotif module not available - skipping toast notification")
            return False
        except Exception as e:
            logger.error(f"❌ Failed to send LiveNotif toast: {e}", exc_info=True)
            return False

    def _get_driver_info_for_vehicle(self, vehicle_no: Optional[str]) -> Optional[Dict[str, str]]:
        """Resolve assigned driver details from horse number."""
        if not vehicle_no:
            return None

        try:
            from roster.models import HorseTrolleyAssignment

            assignment = (
                HorseTrolleyAssignment.objects
                .select_related("driver")
                .filter(horse__horse_number=vehicle_no)
                .first()
            )

            if not assignment or not assignment.driver:
                return None

            return {
                "driver_name": assignment.driver.employee_name or "",
                "driver_code": assignment.driver.employee_code or "",
                "driver_phone": assignment.driver.phone or "",
            }
        except Exception:
            logger.debug("Unable to resolve driver assignment for vehicle: %s", vehicle_no)
            return None

    def _append_driver_info_to_alert_text(self, alert_text: str, vehicle_no: Optional[str]) -> str:
        """Insert driver info into structured alert text so it appears in LiveNotif toast."""
        text = (alert_text or "").strip()
        if not text:
            return text

        if "Driver:" in text:
            return text

        driver_info = self._get_driver_info_for_vehicle(vehicle_no)
        if not driver_info:
            return text

        driver_name = driver_info.get("driver_name", "").strip()
        driver_code = driver_info.get("driver_code", "").strip()
        driver_phone = str(driver_info.get("driver_phone", "")).strip()

        if driver_name and driver_phone:
            driver_text = f"Driver: {driver_name} | Number: {driver_phone}"
        elif driver_name and driver_code:
            driver_text = f"Driver: {driver_name} ({driver_code})"
        elif driver_phone:
            driver_text = f"Driver Number: {driver_phone}"
        elif driver_name:
            driver_text = f"Driver: {driver_name}"
        elif driver_code:
            driver_text = f"Driver: {driver_code}"
        else:
            return text

        # Structured format: "Vehicle | Event | ..."
        # Insert driver after first two parts so location/time stripping doesn't remove driver.
        if " | " in text:
            parts = text.split(" | ")
            if len(parts) >= 2:
                return " | ".join(parts[:2] + [driver_text] + parts[2:])

        # Fallback for unstructured messages
        return f"{text} | {driver_text}"

    def _send_telegram(self, alert_text: str) -> bool:
        """
        Send alert via Telegram.

        Args:
            alert_text: Alert message text

        Returns:
            True if successful, False otherwise
        """
        try:
            from livetracker.alertService.telegram import send_telegram_message

            result = send_telegram_message(alert_text)
            
            if result:
                logger.debug(f"✅ Telegram message sent")
                return True
            else:
                logger.debug(f"⚠️ Telegram message send returned None/False")
                return False

        except ImportError:
            return False
        except Exception as e:
            return False

    def _post_webhook(
        self,
        event_id: str,
        vehicle_id: Optional[str],
        vehicle_no: Optional[str],
        event_trigger_timestamp: int,
        additional_data: Optional[Dict[str, Any]],
    ) -> bool:
        """
        Post alert to webhook endpoint.

        Args:
            event_id: Event ID (e.g., "EVT-101")
            vehicle_id: Vehicle identifier
            vehicle_no: Vehicle number
            event_trigger_timestamp: Unix timestamp
            additional_data: Additional metadata

        Returns:
            True if successful, False otherwise
        """
        try:
            from livetracker.alertService.webhook_service import post_alert_to_webhook

            success = post_alert_to_webhook(
                event_id=event_id,
                vehicle_id=vehicle_id or "",
                vehicle_no=vehicle_no or "",
                event_trigger_timestamp=event_trigger_timestamp,
                additional_data=additional_data,
            )

            if success:
                logger.debug(f"✅ Webhook posted: event_id={event_id}")
                return True
            else:
                logger.debug(f"⚠️ Webhook post returned False: event_id={event_id}")
                return False

        except ImportError:
            logger.debug("Webhook service not available - skipping")
            return False
        except Exception as e:
            logger.error(f"❌ Failed to post webhook: {e}")
            return False


# Global singleton instance
_notification_service = None


def get_notification_service() -> NotificationService:
    """Get or create the global notification service instance."""
    global _notification_service
    if _notification_service is None:
        _notification_service = NotificationService()
    return _notification_service


def send_alert_notification(
    event_id: str,
    alert_text: str,
    priority: str = "medium",
    vehicle_id: Optional[str] = None,
    vehicle_no: Optional[str] = None,
    event_trigger_timestamp: Optional[int] = None,
    additional_data: Optional[Dict[str, Any]] = None,
    spv: Optional[str] = None,
) -> Dict[str, bool]:
    """
    Convenience function to send alert through all notification channels.

    Args:
        event_id: Event ID (e.g., "EVT-101")
        alert_text: The alert message text
        priority: Alert priority ("high", "medium", "low")
        vehicle_id: Vehicle identifier
        vehicle_no: Vehicle number
        event_trigger_timestamp: Unix timestamp when alert was triggered
        additional_data: Additional metadata for webhook
        spv: SPV/project identifier for filtering

    Returns:
        Dictionary with success status for each channel
    """
    service = get_notification_service()
    return service.send_alert(
        event_id=event_id,
        alert_text=alert_text,
        priority=priority,
        vehicle_id=vehicle_id,
        vehicle_no=vehicle_no,
        event_trigger_timestamp=event_trigger_timestamp,
        additional_data=additional_data,
        spv=spv,
    )
