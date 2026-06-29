import json
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.utils import timezone
from django.db.models import Q, F
from django.contrib import messages
from apps.admin_panel.decorators import admin_login_required
from apps.agents.models import AgentSubscription
from apps.admin_panel.models import AdminActivityLog

@admin_login_required
def subscriptions_index(request):
    filter_val = request.GET.get('filter', 'all')
    now = timezone.now()

    # Query active subscriptions for agents with active status
    query = AgentSubscription.objects.filter(agent__status='active').select_related('agent', 'agent__profile')

    if filter_val == 'expired':
        query = query.filter(expires_at__lt=now)
    elif filter_val == 'expiring_soon':
        query = query.filter(expires_at__gte=now, expires_at__lte=now + timezone.timedelta(days=30))

    # Order by: NULL expires_at should be last, others ascending by expires_at.
    subscriptions_list = query.order_by(F('expires_at').asc(nulls_last=True))

    # Precalculate dynamic attributes for each subscription
    for sub in subscriptions_list:
        if sub.expires_at:
            diff = sub.expires_at - now
            days_left = int(diff.total_seconds() / 86400)
            sub.days_left = days_left
            sub.days_left_abs = abs(days_left)
            sub.is_expired = days_left < 0
            sub.is_expiring_soon = not sub.is_expired and days_left <= 30
        else:
            sub.days_left = None
            sub.is_expired = False
            sub.is_expiring_soon = False

        # Status badge attributes
        if sub.is_expired:
            sub.badge_class = 'bg-danger'
            sub.badge_text = 'Expired'
        elif sub.is_expiring_soon:
            sub.badge_class = 'bg-warning text-dark'
            sub.badge_text = 'Expiring Soon'
        else:
            sub.badge_class = 'bg-success'
            sub.badge_text = 'Active'

        plan_name = sub.selected_plan or ''
        sub.is_professional = 'professional' in plan_name.lower() or 'pro' in plan_name.lower()

        agent = sub.agent
        sub.display_fullname = agent.fullname
        sub.display_email = agent.email
        try:
            profile = agent.profile
            sub.display_name = profile.display_name or agent.fullname
        except Exception:
            sub.display_name = agent.fullname

    # Stats for summary cards
    active_subs = AgentSubscription.objects.filter(agent__status='active')
    
    expired_count = active_subs.filter(expires_at__lt=now).count()
    
    expiring_30_count = active_subs.filter(
        expires_at__gte=now,
        expires_at__lte=now + timezone.timedelta(days=30)
    ).count()
    
    expiring_60_count = active_subs.filter(
        expires_at__gt=now + timezone.timedelta(days=30),
        expires_at__lte=now + timezone.timedelta(days=60)
    ).count()
    
    active_healthy_count = active_subs.filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=now + timezone.timedelta(days=60))
    ).count()

    # Estimate Monthly Revenue
    professional_count = active_subs.filter(
        Q(selected_plan__icontains='professional') | Q(selected_plan__icontains='pro'),
        Q(expires_at__isnull=True) | Q(expires_at__gt=now)
    ).count()

    starter_count = active_subs.filter(
        Q(selected_plan__icontains='starter'),
        Q(expires_at__isnull=True) | Q(expires_at__gt=now)
    ).count()

    est_revenue = (professional_count * 999) + (starter_count * 499)

    stats = {
        'expired': expired_count,
        'expiring_30': expiring_30_count,
        'expiring_60': expiring_60_count,
        'active_healthy': active_healthy_count,
        'est_revenue': est_revenue
    }

    context = {
        'subscriptions': subscriptions_list,
        'stats': stats,
        'filter': filter_val,
    }

    return render(request, 'admin/subscriptions.html', context)

@admin_login_required
def delete_subscription(request):
    if request.method == 'POST':
        sub_id = request.POST.get('id')

        # Support JSON payload
        if not sub_id and request.content_type == 'application/json':
            try:
                data = json.loads(request.body)
                sub_id = data.get('id')
            except Exception:
                pass

        if not sub_id:
            return JsonResponse({'success': False, 'message': 'Subscription ID is required'}, status=400)

        subscription = get_object_or_404(AgentSubscription, id=sub_id)
        subscription.delete()

        # Log admin activity
        AdminActivityLog.log('Delete subscription', 'AgentSubscription', sub_id, request=request)

        return JsonResponse({'success': True, 'message': 'Subscription deleted successfully'})

    return JsonResponse({'success': False, 'message': 'Invalid request method'}, status=405)
