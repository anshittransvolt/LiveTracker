"""
Validation Service for VolTrack Dashboard

This service handles input validation for various forms.
"""


class ValidationService:
    """Service class for handling input validation"""

    @staticmethod
    def validate_email(email):
        """
        Validate email format

        Args:
            email (str): Email to validate

        Returns:
            tuple: (is_valid, error_message)
        """
        if not email or not email.strip():
            return False, "Please enter your email address."

        email = email.strip()

        # Basic email validation
        if "@" not in email or "." not in email:
            return False, "Please enter a valid email address."

        return True, None

    @staticmethod
    def validate_password_strength(password):
        """
        Validate password strength

        Args:
            password (str): Password to validate

        Returns:
            tuple: (is_valid, error_message)
        """
        if not password:
            return False, "Password is required."

        if len(password) < 8:
            return False, "Password must be at least 8 characters long."

        return True, None

    @staticmethod
    def validate_password_match(password, confirm_password):
        """
        Validate password confirmation

        Args:
            password (str): Original password
            confirm_password (str): Confirmation password

        Returns:
            tuple: (is_valid, error_message)
        """
        if password != confirm_password:
            return False, "Passwords do not match."

        return True, None

    @staticmethod
    def validate_otp(otp):
        """
        Validate OTP format

        Args:
            otp (str): OTP to validate

        Returns:
            tuple: (is_valid, error_message)
        """
        if not otp or not otp.strip():
            return False, "Please enter the verification code."

        otp = otp.strip()

        if len(otp) != 6:
            return False, "Verification code must be 6 digits."

        if not otp.isdigit():
            return False, "Verification code must contain only numbers."

        return True, None

    @staticmethod
    def validate_forgot_password_form(otp, new_password, confirm_password):
        """
        Validate forgot password form data

        Args:
            otp (str): OTP
            new_password (str): New password
            confirm_password (str): Confirmation password

        Returns:
            tuple: (is_valid, error_message)
        """
        # Check if all fields are provided
        if not all([otp, new_password, confirm_password]):
            return False, "Please fill in all fields."

        # Validate OTP
        otp_valid, otp_error = ValidationService.validate_otp(otp)
        if not otp_valid:
            return False, otp_error

        # Validate password strength
        pwd_valid, pwd_error = ValidationService.validate_password_strength(
            new_password
        )
        if not pwd_valid:
            return False, pwd_error

        # Validate password match
        match_valid, match_error = ValidationService.validate_password_match(
            new_password, confirm_password
        )
        if not match_valid:
            return False, match_error

        return True, None

    @staticmethod
    def validate_change_password_form(otp, new_password, confirm_password):
        """
        Validate change password form data

        Args:
            otp (str): OTP
            new_password (str): New password
            confirm_password (str): Confirmation password

        Returns:
            tuple: (is_valid, error_message)
        """
        # Same validation as forgot password
        return ValidationService.validate_forgot_password_form(
            otp, new_password, confirm_password
        )


# Service instance for easy import
validation_service = ValidationService()
