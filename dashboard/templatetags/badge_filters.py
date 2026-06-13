from django import template
from datetime import datetime

register = template.Library()

@register.simple_tag
def is_new(release_date_str):
    """
    Check if feature is new (within 7 days of release date).
    
    Usage: {% is_new '2026-01-10' as show_badge %}
    
    Args:
        release_date_str: String date in format 'YYYY-MM-DD'
    
    Returns:
        Boolean: True if within 7 days, False otherwise
    """
    try:
        release_date = datetime.strptime(release_date_str, '%Y-%m-%d')
        days_since_release = (datetime.now() - release_date).days
        return 0 <= days_since_release < 7
    except (ValueError, TypeError):
        # If invalid date format, don't show badge
        return False
