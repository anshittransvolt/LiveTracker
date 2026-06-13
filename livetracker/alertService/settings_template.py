"""
Alert Notification System - Settings Template

IMPORTANT: Your settings.py already has all required credentials configured!
You only need to enable/disable services in notification_service.py

Edit notification_service.py to control which channels are active:
    ENABLE_TOAST_SERVICE = True/False
    ENABLE_TELEGRAM_SERVICE = True/False  
    ENABLE_WEBHOOK_SERVICE = True/False

Below is a reference of the settings that should already be in your settings.py:
"""

# =============================================================================
# ALERT NOTIFICATION SYSTEM CONFIGURATION (Already in settings.py)
# =============================================================================

# -----------------------------------------------------------------------------
# Telegram Notifications (Already configured in your settings.py)
# -----------------------------------------------------------------------------
# Get bot token from @BotFather on Telegram
TELEGRAM_BOT_TOKEN = "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz"

# Get chat ID by sending a message to your bot and visiting:
# https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates
TELEGRAM_CHAT_ID = "-1001234567890"


# -----------------------------------------------------------------------------
# Webhook Integration (Already configured in your settings.py)
# -----------------------------------------------------------------------------
# Your webhook endpoint URL
WEBHOOK_URL = "https://your-webhook-endpoint.com/api/alerts"

# API key for webhook authentication
WEBHOOK_API_KEY = "your-webhook-api-key"

# Vendor name to include in webhook payload
WEBHOOK_VENDOR_NAME = "Iplt Live Tracker App"

# Request timeout in seconds
WEBHOOK_TIMEOUT = 10

# Number of retry attempts on failure
WEBHOOK_RETRY_COUNT = 3


# -----------------------------------------------------------------------------
# AWS SQS Configuration (Vendor Alert Messages)
# -----------------------------------------------------------------------------
# AWS region where your SQS queue is located
SQS_REGION = "ap-south-1"  # e.g., us-east-1, ap-south-1, eu-west-1

# AWS credentials with SQS access
SQS_ACCESS_KEY = "AKIAIOSFODNN7EXAMPLE"
SQS_SECRET_ACCESS_KEY = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"

# SQS queue URL - get from AWS SQS console
SQS_QUEUE_URL = "https://sqs.ap-south-1.amazonaws.com/123456789012/your-queue-name"


# =============================================================================
# NOTIFICATION CHANNEL CONTROL
# =============================================================================

# To enable/disable notification channels, edit notification_service.py:
#
# ENABLE_TOAST_SERVICE = True      # LiveNotif real-time UI notifications
# ENABLE_TELEGRAM_SERVICE = True   # Telegram instant messaging
# ENABLE_WEBHOOK_SERVICE = True    # External webhook integration
#
# For development/testing, you can disable specific channels there to avoid
# spamming Telegram or sending test webhooks to production systems.


# =============================================================================
# LOGGING CONFIGURATION (Optional)
# =============================================================================

# Add to your LOGGING configuration for detailed notification logs:
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
        'file': {
            'class': 'logging.FileHandler',
            'filename': 'alert_notifications.log',
        },
    },
    'loggers': {
        'livetracker.alertService.notification_service': {
            'handlers': ['console', 'file'],
            'level': 'INFO',  # Use 'DEBUG' for detailed logging
            'propagate': False,
        },
        'livetracker.alertService.telegram': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': False,
        },
        'livetracker.alertService.webhook_service': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': False,
        },
        'livetracker.alertService.sqs_script': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}


# =============================================================================
# VERIFICATION COMMANDS
# =============================================================================

"""
After configuring settings, verify the integration:

1. Test LiveNotif:
   python manage.py shell
   >>> from livenotif import utils as livenotif
   >>> livenotif.high('TEST-001', '[TEST] LiveNotif working', None)

2. Test Telegram:
   python manage.py shell
   >>> from livetracker.alertService.telegram import send_telegram_message
   >>> send_telegram_message('[TEST] Telegram working')

3. Test Complete Flow:
   python manage.py shell
   >>> from livetracker.alertService.notification_service import send_alert_notification
   >>> from livetracker.alertService.event_mapping import EventIDs
   >>> results = send_alert_notification(
   ...     event_id=EventIDs.GATE_IN_MANAWAR,
   ...     alert_text="[TEST] All channels working",
   ...     priority="high",
   ...     vehicle_no="TEST-001"
   ... )
   >>> print(results)

4. Test SQS Processing:
   python manage.py process_vendor_alerts
"""
