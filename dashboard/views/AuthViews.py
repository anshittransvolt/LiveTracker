from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.contrib.auth.models import User
from django.core.cache import cache
import random
import string
from ..services.microsoftAuth import microsoft_auth_service
from email_service.services.emailservice import cns_email_service
from ..forms import LoginCaptchaForm

@never_cache
@csrf_protect
def login_view(request):
    """Handle user login"""
    if request.user.is_authenticated:
        return redirect("dashboard:dashboard") 

    captcha_form = LoginCaptchaForm(request.POST or None)

    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")

        if not captcha_form.is_valid():
            messages.error(request, "Captcha validation failed. Please try again.")
            return render(request, "dashboard/auth/login.html", {"captcha_form": captcha_form})

        if username and password:
            user = authenticate(request, username=username, password=password)
            if user is not None:
                from ..models import UserProfile

                profile, created = UserProfile.objects.get_or_create(user=user)
                if profile.msal_connected:
                    pass
                else:
                    profile.msal_connected = False
                    profile.save()

                login(request, user)
                messages.success(
                    request, f"Welcome back, {user.first_name or user.username}!"
                )

                next_url = request.GET.get("next")
                if next_url:
                    return redirect(next_url)
                else:
                    return redirect("dashboard:dashboard")
            else:
                messages.error(
                    request, "Invalid username or password. Please try again."
                )
                captcha_form = LoginCaptchaForm()
        else:
            messages.error(request, "Please enter both username and password.")

    return render(request, "dashboard/auth/login.html", {"captcha_form": captcha_form})


@login_required
def logout_view(request):
    """Handle user logout"""
    user_name = request.user.first_name or request.user.username
    logout(request)
    messages.success(request, "You have been successfully logged out.")
    return redirect("dashboard:login")


def microsoft_login(request):
    """Initiate Microsoft OAuth login"""

    is_valid, error_message = microsoft_auth_service.validate_configuration()
    if not is_valid:
        messages.error(request, error_message)
        return redirect("dashboard:login")

    try:
        auth_url = microsoft_auth_service.get_authorization_url()
        return redirect(auth_url)

    except Exception as e:
        messages.error(request, f"Microsoft authentication setup error: {str(e)}")
        return redirect("dashboard:login")


def microsoft_callback(request):
    """Handle Microsoft OAuth callback"""
    code = request.GET.get("code")
    error = request.GET.get("error")

    if error:
        error_description = request.GET.get(
            "error_description", "Authentication was cancelled or failed"
        )
        return render(
            request, "dashboard/auth/error.html", {"error": error_description}
        )

    if not code:
        return render(
            request,
            "dashboard/auth/error.html",
            {"error": "No authorization code returned from Microsoft"},
        )

    success, message, user = microsoft_auth_service.process_callback(code)

    if success and user:
        login(request, user)
        messages.success(request, message)
        return redirect("dashboard:dashboard")
    else:
        return render(request, "dashboard/auth/error.html", {"error": message})


def tos(request):
    """Render Terms of Service page (public)"""
    return render(request, "dashboard/base/tos.html")


def privacy(request):
    """Render Privacy Policy page (public). If you have a dedicated template, render it; otherwise reuse TOS temporarily."""
    # If a dedicated privacy template exists, change the template name below.
    return render(request, "dashboard/base/privacy.html")


def generate_otp():
    """Generate a 6-digit OTP"""
    return "".join(random.choices(string.digits, k=6))

def access_denied(request):
    """Render Access Denied page"""
    return render(request, "dashboard/auth/access_denied_page.html")

@never_cache
@csrf_protect
def forgot_password_request(request):
    """Handle forgot password email request"""
    if request.method == "POST":
        email = request.POST.get("email", "").strip()

        if not email:
            messages.error(request, "Please enter your email address.")
            return render(request, "dashboard/auth/forgot_password.html")

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            messages.success(
                request,
                "If an account with this email exists, you will receive a password reset code.",
            )
            return render(request, "dashboard/auth/forgot_password.html")

        otp = generate_otp()

        cache_key = f"password_reset_otp_{email}"
        cache.set(cache_key, otp, 600)  # 10 minutes

        result = cns_email_service.send_password_reset_otp(email, otp)

        if result["success"]:
            messages.success(
                request, "Password reset code has been sent to your email address."
            )
            request.session["reset_email"] = email
            return redirect("dashboard:forgot_password_verify")
        else:
            messages.error(
                request, "Failed to send password reset email. Please try again."
            )
            return render(request, "dashboard/auth/forgot_password.html")

    return render(request, "dashboard/auth/forgot_password.html")


@never_cache
@csrf_protect
def forgot_password_verify(request):
    """Handle OTP verification and password reset"""
    email = request.session.get("reset_email")

    if not email:
        messages.error(
            request, "Session expired. Please start the password reset process again."
        )
        return redirect("dashboard:forgot_password_request")

    if request.method == "POST":
        otp = request.POST.get("otp", "").strip()
        new_password = request.POST.get("new_password", "").strip()
        confirm_password = request.POST.get("confirm_password", "").strip()

        if not all([otp, new_password, confirm_password]):
            messages.error(request, "Please fill in all fields.")
            return render(
                request, "dashboard/auth/forgot_password_verify.html", {"email": email}
            )

        if new_password != confirm_password:
            messages.error(request, "Passwords do not match.")
            return render(
                request, "dashboard/auth/forgot_password_verify.html", {"email": email}
            )

        if len(new_password) < 8:
            messages.error(request, "Password must be at least 8 characters long.")
            return render(
                request, "dashboard/auth/forgot_password_verify.html", {"email": email}
            )

        cache_key = f"password_reset_otp_{email}"
        cached_otp = cache.get(cache_key)

        if not cached_otp:
            messages.error(
                request, "OTP has expired. Please request a new password reset."
            )
            del request.session["reset_email"]
            return redirect("dashboard:forgot_password_request")

        if otp != cached_otp:
            messages.error(request, "Invalid OTP. Please try again.")
            return render(
                request, "dashboard/auth/forgot_password_verify.html", {"email": email}
            )

        try:
            user = User.objects.get(email=email)
            user.set_password(new_password)
            user.save()

            cache.delete(cache_key)
            del request.session["reset_email"]

            messages.success(
                request,
                "Your password has been reset successfully. Please log in with your new password.",
            )
            return redirect("dashboard:login")

        except User.DoesNotExist:
            messages.error(request, "User not found. Please try again.")
            del request.session["reset_email"]
            return redirect("dashboard:forgot_password_request")

    return render(
        request, "dashboard/auth/forgot_password_verify.html", {"email": email}
    )


@login_required
@csrf_protect
def change_password_request(request):
    """Request OTP for password change"""
    if request.method == "POST":
        otp = generate_otp()
        email = request.user.email

        if not email:
            messages.error(
                request,
                "No email address associated with your account. Please contact administrator.",
            )
            return redirect("dashboard:profile")

        cache_key = f"change_password_otp_{request.user.id}"
        cache.set(cache_key, otp, 600)  # 10 minutes

        result = cns_email_service.send_change_password_otp(email, otp)

        if result.get("success"):
            messages.success(request, f"A verification code has been sent to {email}")
            return redirect("dashboard:change_password_verify")
        else:
            messages.error(
                request, "Failed to send verification email. Please try again."
            )
            return redirect("dashboard:profile")

    return redirect("dashboard:profile")


@login_required
@csrf_protect
def change_password_verify(request):
    """Verify OTP and change password"""
    if request.method == "POST":
        otp = request.POST.get("otp", "").strip()
        new_password = request.POST.get("new_password", "")
        confirm_password = request.POST.get("confirm_password", "")

        if not all([otp, new_password, confirm_password]):
            messages.error(request, "All fields are required.")
            return render(request, "dashboard/auth/change_password_verify.html")

        if new_password != confirm_password:
            messages.error(request, "Passwords do not match.")
            return render(request, "dashboard/auth/change_password_verify.html")

        if len(new_password) < 8:
            messages.error(request, "Password must be at least 8 characters long.")
            return render(request, "dashboard/auth/change_password_verify.html")

        cache_key = f"change_password_otp_{request.user.id}"
        cached_otp = cache.get(cache_key)

        if not cached_otp:
            messages.error(
                request, "OTP has expired. Please request a new verification code."
            )
            return redirect("dashboard:profile")

        if otp != cached_otp:
            messages.error(request, "Invalid OTP. Please try again.")
            return render(request, "dashboard/auth/change_password_verify.html")

        try:
            user = request.user
            user.set_password(new_password)
            user.save()

            cache.delete(cache_key)
            logout(request)

            messages.success(
                request,
                "Your password has been changed successfully. Please log in with your new password.",
            )
            return redirect("dashboard:login")

        except Exception as e:
            messages.error(
                request, "An error occurred while changing password. Please try again."
            )
            return render(request, "dashboard/auth/change_password_verify.html")

    return render(request, "dashboard/auth/change_password_verify.html")
