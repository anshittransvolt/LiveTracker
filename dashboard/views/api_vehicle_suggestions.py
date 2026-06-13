from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from ..services.vehicle_number_suggestion_service import VehicleNumberSuggestionService
from ..project_routing import normalize_project_code, get_default_project_code


@login_required
@require_http_methods(["GET"])
def vehicle_number_suggestions(request):
    """
    API endpoint to get vehicle registration number suggestions.
    
    Query Parameters:
        - q: Search query (partial registration number)
        - project: Project name (optional, uses active project if not provided)
        - limit: Maximum suggestions to return (default: 10)
    
    Returns:
        JSON response with list of matching registration numbers
    """
    search_query = request.GET.get('q', '').strip()
    project_name = request.GET.get('project', '').strip()
    limit = request.GET.get('limit', 10)
    
    # Try to get active project from session if not provided
    if not project_name:
        project_name = (
            normalize_project_code(request.session.get("selected_project"))
            or get_default_project_code()
        )
    
    # Validate inputs
    if not search_query:
        return JsonResponse({
            'success': False,
            'error': 'Search query (q) is required',
            'suggestions': []
        }, status=400)
    
    if not project_name:
        return JsonResponse({
            'success': False,
            'error': 'Project name is required',
            'suggestions': []
        }, status=400)
    
    try:
        limit = int(limit)
        limit = min(limit, 50)  # Cap at 50 to prevent excessive queries
    except (ValueError, TypeError):
        limit = 10
    
    try:
        suggestions = VehicleNumberSuggestionService.get_suggestions(
            search_query=search_query,
            project_name=project_name,
            limit=limit
        )
        
        return JsonResponse({
            'success': True,
            'suggestions': suggestions,
            'count': len(suggestions),
            'query': search_query,
            'project': project_name
        })
    
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e),
            'suggestions': []
        }, status=500)


@login_required
@require_http_methods(["GET"])
def validate_vehicle_number(request):
    """
    API endpoint to validate if a vehicle number exists in the active project.
    
    Query Parameters:
        - registration_number: Vehicle registration number to validate
        - project: Project name (optional, uses active project if not provided)
    
    Returns:
        JSON response with validation result
    """
    registration_number = request.GET.get('registration_number', '').strip()
    project_name = request.GET.get('project', '').strip()
    
    # Try to get active project from session if not provided
    if not project_name:
        project_name = (
            normalize_project_code(request.session.get("selected_project"))
            or get_default_project_code()
        )
    
    if not registration_number:
        return JsonResponse({
            'valid': False,
            'error': 'Registration number is required'
        }, status=400)
    
    if not project_name:
        return JsonResponse({
            'valid': False,
            'error': 'Project name is required'
        }, status=400)
    
    try:
        is_valid = VehicleNumberSuggestionService.validate_vehicle_exists(
            registration_number=registration_number,
            project_name=project_name
        )
        
        return JsonResponse({
            'valid': is_valid,
            'registration_number': registration_number.upper(),
            'project': project_name
        })
    
    except Exception as e:
        return JsonResponse({
            'valid': False,
            'error': str(e)
        }, status=500)
