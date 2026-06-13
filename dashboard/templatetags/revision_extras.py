from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter(is_safe=False)
def bullet_list(value):
    """Convert newline-separated description text into a safe HTML unordered list.

    - Empty lines are ignored.
    - Lines are HTML-escaped.
    - Returns safe HTML string containing a <ul class="list-disc pl-6">...
    """
    if not value:
        return ""

    try:
        lines = [line.strip() for line in str(value).splitlines() if line.strip()]
    except Exception:
        return escape(value)

    if not lines:
        return escape(value)

    items = "".join(f"<li>{escape(line)}</li>" for line in lines)
    return mark_safe(f'<ul class="list-disc pl-6">{items}</ul>')
