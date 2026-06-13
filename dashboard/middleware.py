import time
from django.utils.deprecation import MiddlewareMixin
from dashboard.models.user_action_log import UserActionLog
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import render

from .project_routing import (
    build_project_prefixed_path,
    get_default_project_code,
    is_project_scoped_match,
    normalize_project_code,
    project_to_slug,
    strip_project_prefix,
)


class ProjectURLMiddleware(MiddlewareMixin):
    """
    Keeps project selection in sync between the URL and the session.
    Also redirects legacy unprefixed business URLs to their project-prefixed form.
    """

    def process_view(self, request, view_func, view_args, view_kwargs):
        project_from_url = normalize_project_code(view_kwargs.get("project"))

        if view_kwargs.get("project") and not project_from_url:
            raise Http404("Unknown project")

        if project_from_url:
            view_kwargs.pop("project", None)
            request.project_code = project_from_url
            request.project_slug = project_to_slug(project_from_url)
            if request.session.get("selected_project") != project_from_url:
                request.session["selected_project"] = project_from_url
            return None

        selected_project = (
            normalize_project_code(request.session.get("selected_project"))
            or get_default_project_code()
        )
        request.project_code = selected_project
        request.project_slug = project_to_slug(selected_project)

        if not is_project_scoped_match(getattr(request, "resolver_match", None)):
            return None

        target_url = build_project_prefixed_path(request.get_full_path(), selected_project)
        if target_url == request.get_full_path():
            return None

        response = HttpResponseRedirect(target_url)
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            response.status_code = 307
        return response

class UserActionLoggerMiddleware(MiddlewareMixin):
    """
    Middleware to log all authenticated user actions.
    Captures request details, timing, and response status.
    """

    # Paths to exclude from logging
    EXCLUDED_PATHS = [
        '/static/',
        '/media/',
        '/favicon.ico',
        '/admin/jsi18n/',  # Django admin i18n
    ]

    # Methods to exclude (typically exclude OPTIONS for CORS preflight)
    EXCLUDED_METHODS = ['OPTIONS']

    def process_request(self, request):
        """
        Called before the view. Store the start time.
        """
        request._action_log_start_time = time.time()
        return None

    def process_response(self, request, response):
        """
        Called after the view. Log the action if authenticated.
        """
        # Skip if no start time (shouldn't happen)
        if not hasattr(request, '_action_log_start_time'):
            return response

        # Skip excluded paths
        if any(request.path.startswith(path) for path in self.EXCLUDED_PATHS):
            return response

        # Skip excluded methods
        if request.method in self.EXCLUDED_METHODS:
            return response

        # Only log authenticated users
        if not request.user.is_authenticated:
            return response

        # Calculate duration
        duration_ms = int((time.time() - request._action_log_start_time) * 1000)

        # Get session information
        session_id = request.session.session_key or ''
        
        # Calculate session duration (time since session was created)
        session_duration = None
        if hasattr(request.session, 'get'):
            session_start = request.session.get('session_start_time')
            if session_start:
                session_duration = int(time.time() - session_start)
            else:
                # Set session start time if not present
                request.session['session_start_time'] = time.time()
                session_duration = 0

        # Get user role (you may need to adjust this based on your user model)
        role = self._get_user_role(request.user)

        # Get IP address
        ip_address = self._get_client_ip(request)

        # Determine section and action
        section, action = self._extract_section_and_action(request)

        try:
            # Create log entry (non-blocking in production, consider async)
            UserActionLog.objects.create(
                user=request.user,
                role=role,
                ip_address=ip_address,
                user_agent=request.META.get('HTTP_USER_AGENT', '')[:2000],  # Limit length
                session_id=session_id,
                section=section,
                action=action,
                path=request.path,
                method=request.method,
                response_status=response.status_code,
                duration_ms=duration_ms,
                session_duration=session_duration,
            )
        except Exception as e:
            # Don't let logging errors break the application
            # In production, you might want to log this error elsewhere
            if hasattr(request, 'user') and request.user.is_superuser:
                print(f"[UserActionLogger] Error logging action: {e}")

        return response

    def _get_client_ip(self, request):
        """
        Extract the client IP address from the request.
        Handles proxies and load balancers.
        """
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip

    def _get_user_role(self, user):
        """
        Extract user role. Adjust this based on your user model.
        Examples:
        - If using groups: user.groups.first().name
        - If using custom profile: user.profile.role
        - If using is_staff/is_superuser: check flags
        """
        if user.is_superuser:
            return 'superuser'
        elif user.is_staff:
            return 'staff'
        elif hasattr(user, 'groups') and user.groups.exists():
            return user.groups.first().name
        else:
            return 'user'

    def _extract_section_and_action(self, request):
        """
        Extract section and action from the request.
        You can customize this logic based on your URL structure.
        """
        path = strip_project_prefix(request.path).strip('/')
        path_parts = path.split('/')

        # Try to extract section from the first part of the path
        section = path_parts[0] if path_parts else 'root'
        
        # Create a readable action description
        if request.method == 'GET':
            action = f"View {section}"
        elif request.method == 'POST':
            action = f"Create/Update in {section}"
        elif request.method == 'PUT' or request.method == 'PATCH':
            action = f"Update {section}"
        elif request.method == 'DELETE':
            action = f"Delete from {section}"
        else:
            action = f"{request.method} {section}"

        # Limit lengths
        section = section[:100]
        action = action[:255]

        return section, action


class ProjectRBACMiddleware(MiddlewareMixin):
    """
    Middleware to enforce RBAC (Role-Based Access Control) for projects.
    Runs AFTER ProjectURLMiddleware to validate project access.
    Prevents URL-based cross-project access by validating project_code against RBAC.
    """
    
    # URLs that should be excluded from RBAC checks
    EXCLUDED_PATHS = [
        '/admin/',
        '/static/',
        '/media/',
        '/favicon.ico',
        '/dashboard/project/set/',
        '/dashboard/api/',
        '/login/',
        '/dashboard/logout/',
        '/dashboard/microsoft/',
    ]
    
    def process_request(self, request):
        """
        Validate project access early, BEFORE view execution.
        BLOCKS all requests to projects the user doesn't have access to.
        NO BYPASSES - APPLIES TO EVERYONE INCLUDING SUPERUSERS.
        """
        # Skip RBAC for unauthenticated users
        if not request.user.is_authenticated:
            return None

        # Skip RBAC for excluded paths
        normalized_path = strip_project_prefix(request.path)
        if any(normalized_path.startswith(path) for path in self.EXCLUDED_PATHS):
            return None

        # Get project from URL
        project_code = getattr(request, "project_code", None)
        if not project_code:
            return None

        # Validate project access using RBAC service - APPLIES TO EVERYONE
        from dashboard.services.rbacService import RBACService
        
        if not RBACService.can_access_project_url(request.user, project_code):
            # BLOCK access - no exceptions, not even for superusers
            print(f"[RBAC BLOCK] User {request.user.username} blocked from accessing project: {project_code}")
            return render(
                request,
                "dashboard/auth/access_denied_page.html",
                status=403,
            )
        
        return None
    
    def process_view(self, request, view_func, view_args, view_kwargs):
        """
        Additional validation at view level for extra security.
        NO BYPASSES - APPLIES TO EVERYONE INCLUDING SUPERUSERS.
        """
        # Skip RBAC for unauthenticated users
        if not request.user.is_authenticated:
            return None

        # Skip RBAC if resolver_match is not available yet
        if not hasattr(request, 'resolver_match') or request.resolver_match is None:
            return None

        # Get the URL name (page code)
        page_code = request.resolver_match.url_name
        
        # Skip RBAC if no page code
        if not page_code:
            return None

        # Check if user has access to this page within the selected project
        project_code = getattr(request, "project_code", None)
        if project_code:
            from dashboard.services.rbacService import RBACService
            if not RBACService.can_access_project_url(request.user, project_code):
                return render(
                    request,
                    "dashboard/auth/access_denied_page.html",
                    status=403,
                )

        return None
