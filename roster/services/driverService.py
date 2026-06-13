"""
Driver Service - Fast driver lookup with intelligent caching
"""
from django.core.cache import cache
from roster.models import HorseTrolleyAssignment

# Cache driver assignments for 10 minutes (updates are rare)
DRIVER_CACHE_TIMEOUT = 600


def get_driver_by_vehicle(registration_number):
    """
    Get driver details for a vehicle registration number.
    Uses aggressive caching since driver assignments change infrequently.
    
    Args:
        registration_number (str): Vehicle registration number (horse_number)
    
    Returns:
        dict: {
            'driver_name': str,
            'driver_phone': str,
            'driver_code': str,
            'has_driver': bool
        }
    """
    # Check cache first
    cache_key = f"driver_assignment_{registration_number}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    
    # Query database with optimized select
    try:
        assignment = HorseTrolleyAssignment.objects.select_related('driver').only(
            'driver__employee_name',
            'driver__phone',
            'driver__employee_code'
        ).filter(horse=registration_number).first()
        
        if assignment and assignment.driver:
            result = {
                'driver_name': assignment.driver.employee_name or 'Unknown',
                'driver_phone': assignment.driver.phone or 'N/A',
                'driver_code': assignment.driver.employee_code,
                'has_driver': True
            }
        else:
            result = {
                'driver_name': 'Not Assigned',
                'driver_phone': 'N/A',
                'driver_code': None,
                'has_driver': False
            }
        
        # Cache for 10 minutes
        cache.set(cache_key, result, DRIVER_CACHE_TIMEOUT)
        return result
        
    except Exception as e:
        # Fallback on error
        return {
            'driver_name': 'Error',
            'driver_phone': 'N/A',
            'driver_code': None,
            'has_driver': False
        }


def clear_driver_cache(registration_number):
    """
    Clear cached driver info for a vehicle.
    Call this after assigning/unassigning a driver.
    """
    cache_key = f"driver_assignment_{registration_number}"
    cache.delete(cache_key)


def get_all_drivers_bulk(registration_numbers):
    """
    Get driver details for multiple vehicles at once.
    More efficient than calling get_driver_by_vehicle() in a loop.
    
    Args:
        registration_numbers (list): List of vehicle registration numbers
    
    Returns:
        dict: {registration_number: driver_info_dict}
    """
    # Try to get all from cache first
    result = {}
    uncached_vehicles = []
    
    for reg_num in registration_numbers:
        cache_key = f"driver_assignment_{reg_num}"
        cached = cache.get(cache_key)
        if cached is not None:
            result[reg_num] = cached
        else:
            uncached_vehicles.append(reg_num)
    
    # Fetch uncached ones from DB in one query
    if uncached_vehicles:
        assignments = HorseTrolleyAssignment.objects.select_related('driver').filter(
            horse__in=uncached_vehicles
        ).only(
            'horse',
            'driver__employee_name',
            'driver__phone',
            'driver__employee_code'
        )
        
        # Create a map of vehicle -> driver info
        assignment_map = {}
        for assignment in assignments:
            if assignment.driver:
                driver_info = {
                    'driver_name': assignment.driver.employee_name or 'Unknown',
                    'driver_phone': assignment.driver.phone or 'N/A',
                    'driver_code': assignment.driver.employee_code,
                    'has_driver': True
                }
                assignment_map[assignment.horse.horse_number] = driver_info
                
                # Cache it
                cache_key = f"driver_assignment_{assignment.horse.horse_number}"
                cache.set(cache_key, driver_info, DRIVER_CACHE_TIMEOUT)
        
        # Fill in remaining vehicles with "Not Assigned"
        for reg_num in uncached_vehicles:
            if reg_num in assignment_map:
                result[reg_num] = assignment_map[reg_num]
            else:
                no_driver = {
                    'driver_name': 'Not Assigned',
                    'driver_phone': 'N/A',
                    'driver_code': None,
                    'has_driver': False
                }
                result[reg_num] = no_driver
                
                # Cache the "not assigned" state too
                cache_key = f"driver_assignment_{reg_num}"
                cache.set(cache_key, no_driver, DRIVER_CACHE_TIMEOUT)
    
    return result
