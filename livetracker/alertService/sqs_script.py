import boto3
import json
import logging
from datetime import datetime, timedelta
from django.conf import settings
from django.core.cache import cache

# Initialize logging
logger = logging.getLogger(__name__)

# Initialize SQS client
sqs = boto3.client(
    "sqs",
    region_name=settings.SQS_REGION,
    aws_access_key_id=settings.SQS_ACCESS_KEY,
    aws_secret_access_key=settings.SQS_SECRET_ACCESS_KEY
)

QUEUE_URL = settings.SQS_QUEUE_URL

# Deduplication cache timeout (15 minutes)
DEDUP_CACHE_TIMEOUT = 900


def process_vendor_alert(data):
    """
    Process a vendor alert message and send notifications.
    
    Args:
        data: Parsed JSON data from SQS message
        
    Expected data format:
        {
            "vendor": "Iplt Live Tracker App",
            "event_id": "EVT-101",
            "vehicle_id": "V123",
            "vehicle_no": "MH12AB1234",
            "event_trigger_timestamp": "1733392800",
            "metadata": {...}
        }
    """
    try:
        from livetracker.alertService.notification_service import send_alert_notification
        from livetracker.alertService.event_mapping import EventMapping
        import hashlib
        
        # Extract required fields
        event_id = data.get("event_id")
        vehicle_id = data.get("vehicle_id", "")
        vehicle_no = data.get("vehicle_no", "")
        
        # Validate event_id
        if not event_id:
            logger.error(f"Missing event_id in vendor alert: {data}")
            return False
        
        # Create a unique hash for deduplication based on event_id + vehicle + timestamp (within 1 minute)
        event_trigger_timestamp = data.get("event_trigger_timestamp")
        if event_trigger_timestamp:
            try:
                event_trigger_timestamp = int(event_trigger_timestamp)
                # Round timestamp to nearest minute for deduplication
                timestamp_minute = event_trigger_timestamp // 60
            except (ValueError, TypeError):
                event_trigger_timestamp = int(datetime.now().timestamp())
                timestamp_minute = event_trigger_timestamp // 60
        else:
            event_trigger_timestamp = int(datetime.now().timestamp())
            timestamp_minute = event_trigger_timestamp // 60
        
        # Create deduplication key
        dedup_key = f"alert_processed:{event_id}:{vehicle_no}:{timestamp_minute}"
        
        # Check if we've already processed this alert
        if cache.get(dedup_key):
            return True  # Skip duplicate, return True to delete the message
        
        # Mark as processed (cache for 15 minutes)
        cache.set(dedup_key, True, DEDUP_CACHE_TIMEOUT)
        
        # Get event metadata to construct alert text
        event_metadata = EventMapping.get_event_metadata(event_id)
        event_name = event_metadata.get("event_name", "Unknown Event")
        event_desc = event_metadata.get("event_description", "")
        priority = event_metadata.get("severity", "medium")
        
        # Parse timestamp first to format it
        event_trigger_timestamp = data.get("event_trigger_timestamp")
        if event_trigger_timestamp:
            try:
                event_trigger_timestamp = int(event_trigger_timestamp)
                timestamp_dt = datetime.fromtimestamp(event_trigger_timestamp)
            except (ValueError, TypeError):
                event_trigger_timestamp = int(datetime.now().timestamp())
                timestamp_dt = datetime.now()
        else:
            event_trigger_timestamp = int(datetime.now().timestamp())
            timestamp_dt = datetime.now()
        
        # Format timestamp as readable string
        formatted_time = timestamp_dt.strftime("%d %b %Y, %I:%M %p")
        
        # Extract location from metadata
        additional_data = data.get("metadata", {})
        location = additional_data.get("location", "")
        lat = additional_data.get("latitude") or additional_data.get("lat")
        lon = additional_data.get("longitude") or additional_data.get("lon")
        
        # Build location display
        location_display = (
            f"{location} ({lat}, {lon})" if lat and lon and location
            else f"{lat}, {lon}" if lat and lon
            else location if location
            else ""
        )
        
        # Construct structured alert text
        alert_parts = [vehicle_no, event_name]
        if location_display:
            alert_parts.append(f"Location: {location_display}")
        alert_parts.append(f"Time: {formatted_time}")
        alert_text = " | ".join(alert_parts)
        
        # Add vendor info to metadata
        additional_data["vendor"] = data.get("vendor", "")
        additional_data["source"] = "sqs_vendor_alert"
        
        # Send notification through unified service
        
        results = send_alert_notification(
            event_id=event_id,
            alert_text=alert_text,
            priority=priority,
            vehicle_id=vehicle_id,
            vehicle_no=vehicle_no,
            event_trigger_timestamp=event_trigger_timestamp,
            additional_data=additional_data,
        )
        
        # Alerts processed silently
        
        return True
        
    except ImportError as e:
        logger.error(f"Failed to import notification service: {e}")
        return False
    except Exception as e:
        logger.error(f"Error processing vendor alert: {e}", exc_info=True)
        return False


def poll_messages():
    """
    Poll SQS queue for vendor alert messages.
    Filters for vendor='Iplt Live Tracker App' and processes alerts.
    """
    logger.info("Starting SQS poller... Filtering for vendor='Iplt Live Tracker App'")
    print("Listening for SQS messages... Filtering for vendor='Iplt Live Tracker App'\n")

    message_count = 0
    processed_count = 0

    while True:
        try:
            response = sqs.receive_message(
                QueueUrl=QUEUE_URL,
                MaxNumberOfMessages=10,
                WaitTimeSeconds=20,
                VisibilityTimeout=120  # Increased from 30 to 120 seconds to prevent duplicate processing
            )

            messages = response.get("Messages", [])
            if not messages:
                continue

            for msg in messages:
                message_count += 1
                receipt_handle = msg["ReceiptHandle"]
                
                try:
                    body = msg["Body"]

                    # Try JSON parsing
                    try:
                        data = json.loads(body)
                    except json.JSONDecodeError:
                        logger.warning(f"Skipped invalid JSON message: {body}")
                        print(f"Skipped (invalid JSON): {body}")
                        # Delete invalid message to prevent reprocessing
                        sqs.delete_message(QueueUrl=QUEUE_URL, ReceiptHandle=receipt_handle)
                        continue

                    # FILTER: Only process vendor = Iplt Live Tracker App
                    vendor = data.get("vendor")
                    if vendor != "Iplt Live Tracker App":
                        # Delete non-matching vendor messages
                        sqs.delete_message(QueueUrl=QUEUE_URL, ReceiptHandle=receipt_handle)
                        continue

                    # Print the matched message
                    print("\n====== MATCHED MESSAGE ======")
                    print(f"Message #{message_count}")
                    print(f"Received: {body}")
                    print(f"Parsed JSON: {data}")
                    print("=============================")

                    # Process the vendor alert
                    success = process_vendor_alert(data)
                    
                    if success:
                        processed_count += 1
                        print(f"✅ Alert processed successfully (Total: {processed_count})")
                    else:
                        print(f"⚠️ Alert processing failed")
                    
                    # Delete message after reading and processing attempt
                    sqs.delete_message(QueueUrl=QUEUE_URL, ReceiptHandle=receipt_handle)
                    logger.info(f"Deleted SQS message after processing")
                    
                    print()

                except Exception as e:
                    logger.error(f"Error processing SQS message: {e}", exc_info=True)
                    print(f"Error: {str(e)}")
                    # Delete message even if processing error occurred
                    try:
                        sqs.delete_message(QueueUrl=QUEUE_URL, ReceiptHandle=receipt_handle)
                        logger.info(f"Deleted problematic SQS message")
                    except Exception as delete_error:
                        logger.error(f"Failed to delete message: {delete_error}")
                    
        except KeyboardInterrupt:
            logger.info(f"SQS poller stopped. Processed {processed_count}/{message_count} messages")
            print(f"\n\nStopping... Processed {processed_count}/{message_count} messages")
            break
        except Exception as e:
            logger.error(f"Error in SQS polling loop: {e}", exc_info=True)
            print(f"Polling error: {str(e)}")
            continue


if __name__ == "__main__":
    poll_messages()