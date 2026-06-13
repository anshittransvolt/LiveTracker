"""
Breadcrumb Template Tags
Simple and modular breadcrumb helpers for Django templates
"""

from django import template

register = template.Library()


@register.simple_tag
def breadcrumb(title, url=None, icon=None):
    """
    Create a breadcrumb item.

    Usage in templates:
        {% breadcrumb "Page Title" %}
        {% breadcrumb "Page Title" url_name %}
        {% breadcrumb "Page Title" url_name "icon-name" %}

    Args:
        title: The text to display for the breadcrumb
        url: Optional URL or named URL pattern (if it's the last item, url is ignored)
        icon: Optional Lucide icon name (e.g., 'truck', 'user', 'settings')

    Returns:
        Dictionary with breadcrumb data
    """
    return {"title": title, "url": url, "icon": icon}


@register.simple_tag(takes_context=True)
def get_breadcrumbs(context):
    """
    Get breadcrumbs from the template context.

    Usage:
        This is automatically available in templates through the context.
        Templates should define: {% block breadcrumbs %}...{% endblock %}
    """
    return context.get("breadcrumbs", [])
