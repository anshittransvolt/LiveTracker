"""
Django signals for livetracker app
Handles automated actions when model instances are created/updated
"""
import logging
from threading import Thread
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver
from livetracker.models.livetracker_feedback import Feedback
from email_service.services.emailservice import cns_email_service
from email_service.services.jira_service import create_jira_issue

logger = logging.getLogger(__name__)


def _build_feedback_jira_payload(feedback_instance):
    reporter_name = "Unknown"
    reporter_email = "Unknown"

    if feedback_instance.reported_by:
        reporter_name = (
            feedback_instance.reported_by.get_full_name()
            or feedback_instance.reported_by.username
        )
        reporter_email = feedback_instance.reported_by.email or "Unknown"

    feedback_type_label = feedback_instance.get_feedback_type_display()

    summary = f"[Feedback] {feedback_type_label}: {feedback_instance.title}"

    description_text = (
        f"Feedback ID: #{feedback_instance.id}\n"
        f"Type: {feedback_type_label}\n"
        f"Title: {feedback_instance.title}\n"
        f"Description: {feedback_instance.description}\n\n"
        f"Reported by: {reporter_name}\n"
        f"Page URL: {feedback_instance.page_url or 'N/A'}\n"
        f"Created at: {feedback_instance.created_at}\n\n"
    )

    return summary, description_text


def send_feedback_email_async(feedback_instance):
    """
    Send feedback notification email in background thread
    
    Args:
        feedback_instance: The feedback instance to send notification for
    """
    try:
        logger.info(f"Sending feedback notification for #{feedback_instance.id} - {feedback_instance.title}")
        
        # Send email notification
        result = cns_email_service.send_feedback_notification(feedback_instance)
        
        if result.get('success'):
            logger.info(f"Feedback notification sent successfully for #{feedback_instance.id}")
        else:
            logger.error(f"Failed to send feedback notification for #{feedback_instance.id}: {result.get('error')}")

        summary, description_text = _build_feedback_jira_payload(feedback_instance)
        jira_response = create_jira_issue(
            project_key='BFI',
            summary=summary,
            description_text=description_text,
            issue_type='Task',
        )
        jira_key = jira_response.get("key")
        if jira_key:
            logger.info(f"Jira issue created for feedback #{feedback_instance.id}: {jira_key}")
        else:
            logger.error(
                f"Jira issue creation may have failed for feedback #{feedback_instance.id}: {jira_response}"
            )
            
    except Exception as e:
        # Log error but don't break anything
        logger.error(f"Error sending feedback notification for #{feedback_instance.id}: {str(e)}", exc_info=True)


@receiver(post_save, sender=Feedback)
def notify_feedback_created(sender, instance, created, **kwargs):
    """
    Send email notification when new feedback is submitted (async)
    
    Args:
        sender: The model class (Feedback)
        instance: The actual feedback instance that was saved
        created: Boolean indicating if this is a new record
        **kwargs: Additional keyword arguments
    """
    if created:
        # Start email sending in background thread for instant response
        thread = Thread(target=send_feedback_email_async, args=(instance,), daemon=True)
        thread.start()
        logger.info(f"Feedback #{instance.id} created, email notification queued")
