import json
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.db.models import Avg, Q
from django.utils import timezone
from django.core.cache import cache
from django.core.paginator import Paginator
from apps.admin_panel.views.dashboard import _get_admin_from_session
from django.contrib import messages
from apps.admin_panel.models import AgentReview
from apps.admin_panel.models import AdminActivityLog

def reviews_index(request):
    admin_id = _get_admin_from_session(request)
    if not admin_id: return redirect('admin_login')
    search = request.GET.get('search', '').strip()
    status_filter = request.GET.get('status', 'all')
    rating_filter = request.GET.get('rating', 'all')

    query = AgentReview.objects.select_related('agent', 'user')

    # Apply search filter
    if search:
        query = query.filter(
            Q(agent__fullname__icontains=search) |
            Q(reviewer_name__icontains=search) |
            Q(review__icontains=search)
        )

    # Apply status filter
    if status_filter == 'pending':
        query = query.filter(is_approved=False)
    elif status_filter == 'approved':
        query = query.filter(is_approved=True)

    # Apply rating filter
    if rating_filter != 'all':
        try:
            query = query.filter(rating=int(rating_filter))
        except ValueError:
            pass

    # Order by newest
    reviews_list = query.order_by('-created_at')

    # Paginate (20 per page)
    paginator = Paginator(reviews_list, 20)
    page_number = request.GET.get('page')
    reviews_page = paginator.get_page(page_number)

    for r in reviews_page:
        if r.reviewer_name:
            r.display_reviewer_name = r.reviewer_name
        elif r.user:
            r.display_reviewer_name = getattr(r.user, 'fullname', '') or r.user.get_full_name() or r.user.username
        else:
            r.display_reviewer_name = "Anonymous"

        if r.agent:
            r.display_agent_name = r.agent.fullname
        else:
            r.display_agent_name = "Unknown Agent"

    # Statistics (for the stats cards)
    total_count = AgentReview.objects.count()
    pending_count = AgentReview.objects.filter(is_approved=False).count()
    approved_count = AgentReview.objects.filter(is_approved=True).count()
    
    avg_rating_aggregate = AgentReview.objects.filter(is_approved=True).aggregate(Avg('rating'))
    avg_rating_val = avg_rating_aggregate['rating__avg']
    avg_rating = round(float(avg_rating_val), 1) if avg_rating_val is not None else 0.0

    stats = {
        'total': total_count,
        'pending': pending_count,
        'approved': approved_count,
        'avg_rating': avg_rating
    }

    # Pass range of stars 5 down to 1
    stars_range = range(5, 0, -1)

    context = {
        'reviews': reviews_page,
        'stats': stats,
        'search': search,
        'statusFilter': status_filter,
        'ratingFilter': rating_filter,
        'stars_range': stars_range
    }

    return render(request, 'admin/reviews/index.html', context)

def toggle_review_approval(request):
    admin_id = _get_admin_from_session(request)
    if not admin_id: return JsonResponse({'success': False, 'message': 'Unauthorized'}, status=401)
    if request.method == 'POST':
        review_id = request.POST.get('id')
        is_approved_raw = request.POST.get('is_approved')
        
        # Also check if JSON is posted (for AJAX calls that use application/json)
        if not review_id and request.content_type == 'application/json':
            try:
                data = json.loads(request.body)
                review_id = data.get('id')
                is_approved_raw = data.get('is_approved')
            except Exception:
                pass

        if not review_id:
            return JsonResponse({'success': False, 'message': 'Review ID is required'}, status=400)

        review = get_object_or_404(AgentReview, id=review_id)
        
        # Convert to boolean
        is_approved = str(is_approved_raw).lower() in ['1', 'true', 'yes']

        review.is_approved = is_approved
        review.updated_at = timezone.now()
        review.save()

        # Log admin activity
        log_action = 'Approve review' if is_approved else 'Revoke review approval'
        AdminActivityLog.log(log_action, 'AgentReview', review.id, request=request)

        # Clear homepage reviews cache
        cache.delete('homepage_reviews')

        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json':
            return JsonResponse({'success': True})
            
        messages.success(request, 'Review status updated.')
        return redirect(request.META.get('HTTP_REFERER', 'admin_reviews_index'))

    return JsonResponse({'success': False, 'message': 'Invalid request method'}, status=405)

def bulk_approve_reviews(request):
    admin_id = _get_admin_from_session(request)
    if not admin_id: return JsonResponse({'success': False, 'message': 'Unauthorized'}, status=401)
    if request.method == 'POST':
        ids = request.POST.getlist('ids[]') or request.POST.getlist('ids')

        # Also support JSON array
        if not ids and request.content_type == 'application/json':
            try:
                data = json.loads(request.body)
                ids = data.get('ids', [])
            except Exception:
                pass

        if ids:
            # Map values to integers
            try:
                ids = [int(i) for i in ids]
            except ValueError:
                return JsonResponse({'success': False, 'message': 'Invalid ID format'}, status=400)

            AgentReview.objects.filter(id__in=ids).update(
                is_approved=True,
                updated_at=timezone.now()
            )

            # Log bulk activity
            AdminActivityLog.log('Bulk approve reviews', 'AgentReview', details={'count': len(ids), 'ids': ids}, request=request)

            # Clear cache
            cache.delete('homepage_reviews')

        return JsonResponse({'success': True, 'count': len(ids)})

    return JsonResponse({'success': False, 'message': 'Invalid request method'}, status=405)

def delete_review(request):
    admin_id = _get_admin_from_session(request)
    if not admin_id: return JsonResponse({'success': False, 'message': 'Unauthorized'}, status=401)
    if request.method == 'POST':
        review_id = request.POST.get('id')

        # Also check JSON
        if not review_id and request.content_type == 'application/json':
            try:
                data = json.loads(request.body)
                review_id = data.get('id')
            except Exception:
                pass

        if not review_id:
            return JsonResponse({'success': False, 'message': 'Review ID is required'}, status=400)

        review = get_object_or_404(AgentReview, id=review_id)
        review.delete()

        # Log deletion
        AdminActivityLog.log('Delete review', 'AgentReview', review_id, request=request)

        # Clear cache
        cache.delete('homepage_reviews')

        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json':
            return JsonResponse({'success': True})

        messages.success(request, 'Review deleted.')
        return redirect(request.META.get('HTTP_REFERER', 'admin_reviews_index'))

    return JsonResponse({'success': False, 'message': 'Invalid request method'}, status=405)
