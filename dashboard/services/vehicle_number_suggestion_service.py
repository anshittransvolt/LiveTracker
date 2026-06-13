from django.db.models import Q
from ..models import Vehicle


class VehicleNumberSuggestionService:
    """Service to provide vehicle registration number suggestions based on project and search query"""
    
    @staticmethod
    def get_suggestions(search_query, project_name, limit=10):
        """
        Get vehicle registration number suggestions based on search query and project.
        Optimized for speed: prioritizes prefix matches, then includes contains matches.
        
        Args:
            search_query (str): Partial registration number to search for (searches anywhere in the number)
            project_name (str): Active project name to filter vehicles
            limit (int): Maximum number of suggestions to return (default: 10)
            
        Returns:
            list: List of registration numbers matching the criteria
        """
        if not search_query or not project_name:
            return []
        
        search_query = search_query.strip().upper()
        
        # Hybrid approach: prefix matches (fast with index) + contains matches
        # 1. First try prefix matches (uses database index, very fast)
        prefix_vehicles = Vehicle.objects.filter(
            project_name=project_name,
            registration_number__istartswith=search_query
        ).values_list('registration_number', flat=True)[:limit]
        
        prefix_list = list(prefix_vehicles)
        
        # If we have enough results from prefix, return them
        if len(prefix_list) >= limit:
            return prefix_list
        
        # Otherwise, supplement with contains matches (excluding already found prefixes)
        remaining_limit = limit - len(prefix_list)
        contains_vehicles = Vehicle.objects.filter(
            project_name=project_name,
            registration_number__icontains=search_query
        ).exclude(
            registration_number__in=prefix_list
        ).values_list('registration_number', flat=True)[:remaining_limit]
        
        return prefix_list + list(contains_vehicles)
    
    @staticmethod
    def get_all_project_vehicles(project_name):
        """
        Get all vehicle registration numbers for a specific project.
        Useful for initial dropdown population or admin purposes.
        
        Args:
            project_name (str): Active project name
            
        Returns:
            list: All registration numbers for the project
        """
        if not project_name:
            return []
        
        vehicles = Vehicle.objects.filter(
            project_name=project_name
        ).values_list('registration_number', flat=True).distinct()
        
        return list(vehicles)
    
    @staticmethod
    def validate_vehicle_exists(registration_number, project_name):
        """
        Validate if a vehicle exists in the active project.
        
        Args:
            registration_number (str): Vehicle registration number
            project_name (str): Active project name
            
        Returns:
            bool: True if vehicle exists in project, False otherwise
        """
        if not registration_number or not project_name:
            return False
        
        return Vehicle.objects.filter(
            registration_number=registration_number.upper(),
            project_name=project_name
        ).exists()
