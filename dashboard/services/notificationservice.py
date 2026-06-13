"""
Notification Service
Helper functions to create and manage notifications
"""

from django.contrib.auth.models import User
from ..models import Notification


def create_notification(user, title, message, notification_type="info", link=None):
    """
    Create a notification for a user

    Args:
        user: User object or user ID
        title: Notification title (max 200 chars)
        message: Notification message
        notification_type: Type of notification ('info', 'success', 'warning', 'error')
        link: Optional link URL

    Returns:
        Notification object

    Example:
        from dashboard.services.notificationservice import create_notification
        create_notification(request.user, 'Welcome!', 'Your account is ready', 'success', '/dashboard/')
    """
    if isinstance(user, int):
        user = User.objects.get(id=user)

    return Notification.create_notification(
        user=user,
        title=title,
        message=message,
        notification_type=notification_type,
        link=link,
    )


def notify_user(user, title, message, notification_type="info", link=None):
    """Alias for create_notification"""
    return create_notification(user, title, message, notification_type, link)


def notify_multiple_users(users, title, message, notification_type="info", link=None):
    """
    Create the same notification for multiple users

    Args:
        users: List of User objects or user IDs
        title, message, notification_type, link: Same as create_notification

    Returns:
        List of created Notification objects

    Example:
        from dashboard.services.notificationservice import notify_multiple_users
        notify_multiple_users([user1, user2], 'Update', 'System maintenance scheduled')
    """
    notifications = []
    for user in users:
        notifications.append(
            create_notification(user, title, message, notification_type, link)
        )
    return notifications


def notify_all_users(title, message, notification_type="info", link=None):
    """
    Create a notification for all active users

    Example:
        from dashboard.services.notificationservice import notify_all_users
        notify_all_users('Maintenance', 'System will be down at 3 AM', 'warning')
    """
    users = User.objects.filter(is_active=True)
    return notify_multiple_users(users, title, message, notification_type, link)


def clear_user_notifications(user, mark_read=False):
    """
    Clear all notifications for a user

    Args:
        user: User object
        mark_read: If True, mark as read instead of deleting
    """
    if mark_read:
        return Notification.objects.filter(user=user).update(is_read=True)
    else:
        return Notification.objects.filter(user=user).delete()
