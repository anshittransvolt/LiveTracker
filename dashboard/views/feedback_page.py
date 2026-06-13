from livetracker.models.livetracker_feedback import Feedback
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.shortcuts import render, redirect
from django.contrib import messages

__all__ = ['view_feedback', 'update_feedback_status']

@login_required
@require_http_methods(["GET"])
def view_feedback(request):
    """Display user's submitted feedback with status and type"""
    
    # Get all feedback submitted by current user, ordered by newest first
    user_feedback = Feedback.objects.filter(reported_by=request.user).order_by('-created_at')
    
    context = {
        'feedbacks': user_feedback,
        'total_count': user_feedback.count(),
        'open_count': user_feedback.filter(status='open').count(),
        'working_count': user_feedback.filter(status='working').count(),
        'closed_count': user_feedback.filter(status='closed').count(),
        'bug_count': user_feedback.filter(feedback_type='bug').count(),
        'feature_count': user_feedback.filter(feedback_type='feature').count(),
    }
    
    return render(request, 'dashboard/base/feedback_page.html', context)


@login_required
@require_http_methods(["POST"])
def update_feedback_status(request, feedback_id):
    """Update feedback status - Admin only"""
    
    # Check if user is admin
    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, 'Permission denied')
        return redirect('dashboard:view_feedback')
    
    try:
        feedback = Feedback.objects.get(id=feedback_id)
        new_status = request.POST.get('status')
        
        if new_status in ['open', 'working', 'closed']:
            feedback.status = new_status
            feedback.save()
            messages.success(request, 'Status updated successfully')
        else:
            messages.error(request, 'Invalid status')
            
    except Feedback.DoesNotExist:
        messages.error(request, 'Feedback not found')
    
    return redirect('dashboard:view_feedback')