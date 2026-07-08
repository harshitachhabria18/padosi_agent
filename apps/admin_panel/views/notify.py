import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Count, Max, Q
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.db import models

from apps.admin_panel.views.dashboard import _get_admin_from_session
from apps.admin_panel.models import AdminActivityLog, Agent

logger = logging.getLogger(__name__)

from apps.admin_panel.views.broadcast import AdminBroadcast, AgentDeviceToken

# ─── INDEX ───────────────────────────────────────────────────────────────────

def notify_index(request):
    admin = _get_admin_from_session(request)
    if not admin:
        return redirect('admin_login_page')

    # All active agents (for single-agent dropdown)
    agents = Agent.objects.filter(status='active').order_by('fullname')

    # Count of distinct active agents that have at least one device token
    token_count = (
        AgentDeviceToken.objects
        .filter(agent__status='active')
        .values('agent_id')
        .distinct()
        .count()
    )

    # Agents with device tokens — one row per agent, aggregated
    # Mirrors the DB::table('agent_device_tokens as t')->join('agents as a',...) query
    push_agents = (
        AgentDeviceToken.objects
        .filter(agent__status='active')
        .values('agent_id', 'agent__fullname', 'agent__email', 'agent__mobile')
        .annotate(
            token_count=Count('id'),
            platform=Max('platform'),
            last_seen_at=Max('last_seen_at'),
            registered_at=Max('created_at'),
        )
        .order_by('-last_seen_at')
    )

    # Attach a clean dict for template (mirrors $pa->fullname, $pa->id, etc.)
    push_agent_list = []
    now = timezone.now()
    for row in push_agents:
        last_seen = row['last_seen_at']
        is_recent = (
            last_seen and (now - last_seen).days <= 3
        )
        push_agent_list.append({
            'id':          row['agent_id'],
            'fullname':    row['agent__fullname'],
            'email':       row['agent__email'],
            'mobile':      row['agent__mobile'] or '—',
            'platform':    (row['platform'] or 'web').lower() if row['platform'] else 'web',
            'token_count': row['token_count'],
            'last_seen_at': last_seen,
            'is_recent':   is_recent,
        })

    return render(request, 'admin/notify.html', {
        'agents':          agents,
        'token_count':     token_count,
        'push_agents':     push_agent_list,
        'active_count':    agents.count(),
        'without_push':    max(0, agents.count() - token_count),
    })


# ─── SEND TO SINGLE AGENT ────────────────────────────────────────────────────

@require_POST
def notify_send(request):
    admin = _get_admin_from_session(request)
    if not admin:
        return redirect('admin_login_page')

    agent_id = request.POST.get('agent_id', '').strip()
    title    = request.POST.get('title', '').strip()
    body     = request.POST.get('body', '').strip()

    # Basic validation
    if not agent_id or not title or not body:
        messages.error(request, 'Agent, title, and message are all required.')
        return redirect('agent_notify')

    agent = get_object_or_404(Agent, id=agent_id)

    # Collect FCM tokens for this agent
    tokens = list(
        AgentDeviceToken.objects
        .filter(agent_id=agent.id)
        .exclude(token__isnull=True)
        .exclude(token='')
        .values_list('token', flat=True)
        .distinct()
    )

    if not tokens:
        messages.error(
            request,
            f"No device tokens found for {agent.fullname}. "
            "They may not have the PWA installed or notifications enabled."
        )
        return redirect('agent_notify')

    # Send via FCM
    try:
        from apps.admin_panel.services.fcm import FcmService
        FcmService().send_to_tokens(tokens, title, body, {'type': 'admin_custom'})
    except Exception as exc:
        logger.error(f"FCM send failed for agent #{agent.id}: {exc}")
        messages.error(request, f"Push notification failed: {exc}")
        return redirect('agent_notify')

    # Log activity
    try:
        AdminActivityLog.log(
            action=f"Push notification sent to agent #{agent.id} ({agent.fullname})",
            model_type='Agent',
            request=request,
        )
    except Exception:
        pass

    messages.success(request, f"Push notification sent successfully to {agent.fullname}!")
    return redirect('agent_notify')


# ─── BROADCAST PUSH ──────────────────────────────────────────────────────────

@require_POST
def notify_broadcast(request):
    admin = _get_admin_from_session(request)
    if not admin:
        return redirect('admin_login_page')

    title  = request.POST.get('title', '').strip()
    body   = request.POST.get('body', '').strip()
    target = request.POST.get('target', '').strip()

    VALID_TARGETS = {'all', 'professional', 'starter', 'expiring'}
    if not title or not body or target not in VALID_TARGETS:
        messages.error(request, 'Title, message, and a valid target are required.')
        return redirect('agent_notify')

    now = timezone.now()

    # Build agent ID query based on target — mirrors PHP query
    agents_qs = Agent.objects.filter(status='active')

    if target == 'professional':
        agents_qs = agents_qs.filter(
            subscriptions__selected_plan__icontains='professional'
        )
    elif target == 'starter':
        agents_qs = agents_qs.filter(
            subscriptions__selected_plan__icontains='starter'
        )
    elif target == 'expiring':
        agents_qs = agents_qs.filter(
            subscriptions__expires_at__gte=now,
            subscriptions__expires_at__lte=now + timezone.timedelta(days=30),
        )

    agent_ids = list(agents_qs.distinct().values_list('id', flat=True))

    if not agent_ids:
        messages.error(request, 'No agents found for the selected target group.')
        return redirect('agent_notify')

    # Gather all device tokens for those agents
    tokens = list(
        AgentDeviceToken.objects
        .filter(agent_id__in=agent_ids)
        .exclude(token__isnull=True)
        .exclude(token='')
        .values_list('token', flat=True)
        .distinct()
    )

    if not tokens:
        messages.error(
            request,
            'No device tokens found for the selected agents. '
            'They may not have the PWA installed.'
        )
        return redirect('agent_notify')

    # Send via FCM
    sent_count = len(tokens)
    try:
        from apps.admin_panel.services.fcm import FcmService
        FcmService().send_to_tokens(tokens, title, body, {
            'type':   'admin_broadcast',
            'target': target,
        })
    except Exception as exc:
        logger.error(f"FCM broadcast failed (target={target}): {exc}")
        messages.error(request, f"Broadcast push failed: {exc}")
        return redirect('agent_notify')

    # Log to admin_broadcasts table (mirrors PHP DB::table('admin_broadcasts')->insert())
    try:
        AdminBroadcast.objects.create(
            subject=title,
            message=body,
            target=target,
            channels='push',
            sent_count=sent_count,
        )
    except Exception as exc:
        logger.warning(f"Could not log broadcast push to DB: {exc}")

    # Log admin activity
    try:
        AdminActivityLog.log(
            action=f"Push broadcast sent: '{title}'",
            model_type='Broadcast',
            details={'target': target, 'channels': ['push'], 'token_count': sent_count},
            request=request,
        )
    except Exception:
        pass

    targets_label = {
        'all':          'All Active Agents',
        'professional': 'Professional Plan',
        'starter':      'Starter Plan',
        'expiring':     'Expiring Soon',
    }
    messages.success(
        request,
        f"Push notification broadcast sent to {sent_count} device(s) "
        f"in the '{targets_label.get(target, target)}' group!"
    )
    return redirect('agent_notify')
