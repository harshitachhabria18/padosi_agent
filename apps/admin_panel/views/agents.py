from django.shortcuts import render
from django.core.paginator import Paginator
from django.db.models import Count, Q
from apps.admin_panel.decorators import admin_login_required
from apps.agents.models import Agent


@admin_login_required
def agent_list(request):
    search = request.GET.get('search', '').strip()

    agents_qs = Agent.objects.annotate(
        _total_reviews=Count('reviews', filter=Q(reviews__is_approved=True))
    ).select_related('profile').order_by('-id')

    if search:
        agents_qs = agents_qs.filter(
            Q(fullname__icontains=search) |
            Q(email__icontains=search) |
            Q(mobile__icontains=search) |
            Q(agent_pincode__icontains=search)
        )

    for agent in agents_qs:
        badge_str = agent.badge or ''
        agent._badges = [b.strip() for b in badge_str.split(',') if b.strip()]

    paginator = Paginator(agents_qs, 20)
    page = request.GET.get('page', 1)
    agents_page = paginator.get_page(page)

    context = {
        'agents': agents_page,
        'search': search,
    }
    return render(request, 'admin/agents_list.html', context)
