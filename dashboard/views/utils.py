import random
import string
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from ..vendor_spv_list import VENDOR_SPV_LIST
from ..project_routing import build_project_prefixed_path, project_to_slug


def generate_otp():
    """Generate a 6-digit OTP"""
    return "".join(random.choices(string.digits, k=6))


@login_required
@require_POST
def set_project(request):
    """
    API endpoint to set the active project in user's session.
    VALIDATES PROJECT ACCESS using RBAC before allowing project switch.

    POST Parameters:
        project (str): Project name from VENDOR_SPV_LIST keys

    Returns:
        JSON: {success: bool, project: str, spv_list: list}
    """
    project = request.POST.get("project", "").strip()

    if not project:
        return JsonResponse(
            {"success": False, "error": "Project name is required"}, status=400
        )

    if project not in VENDOR_SPV_LIST:
        return JsonResponse(
            {"success": False, "error": f"Invalid project: {project}"}, status=400
        )

    # RBAC CHECK: Validate user has access to the requested project
    from dashboard.services.rbacService import RBACService
    
    if not request.user.is_superuser:
        if not RBACService.can_access_project_url(request.user, project):
            # Log unauthorized attempt
            print(f"[RBAC VIOLATION] User {request.user.username} attempted unauthorized project switch to: {project}")
            return JsonResponse(
                {"success": False, "error": "You do not have access to this project."}, 
                status=403
            )

    # Store project in session
    request.session["selected_project"] = project

    current_path = request.POST.get("next", "").strip() or request.META.get(
        "HTTP_REFERER", ""
    )
    redirect_url = build_project_prefixed_path(current_path, project)

    return JsonResponse(
        {
            "success": True,
            "project": project,
            "project_slug": project_to_slug(project),
            "spv_list": VENDOR_SPV_LIST[project],
            "redirect_url": redirect_url,
        }
    )
