from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import Group, User
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
import json

from dashboard.models import Project, Page, GroupAccess, UserProfile


def is_admin(user):
    """Check if user is admin (superuser or staff)"""
    return user.is_superuser or user.is_staff


@login_required
@user_passes_test(is_admin)
def manage_group_access(request):
    """View to manage group access to projects and pages."""
    # Get all data
    groups = Group.objects.all().order_by('name')
    projects = Project.objects.filter(is_active=True).order_by('name')
    pages = Page.objects.all().order_by('section', 'code')
    
    # Get users with their group information
    users = User.objects.filter(is_active=True).select_related('profile__group').order_by('username')
    user_data = []
    for user in users:
        try:
            profile = user.profile
            group = profile.group
            user_data.append({
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'group_id': group.id if group else None,
                'group_name': group.name if group else 'No Group',
                'is_superuser': user.is_superuser,
                'is_staff': user.is_staff,
            })
        except UserProfile.DoesNotExist:
            user_data.append({
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'group_id': None,
                'group_name': 'No Group',
                'is_superuser': user.is_superuser,
                'is_staff': user.is_staff,
            })
    
    # Prepare group access data
    group_access_data = []
    for group in groups:
        try:
            group_access = GroupAccess.objects.get(group=group)
            projects_list = list(group_access.projects.values_list('name', flat=True))
            pages_list = list(group_access.pages.values_list('code', flat=True))
        except GroupAccess.DoesNotExist:
            projects_list = []
            pages_list = []
        
        group_access_data.append({
            'id': group.id,
            'name': group.name,
            'users_count': UserProfile.objects.filter(group=group).count(),
            'projects': projects_list,
            'pages': pages_list,
        })
    
    # Convert to JSON for JavaScript
    projects_json = json.dumps([{'id': p.id, 'name': p.name} for p in projects])
    pages_json = json.dumps([{'id': p.id, 'name': p.name, 'code': p.code} for p in pages])
    groups_json = json.dumps(group_access_data)
    users_json = json.dumps(user_data)
    
    context = {
        'groups': groups,
        'projects': projects,
        'pages': pages,
        'users': user_data,
        'group_access_data': group_access_data,
        'projects_json': projects_json,
        'pages_json': pages_json,
        'groups_json': groups_json,
        'users_json': users_json,
    }
    
    return render(request, 'dashboard/administration/manage_group_access.html', context)


@login_required
@user_passes_test(is_admin)
@require_http_methods(["POST"])
def update_group_projects(request, group_id):
    """
    API endpoint to update a group's project access.
    Expects JSON with list of project IDs.
    """
    try:
        group = get_object_or_404(Group, id=group_id)
        group_access, created = GroupAccess.objects.get_or_create(group=group)
        
        # Get project IDs from request
        project_ids = request.POST.getlist('project_ids[]')
        
        # Clear existing projects and add new ones
        group_access.projects.clear()
        group_access.projects.add(*project_ids)
        
        print(f"[ADMIN] User {request.user.username} updated group {group.name} projects: {project_ids}")
        
        return JsonResponse({
            'status': 'success',
            'message': f'Updated projects for group {group.name}'
        })
    
    except Exception as e:
        print(f"[ADMIN ERROR] Error updating group projects: {e}")
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=400)


@login_required
@user_passes_test(is_admin)
@require_http_methods(["POST"])
def update_group_pages(request, group_id):
    """
    API endpoint to update a group's page access.
    Expects JSON with list of page IDs.
    """
    try:
        group = get_object_or_404(Group, id=group_id)
        group_access, created = GroupAccess.objects.get_or_create(group=group)
        
        # Get page IDs from request
        page_ids = request.POST.getlist('page_ids[]')
        
        # Clear existing pages and add new ones
        group_access.pages.clear()
        group_access.pages.add(*page_ids)
        
        print(f"[ADMIN] User {request.user.username} updated group {group.name} pages: {page_ids}")
        
        return JsonResponse({
            'status': 'success',
            'message': f'Updated pages for group {group.name}'
        })
    
    except Exception as e:
        print(f"[ADMIN ERROR] Error updating group pages: {e}")
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=400)


@login_required
@user_passes_test(is_admin)
@require_http_methods(["GET"])
def get_group_access(request, group_id):
    """
    API endpoint to get a group's current access to projects and pages.
    Returns JSON with lists of accessible project and page IDs.
    """
    try:
        group = get_object_or_404(Group, id=group_id)
        group_access = GroupAccess.objects.filter(group=group).first()
        
        if not group_access:
            return JsonResponse({
                'project_ids': [],
                'page_ids': [],
            }, status=200)
        
        project_ids = list(group_access.projects.values_list('id', flat=True))
        page_ids = list(group_access.pages.values_list('id', flat=True))
        
        return JsonResponse({
            'project_ids': project_ids,
            'page_ids': page_ids,
        }, status=200)
    
    except Exception as e:
        print(f"[ADMIN ERROR] Error getting group access: {e}")
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=400)


@login_required
@user_passes_test(is_admin)
@require_http_methods(["POST"])
def create_group(request):
    """Create a new Django auth Group for RBAC access management."""
    name = (request.POST.get("name") or "").strip()
    if not name:
        messages.error(request, "Group name is required.")
        return redirect("dashboard:manage_group_access")

    group, created = Group.objects.get_or_create(name=name)
    if created:
        messages.success(request, f"Group '{name}' created.")
    else:
        messages.warning(request, f"Group '{name}' already exists.")

    return redirect("dashboard:manage_group_access")
