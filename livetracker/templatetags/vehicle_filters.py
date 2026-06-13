"""
Vehicle Mapping Template Tags
==============================
Custom template filters and tags for vehicle number mapping.

Usage in templates:
    {% load vehicle_filters %}
    
    {{ vehicle_no|display_vehicle_number }}
    {{ "MH18BZ2653"|display_vehicle_number }}  {# Shows MH18BZ2647 #}
"""

from django import template
from livetracker.vehicle_mapping import (
    get_display_vehicle_number,
    get_api_vehicle_number,
    get_vehicle_mapping_info,
    is_mapped_vehicle,
    normalize_vehicle_number
)

register = template.Library()


@register.filter(name='display_vehicle_number')
def display_vehicle_number(value):
    """
    Template filter to convert trolley numbers to truck numbers for display.
    
    Usage:
        {{ vehicle_no|display_vehicle_number }}
        {{ "MH18BZ2653"|display_vehicle_number }}  {# Returns "MH18BZ2647" #}
    """
    return get_display_vehicle_number(value)


@register.filter(name='api_vehicle_number')
def api_vehicle_number(value):
    """
    Template filter to get the actual API vehicle number.
    
    Usage:
        {{ vehicle_no|api_vehicle_number }}
    """
    return get_api_vehicle_number(value)


@register.filter(name='normalize_vehicle_number')
def normalize_vehicle_filter(value):
    """
    Template filter to normalize vehicle numbers (remove spaces, uppercase).
    
    Usage:
        {{ "MH 18 BZ 2647"|normalize_vehicle_number }}  {# Returns "MH18BZ2647" #}
    """
    return normalize_vehicle_number(value)


@register.filter(name='is_mapped')
def is_mapped_filter(value):
    """
    Template filter to check if a vehicle is in the mapping.
    
    Usage:
        {% if vehicle_no|is_mapped %}
            This vehicle has truck/trolley mapping
        {% endif %}
    """
    return is_mapped_vehicle(value)


@register.simple_tag
def vehicle_mapping_info(vehicle_no):
    """
    Template tag to get complete mapping information.
    
    Usage:
        {% vehicle_mapping_info "MH18BZ2653" as info %}
        Truck: {{ info.truck_number }}
        Trolley: {{ info.trolley_number }}
        Display: {{ info.display_number }}
    """
    return get_vehicle_mapping_info(vehicle_no)
