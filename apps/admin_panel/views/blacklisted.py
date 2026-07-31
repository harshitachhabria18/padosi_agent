from django.shortcuts import render
from django.http import JsonResponse
from django.utils import timezone
from django.core.paginator import Paginator
from django.db.models import Q, Exists, OuterRef
from apps.agents.models import Agent
from apps.home.models.blacklisted_agent import BlacklistedAgent


def blacklisted_agents_view(request):
    active_tab = request.GET.get('tab', 'flagged')
    
    # Tab 1 — IRDAI Flagged
    # Agents whose PAN exists in blacklisted_agents table
    # but have not been reviewed yet (not approved, not blacklisted)
    flagged_agents = Agent.objects.filter(
        profile__pan_number__in=BlacklistedAgent.objects.values('pan'),
        is_blacklisted=False,
        blacklist_source__isnull=True
    ).select_related('profile').order_by('-created_at')

    # For each flagged agent get the matching IRDAI entry
    flagged_with_match = []
    for agent in flagged_agents:
        pan = agent.profile.pan_number if hasattr(agent, 'profile') else None
        if pan:
            irdai_match = BlacklistedAgent.objects.filter(
                pan=pan
            ).order_by('-blacklisted_date').first()
            flagged_with_match.append({
                'agent': agent,
                'irdai_match': irdai_match
            })

    # Tab 2 — Manually Blacklisted
    manually_blacklisted = Agent.objects.filter(
        is_blacklisted=True
    ).select_related('profile').order_by('-blacklisted_at')

    # Tab 3 — IRDAI Master List with search and filter
    irdai_query = request.GET.get('q', '').strip()
    irdai_field = request.GET.get('field', 'all')
    irdai_type = request.GET.get('type', '').strip()
    irdai_page = request.GET.get('page', 1)

    irdai_list = BlacklistedAgent.objects.all()

    if irdai_query:
        if irdai_field == 'pan':
            irdai_list = irdai_list.filter(pan__icontains=irdai_query)
        elif irdai_field == 'agent_name':
            irdai_list = irdai_list.filter(agent_name__icontains=irdai_query)
        elif irdai_field == 'agency_code':
            irdai_list = irdai_list.filter(agency_code__icontains=irdai_query)
        elif irdai_field == 'insurer':
            irdai_list = irdai_list.filter(insurer__icontains=irdai_query)
        else:
            irdai_list = irdai_list.filter(
                Q(agent_name__icontains=irdai_query) |
                Q(pan__icontains=irdai_query) |
                Q(agency_code__icontains=irdai_query) |
                Q(insurer__icontains=irdai_query)
            )

    if irdai_type:
        irdai_list = irdai_list.filter(insurer_type__iexact=irdai_type)

    # Annotate with on_platform flag
    registered_pans = set(
        Agent.objects.filter(
            profile__pan_number__isnull=False
        ).values_list('profile__pan_number', flat=True)
    )

    insurer_types = BlacklistedAgent.objects.values_list(
        'insurer_type', flat=True
    ).distinct().exclude(
        insurer_type__isnull=True
    ).exclude(insurer_type='').order_by('insurer_type')

    paginator = Paginator(irdai_list.order_by('agent_name'), 25)
    irdai_page_obj = paginator.get_page(irdai_page)

    # Sidebar badge count
    flagged_count = Agent.objects.filter(
        profile__pan_number__in=BlacklistedAgent.objects.values('pan'),
        is_blacklisted=False,
        blacklist_source__isnull=True
    ).count()

    return render(request, 'admin/blacklisted_agents.html', {
        'active_tab': active_tab,
        'flagged_with_match': flagged_with_match,
        'manually_blacklisted': manually_blacklisted,
        'irdai_page_obj': irdai_page_obj,
        'registered_pans': registered_pans,
        'insurer_types': insurer_types,
        'irdai_query': irdai_query,
        'irdai_field': irdai_field,
        'irdai_type': irdai_type,
        'flagged_count': flagged_count,
    })


def ajax_blacklist_approve(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid method'})
    agent_id = request.POST.get('agent_id')
    try:
        agent = Agent.objects.get(id=agent_id)
        agent.blacklist_source = 'Approved'
        agent.save()
        return JsonResponse({'success': True, 'message': 'Agent cleared successfully'})
    except Agent.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Agent not found'})


def ajax_blacklist_confirm(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid method'})
    agent_id = request.POST.get('agent_id')
    reason = request.POST.get('reason', 'PAN found in IRDAI blacklist')
    try:
        agent = Agent.objects.get(id=agent_id)
        agent.is_blacklisted = True
        agent.blacklist_reason = reason
        agent.blacklisted_at = timezone.now()
        agent.blacklist_source = 'Admin'
        agent.save()
        return JsonResponse({'success': True, 'message': 'Agent blacklisted successfully'})
    except Agent.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Agent not found'})


def ajax_blacklist_remove(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid method'})
    agent_id = request.POST.get('agent_id')
    try:
        agent = Agent.objects.get(id=agent_id)
        agent.is_blacklisted = False
        agent.blacklist_reason = None
        agent.blacklisted_at = None
        agent.blacklist_source = None
        agent.save()
        return JsonResponse({'success': True, 'message': 'Blacklist removed successfully'})
    except Agent.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Agent not found'})
