import msal
import requests
from django.conf import settings
from django.contrib.auth.models import User
from typing import Dict, Optional, Tuple


class MicrosoftAuthService:
    """Service class to handle Microsoft OAuth authentication"""

    def __init__(self):
        self.client_id = settings.MICROSOFT_CLIENT_ID
        self.client_secret = settings.MICROSOFT_CLIENT_SECRET
        self.authority = settings.MICROSOFT_AUTHORITY
        self.scopes = settings.MICROSOFT_SCOPE
        self.redirect_uri = settings.MICROSOFT_REDIRECT_URI

    def validate_configuration(self) -> Tuple[bool, str]:
        """
        Validate Microsoft authentication configuration
        Returns: (is_valid, error_message)
        """
        # Check if all required settings are present
        if not all([self.client_id, self.client_secret, settings.MICROSOFT_TENANT_ID]):
            return (
                False,
                "Microsoft authentication is not properly configured. Please check your environment variables.",
            )

        # Check for placeholder values
        if (
            settings.MICROSOFT_TENANT_ID == "<YOUR_TENANT_ID>"
            or self.client_id == "your-microsoft-app-client-id"
            or self.client_secret == "your-microsoft-app-client-secret"
        ):
            return (
                False,
                "Please configure your Microsoft Azure AD credentials in the .env file.",
            )

        return True, ""

    def get_msal_app(self) -> msal.ConfidentialClientApplication:
        """Create and return MSAL application instance"""
        return msal.ConfidentialClientApplication(
            self.client_id,
            authority=self.authority,
            client_credential=self.client_secret,
        )

    def get_authorization_url(self) -> str:
        """
        Generate Microsoft OAuth authorization URL
        Returns: Authorization URL string
        """
        app = self.get_msal_app()
        auth_url = app.get_authorization_request_url(
            scopes=self.scopes, redirect_uri=self.redirect_uri
        )
        return auth_url

    def acquire_token_by_code(self, auth_code: str) -> Dict:
        """
        Exchange authorization code for access token
        Args:
            auth_code: Authorization code from Microsoft callback
        Returns: Token result dictionary
        """
        app = self.get_msal_app()
        result = app.acquire_token_by_authorization_code(
            code=auth_code, scopes=self.scopes, redirect_uri=self.redirect_uri
        )
        return result

    def get_user_info(self, access_token: str) -> Optional[Dict]:
        """
        Get user information from Microsoft Graph API
        Args:
            access_token: Valid access token
        Returns: User information dictionary or None if failed
        """
        try:
            response = requests.get(
                "https://graph.microsoft.com/v1.0/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code == 200:
                return response.json()
            else:
                return None
        except Exception:
            return None

    def create_or_update_user(self, user_info: Dict) -> Tuple[User, bool]:
        """
        Create or update Django user from Microsoft user info
        Args:
            user_info: User information from Microsoft Graph
        Returns: (User object, created boolean)
        """
        from ..models import UserProfile  # Import here to avoid circular imports

        email = user_info.get("mail") or user_info.get("userPrincipalName")
        display_name = user_info.get("displayName", "")
        first_name = user_info.get("givenName", "")
        last_name = user_info.get("surname", "")

        if not email:
            raise ValueError("No email found in Microsoft account")

        # Create or get user
        user, created = User.objects.get_or_create(
            username=email,
            defaults={
                "email": email,
                "first_name": first_name,
                "last_name": last_name,
            },
        )

        # Update user info if not created (existing user)
        if not created:
            user.first_name = first_name
            user.last_name = last_name
            user.email = email
            user.save()

        # Set MSAL connection status in profile
        profile, profile_created = UserProfile.objects.get_or_create(user=user)
        # print(f"DEBUG: Profile created: {profile_created}, User: {user.username}")
        # print(f"DEBUG: Profile before update - msal_connected: {profile.msal_connected}")
        profile.msal_connected = True
        profile.save()
        # print(f"DEBUG: Profile after update - msal_connected: {profile.msal_connected}")

        return user, created

    def process_callback(self, auth_code: str) -> Tuple[bool, str, Optional[User]]:
        """
        Process Microsoft OAuth callback
        Args:
            auth_code: Authorization code from callback
        Returns: (success, message, user_object)
        """
        try:
            # Get access token
            token_result = self.acquire_token_by_code(auth_code)

            if "access_token" not in token_result:
                error_msg = token_result.get(
                    "error_description", "Failed to get access token from Microsoft"
                )
                return False, error_msg, None

            # Get user information
            user_info = self.get_user_info(token_result["access_token"])
            if not user_info:
                return False, "Failed to get user information from Microsoft", None

            # Create or update user
            user, created = self.create_or_update_user(user_info)

            display_name = user_info.get("displayName", user.email)
            success_msg = (
                f"Welcome {display_name}! You have been signed in with Microsoft."
            )

            return True, success_msg, user

        except ValueError as e:
            return False, str(e), None
        except Exception as e:
            return False, f"Authentication error: {str(e)}", None


# Create a singleton instance for easy import
microsoft_auth_service = MicrosoftAuthService()
