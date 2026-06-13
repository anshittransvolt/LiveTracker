"""
Webhook Service Module
Handles posting alerts to external webhook endpoints.
"""

import logging
import requests
from typing import Dict, Optional, Any
from datetime import datetime
from django.conf import settings

from livetracker.alertService.event_mapping import EventMapping

logger = logging.getLogger(__name__)


class WebhookService:
    """Service for posting alerts to webhook endpoints."""

    def __init__(self):
        self.url = getattr(settings, "WEBHOOK_URL")
        self.api_key = getattr(settings, "WEBHOOK_API_KEY")
        self.enabled = getattr(settings, "WEBHOOK_ENABLED")
        self.timeout = getattr(settings, "WEBHOOK_TIMEOUT")
        self.retry_count = getattr(settings, "WEBHOOK_RETRY_COUNT")
        self.vendor_name = getattr(settings, "WEBHOOK_VENDOR_NAME")

    def _build_webhook_payload(
        self,
        event_id: str,
        event_trigger_timestamp: int,
        event_timestamp: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Build webhook payload according to the specified format.

        Args:
            event_id: The event ID (e.g., "EVT-101")
            event_trigger_timestamp: Unix timestamp when alert was triggered
            event_timestamp: Unix timestamp of the actual event (optional)
            metadata: Additional metadata to include in payload

        Returns:
            Dictionary payload ready for webhook POST
        """
        # Get event metadata from mapping
        event_data = EventMapping.get_event_metadata(event_id)

        # Use event_trigger_timestamp as event_timestamp if not provided
        if event_timestamp is None:
            event_timestamp = event_trigger_timestamp

        payload = {
            "vendor": self.vendor_name,
            "event_id": event_id,
            "event_name": event_data["event_name"],
            "event_desc": event_data["event_description"],
            "event_trigger_timestamp": str(event_trigger_timestamp),
            "event_timestamp": str(event_timestamp),
        }

        # Add optional metadata if provided
        if metadata:
            payload["metadata"] = metadata

        return payload

    def post_alert(
        self,
        event_id: str,
        vehicle_id: Optional[str] = None,
        vehicle_no: Optional[str] = None,
        event_trigger_timestamp: Optional[int] = None,
        event_timestamp: Optional[int] = None,
        additional_data: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Post an alert to the webhook endpoint.

        Args:
            event_id: Event ID (e.g., "EVT-101")
            vehicle_id: Vehicle identifier
            vehicle_no: Vehicle number
            event_trigger_timestamp: When alert was triggered (Unix timestamp)
            event_timestamp: When event occurred (Unix timestamp)
            additional_data: Additional metadata to include

        Returns:
            True if successful, False otherwise
        """
        if not self.enabled:
            logger.debug("Webhook posting disabled via settings")
            return False

        if not self.url:
            logger.warning("Webhook URL not configured in settings")
            return False

        if not self.api_key:
            logger.warning("Webhook API key not configured in settings")
            return False

        # Generate timestamps if not provided
        if event_trigger_timestamp is None:
            event_trigger_timestamp = int(datetime.now().timestamp())

        # Build metadata
        metadata = {}
        if vehicle_id:
            metadata["vehicle_id"] = vehicle_id
        if vehicle_no:
            metadata["vehicle_no"] = vehicle_no
        if additional_data:
            metadata.update(additional_data)

        # Extract alert_type from additional_data if available
        alert_type = additional_data.get("alert_type") if additional_data else None

        # Build payload
        payload = self._build_webhook_payload(
            event_id=event_id,
            event_trigger_timestamp=event_trigger_timestamp,
            event_timestamp=event_timestamp,
            metadata=metadata if metadata else None,
        )

        # Prepare headers
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
        }

        # Attempt to post with retries
        for attempt in range(1, self.retry_count + 1):
            try:
                response = requests.post(
                    self.url,
                    json=payload,
                    headers=headers,
                    timeout=self.timeout,
                )

                # Check response status
                if response.status_code in [200, 201, 202]:
                    return True
                else:
                    logger.warning(
                        "Webhook returned non-success status: status=%d response=%s",
                        response.status_code,
                        response.text[:200],
                    )

                    # Don't retry on client errors (4xx)
                    if 400 <= response.status_code < 500:
                        logger.error("Client error, not retrying: %s", response.text[:200])
                        return False

            except requests.exceptions.Timeout:
                logger.warning(
                    "Webhook request timeout (attempt %d/%d)",
                    attempt,
                    self.retry_count,
                )
            except requests.exceptions.ConnectionError as e:
                logger.warning(
                    "Webhook connection error (attempt %d/%d): %s",
                    attempt,
                    self.retry_count,
                    str(e),
                )
            except requests.exceptions.RequestException as e:
                logger.error(
                    "Webhook request failed (attempt %d/%d): %s",
                    attempt,
                    self.retry_count,
                    str(e),
                )
            except Exception as e:
                logger.exception(
                    "Unexpected error posting webhook (attempt %d/%d): %s",
                    attempt,
                    self.retry_count,
                    str(e),
                )

            # Don't sleep on last attempt
            if attempt < self.retry_count:
                import time
                time.sleep(1)  # Wait 1 second between retries

        logger.error(
            "Webhook posting failed after %d attempts: event_id=%s vehicle=%s",
            self.retry_count,
            payload.get("event_id"),
            vehicle_no or vehicle_id or "unknown",
        )
        return False

    def test_connection(self) -> bool:
        """
        Test webhook connection with a test event.

        Returns:
            True if connection is successful, False otherwise
        """
        if not self.enabled or not self.url or not self.api_key:
            logger.warning("Webhook not properly configured for testing")
            return False

        from livetracker.alertService.event_mapping import EventIDs
        
        test_payload = self._build_webhook_payload(
            event_id=EventIDs.GATE_IN_MANAWAR,  # Use a valid event ID
            event_trigger_timestamp=int(datetime.now().timestamp()),
            metadata={"test": True, "message": "Connection test"},
        )

        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
        }

        try:
            logger.info("Testing webhook connection to %s", self.url)
            response = requests.post(
                self.url,
                json=test_payload,
                headers=headers,
                timeout=self.timeout,
            )

            if response.status_code in [200, 201, 202]:
                logger.info("Webhook connection test successful: status=%d", response.status_code)
                return True
            else:
                logger.warning(
                    "Webhook test returned non-success status: status=%d",
                    response.status_code,
                )
                return False

        except Exception as e:
            logger.error("Webhook connection test failed: %s", str(e))
            return False


# Singleton instance
_webhook_service = None


def get_webhook_service() -> WebhookService:
    """Get or create the singleton webhook service instance."""
    global _webhook_service
    if _webhook_service is None:
        _webhook_service = WebhookService()
    return _webhook_service


def post_alert_to_webhook(
    event_id: str,
    vehicle_id: Optional[str] = None,
    vehicle_no: Optional[str] = None,
    event_trigger_timestamp: Optional[int] = None,
    event_timestamp: Optional[int] = None,
    additional_data: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Convenience function to post an alert to webhook.

    Args:
        event_id: Event ID (e.g., "EVT-101")
        vehicle_id: Vehicle identifier
        vehicle_no: Vehicle number
        event_trigger_timestamp: When alert was triggered (Unix timestamp)
        event_timestamp: When event occurred (Unix timestamp)
        additional_data: Additional metadata

    Returns:
        True if successful, False otherwise
    """
    service = get_webhook_service()
    return service.post_alert(
        event_id=event_id,
        vehicle_id=vehicle_id,
        vehicle_no=vehicle_no,
        event_trigger_timestamp=event_trigger_timestamp,
        event_timestamp=event_timestamp,
        additional_data=additional_data,
    )
