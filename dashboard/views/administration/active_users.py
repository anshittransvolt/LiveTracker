from django.shortcuts import render
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.utils import timezone
from django.db.models import Min, Q, F
from datetime import datetime, time
from dashboard.models.user_action_log import UserActionLog


def is_superuser(user):
    return user.is_superuser


@login_required
@user_passes_test(is_superuser)
def active_users(request):
    """
    Display all active users with their login information.
    Shows users who have activity logs today as active, otherwise shows last login.
    Only accessible to superusers/admins.
    """
    # Get today's date range
    today_start = datetime.combine(timezone.now().date(), time.min)
    today_start = timezone.make_aware(today_start)
    today_end = datetime.combine(timezone.now().date(), time.max)
    today_end = timezone.make_aware(today_end)
    
    # Get all active users
    users = User.objects.filter(is_active=True)
    
    # Annotate with first log entry time for today
    users = users.annotate(
        first_log_today=Min(
            'action_logs__created_at',
            filter=Q(
                action_logs__created_at__gte=today_start,
                action_logs__created_at__lte=today_end
            )
        )
    )
    
    # Order by: users with logs today first (by first log time), then by last login
    users = users.order_by(
        F('first_log_today').desc(nulls_last=True),
        F('last_login').desc(nulls_last=True)
    )
    
    context = {
        'users': users,
        'current_time': timezone.now(),
        'today_start': today_start,
    }
    
    return render(request, 'dashboard/administration/active_users.html', context)
