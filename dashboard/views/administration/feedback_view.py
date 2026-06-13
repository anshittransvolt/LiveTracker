from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from livetracker.models.livetracker_feedback import Feedback
from django.db.models import Q, Count


def is_admin(user):
    """Check if user is superuser"""
    return user.is_superuser


@login_required
@user_passes_test(is_admin)
def admin_feedback_list(request):
    """
    Admin view to see all feedback submissions from all users
    with filtering and sorting capabilities
    """
    # Get filter parameters
    status_filter = request.GET.get('status', 'all')
    type_filter = request.GET.get('type', 'all')
    search_query = request.GET.get('search', '')
    
    # Base queryset with related user data
    feedbacks = Feedback.objects.select_related('reported_by').all()
    
    # Apply filters
    if status_filter != 'all':
        feedbacks = feedbacks.filter(status=status_filter)
    
    if type_filter != 'all':
        feedbacks = feedbacks.filter(feedback_type=type_filter)
    
    # Apply search
    if search_query:
        feedbacks = feedbacks.filter(
            Q(title__icontains=search_query) |
            Q(description__icontains=search_query) |
            Q(reported_by__username__icontains=search_query) |
            Q(reported_by__email__icontains=search_query)
        )
    
    # Get statistics
    stats = {
        'total': Feedback.objects.count(),
        'open': Feedback.objects.filter(status='open').count(),
        'working': Feedback.objects.filter(status='working').count(),
        'closed': Feedback.objects.filter(status='closed').count(),
        'bugs': Feedback.objects.filter(feedback_type='bug').count(),
        'features': Feedback.objects.filter(feedback_type='feature').count(),
    }
    
    context = {
        'feedbacks': feedbacks.order_by('-created_at'),
        'stats': stats,
        'status_filter': status_filter,
        'type_filter': type_filter,
        'search_query': search_query,
    }
    
    return render(request, 'dashboard/administration/admin_feedback_view.html', context)


@login_required
@user_passes_test(is_admin)
@require_http_methods(["POST"])
def admin_update_feedback_status(request, feedback_id):
    """
    Admin endpoint to update feedback status
    """
    feedback = get_object_or_404(Feedback, id=feedback_id)
    new_status = request.POST.get('status')
    
    if new_status in ['open', 'working', 'closed']:
        feedback.status = new_status
        feedback.save()
        messages.success(request, f'Feedback status updated to {new_status.title()}')
    else:
        messages.error(request, 'Invalid status')
    
    return redirect('dashboard:admin_feedback_list')


@login_required
@user_passes_test(is_admin)
@require_http_methods(["POST"])
def admin_delete_feedback(request, feedback_id):
    """
    Admin endpoint to delete feedback
    """
    feedback = get_object_or_404(Feedback, id=feedback_id)
    feedback.delete()
    messages.success(request, 'Feedback deleted successfully')
    
    return redirect('dashboard:admin_feedback_list')
