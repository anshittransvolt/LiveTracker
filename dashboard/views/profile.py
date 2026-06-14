from django.shortcuts import render
from django.contrib.auth.decorators import login_required


@login_required
def profile(request):
    """User profile view"""
    from ..models import UserProfile

    profile, created = UserProfile.objects.get_or_create(user=request.user)

    context = {"user": request.user, "title": "Profile - LiveTracker"}
    return render(request, "dashboard/profile.html", context)
