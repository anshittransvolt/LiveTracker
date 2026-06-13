"""
Dashboard context processors to make data available across all templates
"""

from .project_routing import (
    get_default_project_code,
    normalize_project_code,
    project_to_slug,
)


PROJECT_RENDER_GROUPS = {
    "show_iplt_links": {"ULTRATECH"},
    "show_globaltracker_links": {"MBMT", "UMT", "NAGPUR"},
}





def project_spv_context(request):
    """
    Context processor to inject selected project and its SPV list into all templates.
    VALIDATES PROJECT ACCESS using RBAC before allowing project selection.
    
    Makes available:
    - {{ selected_project }}: Currently selected project name (only if user has access)
    - {{ project_spv_list }}: List of SPVs for the selected project
    - {{ all_projects }}: List of all available projects
    """
    from .vendor_spv_list import VENDOR_SPV_LIST
    from .services.rbacService import RBACService

    # Start with session/default, ignoring URL for now
    selected_project = (
        normalize_project_code(request.session.get("selected_project"))
        or get_default_project_code()
    )

    # NOW check if the URL is trying to override with a different project
    url_project = getattr(request, "project_code", None)
    if url_project and url_project != selected_project:
        # User is trying to switch projects via URL
        # Validate they have access to the URL project
        if request.user.is_authenticated and not request.user.is_superuser:
            if not RBACService.can_access_project_url(request.user, url_project):
                # Unauthorized attempt to access URL project
                print(f"[RBAC BLOCK] User {request.user.username} tried to access unauthorized project via URL: {url_project}")
                # Keep current project, don't allow the switch
            else:
                # User has access to URL project, allow the switch
                selected_project = url_project
        elif request.user.is_superuser:
            # Superusers can access any project
            selected_project = url_project
    elif not url_project and request.user.is_authenticated and not request.user.is_superuser:
        # No URL project specified, validate session project with RBAC
        if not RBACService.can_access_project_url(request.user, selected_project):
            print(f"[RBAC] User {request.user.username} tried to access unauthorized project: {selected_project}")
            selected_project = get_default_project_code()

    # Validate that selected project exists in the mapping
    if selected_project not in VENDOR_SPV_LIST:
        selected_project = get_default_project_code()

    request.session["selected_project"] = selected_project

    # Get SPV list for selected project
    spv_list = VENDOR_SPV_LIST.get(selected_project, [])
    project_slug = project_to_slug(selected_project)
    project_render_flags = {
        flag_name: selected_project in project_codes
        for flag_name, project_codes in PROJECT_RENDER_GROUPS.items()
    }

    return {
        "selected_project": selected_project,
        "selected_project_slug": project_slug,
        "project_url_prefix": f"/{project_slug}",
        "project_spv_list": spv_list,
        "all_projects": list(VENDOR_SPV_LIST.keys()),
        "project_render_flags": project_render_flags,
        **project_render_flags,
    }

    # Get SPV list for selected project
    spv_list = VENDOR_SPV_LIST.get(selected_project, [])
    project_slug = project_to_slug(selected_project)
    project_render_flags = {
        flag_name: selected_project in project_codes
        for flag_name, project_codes in PROJECT_RENDER_GROUPS.items()
    }

    return {
        "selected_project": selected_project,
        "selected_project_slug": project_slug,
        "project_url_prefix": f"/{project_slug}",
        "project_spv_list": spv_list,
        "all_projects": list(VENDOR_SPV_LIST.keys()),
        "project_render_flags": project_render_flags,
        **project_render_flags,
    }


def rbac_context(request):
    """
    Context processor to inject RBAC data based on user's group and selected project.
    Provides current user's group and the group's affiliated projects and pages.

    Makes available:
    - {{ user_group }}: Current user's assigned group
    - {{ user_projects }}: List of projects accessible to user's group
    - {{ user_project_ids }}: List of project IDs accessible to user's group
    - {{ user_pages }}: List of pages accessible to user's group
    - {{ user_page_codes }}: Set of page codes accessible to user's group (across all projects)
    - {{ selected_project_pages }}: List of pages accessible for the currently selected project
    - {{ selected_project_page_codes }}: Set of page codes for currently selected project (for sidebar)
    """
    if not request.user.is_authenticated:
        return {
            "user_group": None,
            "user_projects": [],
            "user_project_ids": [],
            "user_pages": [],
            "user_page_codes": set(),
            "selected_project_page_codes": set(),
        }

    try:
        # Get user's profile and group
        user_profile = request.user.profile
        user_group = user_profile.group
        
        if not user_group:
            # User not assigned to any group
            return {
                "user_group": None,
                "user_projects": [],
                "user_project_ids": [],
                "user_pages": [],
                "user_page_codes": set(),
                "selected_project_page_codes": set(),
            }
        
        # Get group access configuration
        from .models import GroupAccess
        
        group_access = GroupAccess.objects.filter(group=user_group).first()
        
        if not group_access:
            # Group exists but no access configuration
            return {
                "user_group": user_group,
                "user_projects": [],
                "user_project_ids": [],
                "user_pages": [],
                "user_page_codes": set(),
                "selected_project_page_codes": set(),
            }
        
        # Get projects and pages from group access
        user_projects = group_access.projects.all()
        user_pages = group_access.pages.all()
        
        # Extract IDs and codes for easy template checks
        user_project_ids = list(user_projects.values_list('id', flat=True))
        user_page_codes = set(user_pages.values_list('code', flat=True))
        
        # Get currently selected project and its page codes
        from .project_routing import normalize_project_code, get_default_project_code
        selected_project_code = (
            getattr(request, "project_code", None)
            or normalize_project_code(request.session.get("selected_project"))
            or get_default_project_code()
        )
        
        # Create list of accessible project codes/names for easy template checking
        user_project_codes = [p.name for p in user_projects]
        
        # Verify selected project is in user's accessible projects
        # If not, it means the project_spv_context already reset it, but double-check for safety
        if selected_project_code not in user_project_codes:
            selected_project_code = get_default_project_code()
        
        # For now, show all page codes for selected project
        # In future, this can be made project-specific if needed
        selected_project_page_codes = user_page_codes
        
        rbac_context_data = {
            "user_group": user_group,
            "user_group_name": user_group.name,
            "user_projects": user_projects,
            "user_project_ids": user_project_ids,
            "user_project_codes": user_project_codes,  # NEW: For sidebar checks
            "user_pages": user_pages,
            "user_page_codes": user_page_codes,
            "selected_project_page_codes": selected_project_page_codes,
            "selected_project": selected_project_code,
        }
        
        # Print RBAC context for debugging
        # print("\n" + "="*80)
        # print("RBAC CONTEXT")
        # print("="*80)
        # print(f"User: {request.user.username}")
        # print(f"User Group: {user_group.name}")
        # print(f"Selected Project: {selected_project_code}")
        # print(f"User Projects: {list(user_projects.values_list('name', flat=True))}")
        # print(f"User Page Codes: {user_page_codes}")
        # print(f"Selected Project Page Codes: {selected_project_page_codes}")
        # print("="*80 + "\n")
        
        return rbac_context_data
        
    except Exception as e:
        # If profile doesn't exist or any error occurs, return empty context
        print(f"Error in rbac_context: {e}")
        import traceback
        traceback.print_exc()
        return {
            "user_group": None,
            "user_projects": [],
            "user_project_ids": [],
            "user_pages": [],
            "user_page_codes": set(),
            "selected_project_page_codes": set(),
        }

    