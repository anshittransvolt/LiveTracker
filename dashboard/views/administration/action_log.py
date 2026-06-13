from django.shortcuts import render, get_object_or_404
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from dashboard.models.user_action_log import UserActionLog
from datetime import timedelta


@login_required
@require_http_methods(["GET"])
def user_action_log(request, user_id):
    """
    Display action logs for a specific user with filtering options and pagination
    """
    # Get the user
    target_user = get_object_or_404(User, pk=user_id)
    
    # Get filter parameters - default to 'today' to show today's logs
    period = request.GET.get('period', 'today')
    search_query = request.GET.get('search', '').strip()
    section_filter = request.GET.get('section', 'all')
    page_num = request.GET.get('page', 1)
    
    # Base queryset
    queryset = UserActionLog.objects.filter(user=target_user)
    
    # Date filtering
    now = timezone.now()
    today_start = timezone.make_aware(
        timezone.datetime(now.year, now.month, now.day, 0, 0, 0)
    )
    today_end = today_start + timedelta(days=1)
    
    if period == 'today':
        queryset = queryset.filter(created_at__gte=today_start, created_at__lt=today_end)
    elif period == 'yesterday':
        yesterday_start = today_start - timedelta(days=1)
        yesterday_end = today_start
        queryset = queryset.filter(created_at__gte=yesterday_start, created_at__lt=yesterday_end)
    elif period == 'week':
        week_ago = today_start - timedelta(days=7)
        queryset = queryset.filter(created_at__gte=week_ago)
    elif period == 'month':
        month_ago = today_start - timedelta(days=30)
        queryset = queryset.filter(created_at__gte=month_ago)
    # If period == 'all', no date filter is applied
    
    # Search filtering
    if search_query:
        queryset = queryset.filter(
            action__icontains=search_query
        ) | queryset.filter(
            path__icontains=search_query
        ) | queryset.filter(
            section__icontains=search_query
        )
    
    # Section filtering
    if section_filter != 'all':
        queryset = queryset.filter(section=section_filter)
    
    # Get unique sections for filter dropdown
    sections = UserActionLog.objects.filter(user=target_user).values_list(
        'section', flat=True
    ).distinct().order_by('section')
    
    # Count statistics
    total_logs = UserActionLog.objects.filter(user=target_user).count()
    filtered_logs = queryset.count()
    
    # Order by most recent first
    queryset = queryset.order_by('-created_at')
    
    # Pagination - 25 items per page
    paginator = Paginator(queryset, 25)
    
    try:
        logs = paginator.page(page_num)
    except PageNotAnInteger:
        logs = paginator.page(1)
    except EmptyPage:
        logs = paginator.page(paginator.num_pages)
    
    context = {
        'target_user': target_user,
        'logs': logs,
        'total_logs': total_logs,
        'filtered_logs': filtered_logs,
        'period': period,
        'search_query': search_query,
        'section_filter': section_filter,
        'sections': sections,
        'paginator': paginator,
    }
    
    return render(request, 'dashboard/administration/action_log.html', context)
