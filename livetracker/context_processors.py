# livetracker/context_processors.py
from django.conf import settings
from .vehicle_mapping import get_display_vehicle_number


def environment_variables(request):
    """
    Context processor to inject environment variables into all templates.
    Makes API configuration variables available to JavaScript via window.ENV.
    """
    return {
        # SECURITY FIX: All external API URLs and credentials removed
        # All API calls now go through Django backend proxies - no client-side exposure needed
    }


def vehicle_mapping(request):
    """
    Context processor to make vehicle mapping functions available in all templates.
    Provides get_display_vehicle_number function to convert trolley numbers to truck numbers.
    """
    return {
        "get_display_vehicle_number": get_display_vehicle_number,
    }


def selected_project_context(request):
    """
    Minimal replacement for dashboard's project_spv_context: exposes the
    currently selected project to templates/JS without any RBAC/session
    validation (project access is expected to be enforced upstream by the
    external auth/JWT system, not this app).
    """
    selected_project = (request.GET.get('spv') or 'ULTRATECH').strip().upper()
    return {
        "selected_project": selected_project,
        "show_iplt_links": selected_project == 'ULTRATECH',
    }
