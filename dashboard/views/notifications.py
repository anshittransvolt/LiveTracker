from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.utils.timesince import timesince
from ..models import Notification


@login_required
@require_http_methods(["GET"])
def get_notifications(request):
    """
    API endpoint to fetch user notifications
    Returns JSON with notification data
    """
    notifications = Notification.objects.filter(user=request.user)[:20]  # Get latest 20

    data = {
        "notifications": [
            {
                "id": n.id,
                "title": n.title,
                "message": n.message,
                "type": n.notification_type,
                "link": n.link or "#",
                "is_read": n.is_read,
                "timestamp": timesince(n.created_at) + " ago",
                "created_at": n.created_at.isoformat(),
            }
            for n in notifications
        ],
        "unread_count": Notification.objects.filter(
            user=request.user, is_read=False
        ).count(),
    }

    return JsonResponse(data)


@login_required
@require_http_methods(["POST"])
def mark_notification_read(request, notification_id):
    """
    Mark a specific notification as read
    """
    try:
        notification = Notification.objects.get(id=notification_id, user=request.user)
        notification.mark_as_read()
        return JsonResponse({"success": True, "message": "Notification marked as read"})
    except Notification.DoesNotExist:
        return JsonResponse(
            {"success": False, "message": "Notification not found"}, status=404
        )


@login_required
@require_http_methods(["POST"])
def mark_all_read(request):
    """
    Mark all user notifications as read
    """
    updated = Notification.objects.filter(user=request.user, is_read=False).update(
        is_read=True
    )
    return JsonResponse(
        {
            "success": True,
            "message": f"{updated} notification(s) marked as read",
            "count": updated,
        }
    )
