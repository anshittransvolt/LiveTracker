"""
OTP Service for LiveTracker Dashboard

This service handles all OTP-related operations including:
- OTP generation
- OTP validation
- Cache management
- Email sending integration
"""

import random
import string
from django.core.cache import cache
from django.contrib.auth.models import User
from email_service.services.emailservice import cns_email_service


class OTPService:
    """Service class for handling OTP operations"""

    # Cache key templates
    FORGOT_PASSWORD_KEY_TEMPLATE = "password_reset_otp_{email}"
    CHANGE_PASSWORD_KEY_TEMPLATE = "change_password_otp_{user_id}"

    # OTP configuration
    OTP_LENGTH = 6
    OTP_EXPIRY_SECONDS = 600  # 10 minutes

    @staticmethod
    def generate_otp(length=None):
        """
        Generate a random OTP

        Args:
            length (int): Length of OTP (default: 6)

        Returns:
            str: Generated OTP
        """
        if length is None:
            length = OTPService.OTP_LENGTH
        return "".join(random.choices(string.digits, k=length))

    @staticmethod
    def _get_cache_key(template, **kwargs):
        """
        Generate cache key from template

        Args:
            template (str): Cache key template
            **kwargs: Template parameters

        Returns:
            str: Formatted cache key
        """
        return template.format(**kwargs)

    @staticmethod
    def store_otp(cache_key, otp, expiry_seconds=None):
        """
        Store OTP in cache

        Args:
            cache_key (str): Cache key
            otp (str): OTP to store
            expiry_seconds (int): Expiry time in seconds (default: 600)

        Returns:
            bool: Success status
        """
        if expiry_seconds is None:
            expiry_seconds = OTPService.OTP_EXPIRY_SECONDS

        try:
            cache.set(cache_key, otp, expiry_seconds)
            return True
        except Exception:
            return False

    @staticmethod
    def verify_otp(cache_key, provided_otp):
        """
        Verify OTP against cached value

        Args:
            cache_key (str): Cache key
            provided_otp (str): OTP provided by user

        Returns:
            tuple: (is_valid, is_expired)
        """
        cached_otp = cache.get(cache_key)

        if cached_otp is None:
            return False, True  # Invalid and expired

        is_valid = cached_otp == provided_otp
        return is_valid, False  # Valid/Invalid but not expired

    @staticmethod
    def clear_otp(cache_key):
        """
        Clear OTP from cache

        Args:
            cache_key (str): Cache key to clear

        Returns:
            bool: Success status
        """
        try:
            cache.delete(cache_key)
            return True
        except Exception:
            return False


class ForgotPasswordOTPService:
    """Service for handling forgot password OTP operations"""

    @staticmethod
    def send_reset_otp(email):
        """
        Generate and send password reset OTP

        Args:
            email (str): User's email address

        Returns:
            dict: Result with success status and message
        """
        try:
            # Check if user exists
            if not User.objects.filter(email=email).exists():
                # Return success for security (don't reveal user existence)
                return {
                    "success": True,
                    "message": "If an account with this email exists, you will receive a password reset code.",
                    "show_verify_page": False,
                }

            # Generate OTP
            otp = OTPService.generate_otp()

            # Store in cache
            cache_key = OTPService._get_cache_key(
                OTPService.FORGOT_PASSWORD_KEY_TEMPLATE, email=email
            )

            if not OTPService.store_otp(cache_key, otp):
                return {
                    "success": False,
                    "message": "Failed to generate verification code. Please try again.",
                }

            # Send email
            email_result = cns_email_service.send_password_reset_otp(email, otp)

            if email_result.get("success"):
                return {
                    "success": True,
                    "message": "Password reset code has been sent to your email address.",
                    "show_verify_page": True,
                }
            else:
                # Clear OTP if email failed
                OTPService.clear_otp(cache_key)
                return {
                    "success": False,
                    "message": "Failed to send password reset email. Please try again.",
                }

        except Exception as e:
            return {"success": False, "message": "An error occurred. Please try again."}

    @staticmethod
    def verify_and_reset_password(email, otp, new_password):
        """
        Verify OTP and reset user password

        Args:
            email (str): User's email address
            otp (str): OTP provided by user
            new_password (str): New password

        Returns:
            dict: Result with success status and message
        """
        try:
            # Get cache key
            cache_key = OTPService._get_cache_key(
                OTPService.FORGOT_PASSWORD_KEY_TEMPLATE, email=email
            )

            # Verify OTP
            is_valid, is_expired = OTPService.verify_otp(cache_key, otp)

            if is_expired:
                return {
                    "success": False,
                    "message": "OTP has expired. Please request a new password reset.",
                    "redirect_to_request": True,
                }

            if not is_valid:
                return {"success": False, "message": "Invalid OTP. Please try again."}

            # Get user and reset password
            user = User.objects.get(email=email)
            user.set_password(new_password)
            user.save()

            # Clear OTP
            OTPService.clear_otp(cache_key)

            return {
                "success": True,
                "message": "Your password has been reset successfully. Please log in with your new password.",
            }

        except User.DoesNotExist:
            return {
                "success": False,
                "message": "User not found. Please try again.",
                "redirect_to_request": True,
            }
        except Exception as e:
            return {
                "success": False,
                "message": "An error occurred while resetting password. Please try again.",
            }


class ChangePasswordOTPService:
    """Service for handling change password OTP operations"""

    @staticmethod
    def send_change_otp(user):
        """
        Generate and send change password OTP

        Args:
            user (User): Django User object

        Returns:
            dict: Result with success status and message
        """
        try:
            if not user.email:
                return {
                    "success": False,
                    "message": "No email address associated with your account. Please contact administrator.",
                }

            # Generate OTP
            otp = OTPService.generate_otp()

            # Store in cache
            cache_key = OTPService._get_cache_key(
                OTPService.CHANGE_PASSWORD_KEY_TEMPLATE, user_id=user.id
            )

            if not OTPService.store_otp(cache_key, otp):
                return {
                    "success": False,
                    "message": "Failed to generate verification code. Please try again.",
                }

            # Send email
            email_result = cns_email_service.send_change_password_otp(user.email, otp)

            if email_result.get("success"):
                return {
                    "success": True,
                    "message": f"A verification code has been sent to {user.email}",
                }
            else:
                # Clear OTP if email failed
                OTPService.clear_otp(cache_key)
                return {
                    "success": False,
                    "message": "Failed to send verification email. Please try again.",
                }

        except Exception as e:
            return {"success": False, "message": "An error occurred. Please try again."}

    @staticmethod
    def verify_and_change_password(user, otp, new_password):
        """
        Verify OTP and change user password

        Args:
            user (User): Django User object
            otp (str): OTP provided by user
            new_password (str): New password

        Returns:
            dict: Result with success status and message
        """
        try:
            # Get cache key
            cache_key = OTPService._get_cache_key(
                OTPService.CHANGE_PASSWORD_KEY_TEMPLATE, user_id=user.id
            )

            # Verify OTP
            is_valid, is_expired = OTPService.verify_otp(cache_key, otp)

            if is_expired:
                return {
                    "success": False,
                    "message": "OTP has expired. Please request a new verification code.",
                    "redirect_to_profile": True,
                }

            if not is_valid:
                return {"success": False, "message": "Invalid OTP. Please try again."}

            # Change password
            user.set_password(new_password)
            user.save()

            # Clear OTP
            OTPService.clear_otp(cache_key)

            return {
                "success": True,
                "message": "Your password has been changed successfully. Please log in with your new password.",
                "logout_required": True,
            }

        except Exception as e:
            return {
                "success": False,
                "message": "An error occurred while changing password. Please try again.",
            }


# Service instances for easy import
otp_service = OTPService()
forgot_password_service = ForgotPasswordOTPService()
change_password_service = ChangePasswordOTPService()
