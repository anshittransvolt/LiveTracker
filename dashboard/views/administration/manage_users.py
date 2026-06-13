from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User, Group
from django.contrib import messages
from django.db.models import Q, F
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_protect
from datetime import datetime, time
import json

from dashboard.models import UserProfile


def is_superuser(user):
    return user.is_superuser


@login_required
@user_passes_test(is_superuser)
def manage_users(request):
    """
    Manage users: Create, view, edit, and delete users.
    Only accessible to superusers/admins.
    """
    # Get all users
    users = User.objects.select_related('profile__group').all()
    
    # Get filter and search parameters
    search_query = request.GET.get('search', '').strip()
    status_filter = request.GET.get('status', 'all')
    group_filter = request.GET.get('group', 'all')
    
    # Apply search filter
    if search_query:
        users = users.filter(
            Q(username__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(first_name__icontains=search_query) |
            Q(last_name__icontains=search_query)
        )
    
    # Apply status filter
    if status_filter == 'active':
        users = users.filter(is_active=True)
    elif status_filter == 'inactive':
        users = users.filter(is_active=False)
    
    # Apply group filter
    if group_filter == 'none':
        users = users.filter(profile__group__isnull=True)
    elif group_filter not in ('all', '', None):
        # Expect group id
        users = users.filter(profile__group_id=group_filter)
    
    # Get all groups for filter dropdown
    groups = Group.objects.all().order_by('name')
    
    # Count statistics
    total_users = User.objects.count()
    active_users_count = User.objects.filter(is_active=True).count()
    inactive_users_count = User.objects.filter(is_active=False).count()
    superusers_count = User.objects.filter(is_superuser=True).count()
    staff_count = User.objects.filter(is_staff=True).count()
    
    # Order by most recently joined
    users = users.order_by('-date_joined')
    
    context = {
        'users': users,
        'groups': groups,
        'search_query': search_query,
        'status_filter': status_filter,
        'group_filter': group_filter,
        'total_users': total_users,
        'active_users_count': active_users_count,
        'inactive_users_count': inactive_users_count,
        'superusers_count': superusers_count,
        'staff_count': staff_count,
        'filtered_count': users.count(),
    }
    
    return render(request, 'dashboard/administration/manage_users.html', context)


@login_required
@user_passes_test(is_superuser)
def toggle_user_active(request, user_id):
    """Toggle user active/inactive status"""
    user = get_object_or_404(User, pk=user_id)
    
    # Prevent deactivating self
    if user == request.user:
        messages.error(request, "You cannot deactivate your own account!")
        return redirect('dashboard:manage_users')
    
    user.is_active = not user.is_active
    user.save()
    
    status = "activated" if user.is_active else "deactivated"
    messages.success(request, f"User {user.username} has been {status}.")
    
    return redirect('dashboard:manage_users')


@login_required
@user_passes_test(is_superuser)
def toggle_user_staff(request, user_id):
    """Toggle user staff status"""
    user = get_object_or_404(User, pk=user_id)
    
    # Prevent removing own staff status
    if user == request.user and user.is_staff:
        messages.error(request, "You cannot remove your own staff status!")
        return redirect('dashboard:manage_users')
    
    user.is_staff = not user.is_staff
    user.save()
    
    status = "granted" if user.is_staff else "removed"
    messages.success(request, f"Staff privileges {status} for user {user.username}.")
    
    return redirect('dashboard:manage_users')


@login_required
@user_passes_test(is_superuser)
def toggle_user_superuser(request, user_id):
    """Toggle user superuser status"""
    user = get_object_or_404(User, pk=user_id)
    
    # Prevent removing own superuser status
    if user == request.user and user.is_superuser:
        messages.error(request, "You cannot remove your own superuser status!")
        return redirect('dashboard:manage_users')
    
    user.is_superuser = not user.is_superuser
    if user.is_superuser:
        user.is_staff = True  # Superusers must be staff
    user.save()
    
    status = "granted" if user.is_superuser else "removed"
    messages.success(request, f"Superuser privileges {status} for user {user.username}.")
    
    return redirect('dashboard:manage_users')


@login_required
@user_passes_test(is_superuser)
@require_http_methods(["POST"])
def set_user_group(request, user_id):
    """Assign/clear a user's affiliated group (UserProfile.group)."""
    user = get_object_or_404(User, pk=user_id)
    group_id = (request.POST.get("group_id") or "").strip()

    if group_id:
        group = get_object_or_404(Group, pk=group_id)
    else:
        group = None

    profile, _ = UserProfile.objects.get_or_create(user=user, defaults={"msal_connected": False})
    profile.group = group
    profile.save()

    if group:
        messages.success(request, f"Assigned {user.username} to group {group.name}.")
    else:
        messages.success(request, f"Cleared group for {user.username}.")

    next_url = request.POST.get("next") or request.META.get("HTTP_REFERER")
    return redirect(next_url or 'dashboard:manage_users')


@login_required
@user_passes_test(is_superuser)
@require_http_methods(["POST"])
@csrf_protect
def update_user_profile(request, user_id):
    """Update user profile information (first_name, last_name, group_id) via JSON POST."""
    try:
        user = get_object_or_404(User, pk=user_id)
        
        # Parse JSON body
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse(
                {"success": False, "error": "Invalid JSON payload"},
                status=400
            )
        
        # Update first_name and last_name if provided
        if "first_name" in data:
            user.first_name = data["first_name"].strip()
        if "last_name" in data:
            user.last_name = data["last_name"].strip()
        user.save()
        
        # Update group if provided
        group_id = data.get("group_id")
        if group_id:
            group = get_object_or_404(Group, pk=group_id)
        else:
            group = None
        
        profile, _ = UserProfile.objects.get_or_create(user=user, defaults={"msal_connected": False})
        profile.group = group
        profile.save()
        
        return JsonResponse(
            {
                "success": True,
                "message": f"Profile updated successfully for {user.username}."
            },
            status=200
        )
    
    except Exception as e:
        return JsonResponse(
            {"success": False, "error": str(e)},
            status=500
        )

