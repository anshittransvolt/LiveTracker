"""
Vehicle Number Mapping Utility
================================
Maps trolley numbers to truck numbers for display purposes.

IMPORTANT: 
- Some vehicles report their trolley number instead of truck number
- This module provides bidirectional mapping (trolley -> truck and truck -> trolley)
- All display logic should use get_display_vehicle_number() to show truck numbers
- All API calls should use get_api_vehicle_number() to use the actual number from the system

Usage:
    from livetracker.vehicle_mapping import get_display_vehicle_number, get_api_vehicle_number
    
    # Display on UI (converts trolley to truck if needed)
    display_number = get_display_vehicle_number("MH18BZ2653")  # Returns "MH18BZ2647"
    
    # For API calls (keeps original number)
    api_number = get_api_vehicle_number("MH18BZ2647")  # Returns actual number in system
"""

# Mapping: Truck Number -> Trolley Number
TRUCK_TO_TROLLEY_MAPPING = {
    "MH18BZ2647": "MH18BZ2653",
    "MH18BZ2648": "MH18BZ2654",
    "MH18BZ2649": "MH18BZ2652",
    "MH18BZ2689": "MH18BZ2694",
    "MH18BZ2690": "MH18BZ2693",
    "MH18BZ2958": "MH18BZ2974",
    "MH18BZ2960": "MH18BZ2971",
    "MH18BZ2961": "MH18BZ2972",
    "MH18BZ2962": "MH18BZ2970",
    "MH18BZ2963": "MH18BZ2975",
    "MH18BZ2968": "MH18BZ2973",
    "MH18BZ2872": "MH18BZ3015",
    "MH18BZ2869": "MH18BZ3095",
    "MH18BZ2871": "MH18BZ3014",
    "MH18BZ3028": "MH18BZ3027",
    "MH18BZ3038": "MH18BZ3094",
    "MH18BZ3036": "MH18BZ3096",
    "MH18BZ3034": "MH18BZ3098",
    "MH18BZ3032": "MH18BZ3097",
    "MH18BZ2874": "MH18BZ2874",  # Same
    "MH18BZ2873": "MH18BZ2873",  # Same
    "MH18BZ3029": "MH18BZ3029",  # Same
    "MH18BZ3024": "MH18BZ3024",  # Same
    "MH18BZ3110": "MH18BZ3110",  # Same
    "MH18BZ3108": "MH18BZ3108",  # Same
    "MH18BZ3039": "MH18BZ3039",  # Same
    "MH18BZ3109": "MH18BZ3109",  # Same
    "MH18BZ3112": "MH18BZ3112",  # Same
    "MH18BZ3162": "MH18BZ3179",
    "MH18BZ3160": "MH18BZ3178",
    "MH18BZ3163": "MH18BZ3176",
    "MH18BZ3164": "MH18BZ3177",
    "MH18BZ3113": "MH18BZ3172",
    "MH18BZ3161": "MH18BZ3174",
    "MH18BZ3165": "MH18BZ3173",
    "MH18BZ3194": "MH18BZ3328",
    "MH18BZ3198": "MH18BZ3332",
    "MH18BZ3201": "MH18BZ3356",
    "MH18BZ3195": "MH18BZ3338",
    "MH18BZ3196": "MH18BZ3329",
    "MH18BZ3341": "MH18BZ3351",
    "MH18BZ3344": "MH18BZ3350",
    "MH18BZ3345": "MH18BZ3324",
    "MH18BZ3342": "MH18BZ3352",
    "MH18BZ3346": "MH18BZ3354",
    "MH18BZ3343": "MH18BZ3325",
    "MH18BZ3347": "MH18BZ3327",
    "MH18BZ3387": "MH18BZ3385",
    "MH18BZ3390": "MH18BZ3484",
    "MH18BZ3381": "MH18BZ3478",
    "MH18BZ3383": "MH18BZ3475",
    "MH18BZ3380": "MH18BZ3480",
    "MH18BZ3375": "MH18BZ3483",
    "MH18BZ3386": "MH18BZ3486",
    "MH18BZ3389": "MH18BZ3490",
    "MH18BZ3376": "MH18BZ3497",
    "MH18BZ3501": "MH18BZ3496",
    "MH18BZ3476": "MH18BZ3482",
    "MH18BZ3426": "MH18BZ3485",
    "MH18BZ3372": "MH18BZ3513",
    "MH18BZ3392": "MH18BZ3514",
    "MH18BZ3378": "MH18BZ3517",
    "MH18BZ3391": "MH18BZ3519",
    "MH18BZ3384": "MH18BZ3518",
    "MH18BZ3370": "MH18BZ3511",
    "HR55AY9178": "HR55AY9178",  # Same
    "MH18BZ3374": "MH18BZ3512",
    "MH18BZ3382": "MH18BZ3547",
    "MH18BZ3368": "MH18BZ3544",
    "MH18BZ3379": "MH18BZ3379",  # Same
    "MH18BZ3369": "MH18BZ3369",  # Same
}

# Reverse mapping: Trolley Number -> Truck Number (auto-generated)
TROLLEY_TO_TRUCK_MAPPING = {trolley: truck for truck, trolley in TRUCK_TO_TROLLEY_MAPPING.items()}


def normalize_vehicle_number(vehicle_no):
    """
    Normalize vehicle number by removing spaces and converting to uppercase.
    
    Args:
        vehicle_no: Vehicle number string (may contain spaces)
        
    Returns:
        Normalized vehicle number without spaces, uppercase
    """
    if not vehicle_no:
        return vehicle_no
    return str(vehicle_no).replace(" ", "").upper()


def get_display_vehicle_number(vehicle_no):
    """
    Get the truck number to display on UI.
    If a trolley number is provided, returns the corresponding truck number.
    If a truck number or unmapped number is provided, returns it as-is.
    
    Args:
        vehicle_no: Vehicle number from API (could be truck or trolley number)
        
    Returns:
        Truck number for display purposes
        
    Examples:
        >>> get_display_vehicle_number("MH18BZ2653")  # Trolley
        'MH18BZ2647'  # Returns truck
        
        >>> get_display_vehicle_number("MH18BZ2647")  # Already truck
        'MH18BZ2647'
        
        >>> get_display_vehicle_number("MH 18 BZ 2653")  # With spaces
        'MH18BZ2647'
    """
    if not vehicle_no:
        return vehicle_no
    
    # Normalize the input
    normalized = normalize_vehicle_number(vehicle_no)
    
    # Check if it's a trolley number, return corresponding truck
    if normalized in TROLLEY_TO_TRUCK_MAPPING:
        truck_number = TROLLEY_TO_TRUCK_MAPPING[normalized]
        return truck_number
    
    # If it's already a truck number or unmapped, return as-is
    return normalized


def get_api_vehicle_number(vehicle_no):
    """
    Get the actual vehicle number to use for API calls.
    This checks if the vehicle number exists as a truck or trolley in our mapping.
    
    Args:
        vehicle_no: Display vehicle number (truck number)
        
    Returns:
        Actual vehicle number in the system (could be trolley if that's what API uses)
        
    Examples:
        >>> get_api_vehicle_number("MH18BZ2647")  # Truck
        'MH18BZ2653'  # Returns trolley if that's what system uses
    """
    if not vehicle_no:
        return vehicle_no
    
    # Normalize the input
    normalized = normalize_vehicle_number(vehicle_no)
    
    # If it's a truck number and has a trolley mapping, return the trolley
    # (This assumes the API uses trolley numbers for these vehicles)
    if normalized in TRUCK_TO_TROLLEY_MAPPING:
        trolley_number = TRUCK_TO_TROLLEY_MAPPING[normalized]
        # If trolley is different from truck, that's what the API uses
        if trolley_number != normalized:
            return trolley_number
    
    # Otherwise, return the normalized number
    return normalized


def is_mapped_vehicle(vehicle_no):
    """
    Check if a vehicle number exists in our mapping (either as truck or trolley).
    
    Args:
        vehicle_no: Vehicle number to check
        
    Returns:
        True if vehicle is in mapping, False otherwise
    """
    if not vehicle_no:
        return False
    
    normalized = normalize_vehicle_number(vehicle_no)
    return normalized in TRUCK_TO_TROLLEY_MAPPING or normalized in TROLLEY_TO_TRUCK_MAPPING


def get_vehicle_mapping_info(vehicle_no):
    """
    Get complete mapping information for a vehicle.
    
    Args:
        vehicle_no: Vehicle number to look up
        
    Returns:
        Dictionary with mapping info:
        {
            'input': original input,
            'normalized': normalized input,
            'truck_number': truck number,
            'trolley_number': trolley number,
            'is_mapped': whether vehicle is in mapping,
            'display_number': number to show on UI,
            'api_number': number to use for API calls
        }
    """
    normalized = normalize_vehicle_number(vehicle_no) if vehicle_no else None
    
    if not normalized:
        return {
            'input': vehicle_no,
            'normalized': None,
            'truck_number': None,
            'trolley_number': None,
            'is_mapped': False,
            'display_number': vehicle_no,
            'api_number': vehicle_no
        }
    
    # Check if it's a trolley
    if normalized in TROLLEY_TO_TRUCK_MAPPING:
        truck = TROLLEY_TO_TRUCK_MAPPING[normalized]
        trolley = normalized
    # Check if it's a truck
    elif normalized in TRUCK_TO_TROLLEY_MAPPING:
        truck = normalized
        trolley = TRUCK_TO_TROLLEY_MAPPING[normalized]
    else:
        # Unmapped vehicle
        return {
            'input': vehicle_no,
            'normalized': normalized,
            'truck_number': normalized,
            'trolley_number': normalized,
            'is_mapped': False,
            'display_number': normalized,
            'api_number': normalized
        }
    
    return {
        'input': vehicle_no,
        'normalized': normalized,
        'truck_number': truck,
        'trolley_number': trolley,
        'is_mapped': True,
        'display_number': truck,  # Always display truck number
        'api_number': trolley if trolley != truck else truck  # Use trolley if different
    }
