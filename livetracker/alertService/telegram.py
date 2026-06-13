import requests
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

def send_telegram_message(message):
    """
    Send alert message to Telegram
    Args:
        message: Alert text to send
    Returns:
        Response JSON or None if failed
    """
    try:
        bot_token = settings.TELEGRAM_BOT_TOKEN
        chat_id = settings.TELEGRAM_CHAT_ID

        # Check if credentials are configured
        if not bot_token or not chat_id:
            logger.warning(
                "Telegram bot token or chat ID not configured. Skipping Telegram notification."
            )
            return None

        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",  # Allow HTML formatting
        }

        response = requests.post(url, data=payload, timeout=10)
        response.raise_for_status()

        result = response.json()

        if result.get("ok"):
            return result
        else:
            return None

    except requests.exceptions.Timeout:
        return None
    except requests.exceptions.RequestException as e:
        return None
    except Exception as e:
        logger.error(f"❌ Unexpected error sending Telegram message: {e}")
        return None
