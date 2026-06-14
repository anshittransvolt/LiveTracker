import requests
import json
import logging
from django.conf import settings
from typing import List, Optional, Dict, Any
from email_service.constants import FEEDBACK_TO_RECIPIENTS, FEEDBACK_CC_RECIPIENTS
logger = logging.getLogger(__name__)


class CNSEmailService:
    """
    Service class for sending password reset OTP emails through CNS (Cloud Notification Service)
    """

    def __init__(self):
        self.access_key = getattr(settings, "CNS_ACCESS_KEY", None)
        self.base_url = getattr(settings, "CNS_BASE_URL")
        self.email_endpoint = f"{self.base_url}/email/send/"

        if not self.access_key:
            logger.warning("CNS_ACCESS_KEY not configured in settings")

    def _make_request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Make HTTP POST request to CNS service

        Args:
            payload: Email data to send

        Returns:
            Dict containing response from CNS service
        """
        headers = {"Content-Type": "application/json", "X-Access-Key": self.access_key}

        try:
            response = requests.post(
                self.email_endpoint, json=payload, headers=headers, timeout=30
            )

            # Parse response
            response_data = response.json()

            if response.status_code == 200:
                logger.info(
                    f"Email sent successfully. Email ID: {response_data.get('email_id')}"
                )
                return {"success": True, "data": response_data}
            else:
                logger.error(f"CNS API error: {response_data}")
                return {
                    "success": False,
                    "error": response_data.get("error", "Unknown error"),
                    "details": response_data.get("details", ""),
                }

        except requests.exceptions.RequestException as e:
            logger.error(f"Network error while sending email: {str(e)}")
            return {"success": False, "error": "Network error", "details": str(e)}
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON response from CNS: {str(e)}")
            return {
                "success": False,
                "error": "Invalid response format",
                "details": str(e),
            }
        except Exception as e:
            logger.error(f"Unexpected error while sending email: {str(e)}")
            return {"success": False, "error": "Unexpected error", "details": str(e)}

    def send_password_reset_otp(self, recipient: str, otp_code: str) -> Dict[str, Any]:
        """
        Send password reset OTP email

        Args:
            recipient: Recipient email address
            otp_code: OTP code to send

        Returns:
            Dict with success status and response data
        """
        if not self.access_key:
            return {"success": False, "error": "CNS access key not configured"}

        if not recipient:
            return {"success": False, "error": "Recipient email cannot be empty"}

        subject = "Password Reset - LiveTracker"
        content = f"""
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <h2 style="color: #dc2626;">Password Reset Request</h2>
                <p>You have requested to reset your LiveTracker account password. Use the OTP below:</p>
                <div style="background: #fef2f2; padding: 20px; text-align: center; margin: 20px 0; border: 1px solid #fecaca;">
                    <h1 style="color: #dc2626; font-size: 32px; margin: 0;">{otp_code}</h1>
                </div>
                <p>This OTP will expire in 10 minutes.</p>
                <p>If you didn't request a password reset, please secure your account immediately.</p>
            </div>
        """

        # Prepare payload
        payload = {"recipients": [recipient], "subject": subject, "content": content}

        return self._make_request(payload)

    def send_change_password_otp(self, recipient: str, otp_code: str) -> Dict[str, Any]:
        """
        Send change password OTP email

        Args:
            recipient: Recipient email address
            otp_code: OTP code to send

        Returns:
            Dict with success status and response data
        """
        if not self.access_key:
            return {"success": False, "error": "CNS access key not configured"}

        if not recipient:
            return {"success": False, "error": "Recipient email cannot be empty"}

        subject = "Password Change Verification - LiveTracker"
        content = f"""
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <h2 style="color: #2563eb;">Password Change Verification</h2>
                <p>You have requested to change your LiveTracker account password. Use the OTP below to proceed:</p>
                <div style="background: #eff6ff; padding: 20px; text-align: center; margin: 20px 0; border: 1px solid #bfdbfe;">
                    <h1 style="color: #2563eb; font-size: 32px; margin: 0;">{otp_code}</h1>
                </div>
                <p>This OTP will expire in 10 minutes.</p>
                <p>If you didn't request a password change, please secure your account immediately.</p>
            </div>
        """

        # Prepare payload
        payload = {"recipients": [recipient], "subject": subject, "content": content}

        return self._make_request(payload)

    def send_feedback_notification(self, feedback_instance) -> Dict[str, Any]:
        """
        Send notification email when new feedback is submitted

        Args:
            feedback_instance: Feedback model instance

        Returns:
            Dict with success status and response data
        """
        if not self.access_key:
            return {"success": False, "error": "CNS access key not configured"}

      

        # Determine feedback type icon and color
        if feedback_instance.feedback_type == 'bug':
            type_label = "Bug Report"
            type_color = "#dc2626"
            bg_color = "#fef2f2"
            border_color = "#fecaca"
        else:
            type_label = "Feature Request"
            type_color = "#2563eb"
            bg_color = "#eff6ff"
            border_color = "#bfdbfe"

        # Get reporter info
        reporter_name = feedback_instance.reported_by.get_full_name() or feedback_instance.reported_by.username
        reporter_email = feedback_instance.reported_by.email

       

        # Build page URL section
        page_url_html = ""
        if feedback_instance.page_url:
            page_url_html = f"""
                <div style="margin: 10px 0;">
                    <strong>Page URL:</strong>
                    <div style="margin-top: 5px; word-break: break-all;">
                        <a href="{feedback_instance.page_url}" target="_blank" style="color: #2563eb; text-decoration: none;">
                            {feedback_instance.page_url}
                        </a>
                    </div>
                </div>
            """

        # Build browser/device info
        device_info_html = ""
        if feedback_instance.browser or feedback_instance.os or feedback_instance.device:
            device_info_html = f"""
                <div style="background: #f9fafb; padding: 15px; border-radius: 5px; margin: 20px 0;">
                    <strong>Device Information:</strong>
                    <div style="margin-top: 10px; font-size: 14px; color: #6b7280;">
                        {f'<div>Browser: {feedback_instance.browser}</div>' if feedback_instance.browser else ''}
                        {f'<div>OS: {feedback_instance.os}</div>' if feedback_instance.os else ''}
                        {f'<div>Device: {feedback_instance.device}</div>' if feedback_instance.device else ''}
                    </div>
                </div>
            """

        subject = f"[LiveTracker] New {feedback_instance.get_feedback_type_display()}: {feedback_instance.title}"
        
        content = f"""
            <div style="font-family: Arial, sans-serif; max-width: 700px; margin: 0 auto; padding: 20px;">
                <div style="background: {bg_color}; padding: 20px; border-left: 4px solid {type_color}; margin-bottom: 20px;">
                    <h2 style="color: {type_color}; margin: 0 0 10px 0;">{type_label}</h2>
                    <h3 style="margin: 0; color: #1f2937;">{feedback_instance.title}</h3>
                </div>

                <div style="background: white; padding: 20px; border: 1px solid #e5e7eb; border-radius: 5px;">
                    <div style="margin-bottom: 20px;">
                        <strong>Description:</strong>
                        <div style="margin-top: 10px; line-height: 1.6; color: #374151;">
                            {feedback_instance.description}
                        </div>
                    </div>

                    {page_url_html}

                    <div style="margin: 20px 0; padding-top: 20px; border-top: 1px solid #e5e7eb;">
                        <strong>Reported By:</strong>
                        <div style="margin-top: 10px; color: #374151;">
                            <div>{reporter_name}</div>
                            <div style="color: #6b7280; font-size: 14px;">{reporter_email}</div>
                        </div>
                    </div>

                

                    {device_info_html}

                    <div style="margin-top: 20px; padding-top: 20px; border-top: 1px solid #e5e7eb; font-size: 14px; color: #6b7280;">
                        <div>Submitted: {feedback_instance.created_at.strftime('%B %d, %Y at %I:%M %p')}</div>
                        <div>Feedback ID: #{feedback_instance.id}</div>
                    </div>

                    
                </div>

                <div style="margin-top: 20px; text-align: center; font-size: 12px; color: #9ca3af;">
                    <p>This is an automated notification from LiveTracker Feedback System</p>
                </div>
            </div>
        """

        # Prepare payload with TO and CC
        payload = {
            "recipients": FEEDBACK_TO_RECIPIENTS,
            "subject": subject,
            "content": content
        }

        # Add CC if available
        if FEEDBACK_CC_RECIPIENTS:
            payload["cc_list"] = FEEDBACK_CC_RECIPIENTS

        return self._make_request(payload)


# Create a singleton instance for easy import
cns_email_service = CNSEmailService()
