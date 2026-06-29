import json
from django.shortcuts import render, redirect
from django.utils import timezone
from django.db.models import Q
from django.contrib import messages
from apps.admin_panel.decorators import admin_login_required
from apps.agents.models import Agent, AgentDeviceToken
from apps.admin_panel.models import AdminActivityLog, AdminBroadcast

@admin_login_required
def broadcast_index(request):
    now = timezone.now()

    # Calculate agent counts per target segment
    all_count = Agent.objects.filter(status='active').count()

    professional_count = Agent.objects.filter(
        status='active',
        subscriptions__selected_plan__icontains='professional'
    ).distinct().count()

    starter_count = Agent.objects.filter(
        status='active',
        subscriptions__selected_plan__icontains='starter'
    ).distinct().count()

    expiring_count = Agent.objects.filter(
        status='active',
        subscriptions__expires_at__gte=now,
        subscriptions__expires_at__lte=now + timezone.timedelta(days=30)
    ).distinct().count()

    agent_counts = {
        'all': all_count,
        'professional': professional_count,
        'starter': starter_count,
        'expiring': expiring_count,
    }

    # Fetch recent broadcasts, handle gracefully if table is missing
    recent_broadcasts = []
    try:
        recent_broadcasts = list(AdminBroadcast.objects.order_by('-created_at')[:5])
        targets_map = {
            'all': 'All Active Agents',
            'professional': 'Professional Plan',
            'starter': 'Starter Plan',
            'expiring': 'Expiring Soon',
        }
        for b in recent_broadcasts:
            b.target_label = targets_map.get(b.target, b.target)
    except Exception:
        pass

    context = {
        'agentCounts': agent_counts,
        'recentBroadcasts': recent_broadcasts,
    }

    return render(request, 'admin/broadcast.html', context)

@admin_login_required
def send_broadcast(request):
    if request.method == 'POST':
        target = request.POST.get('target')
        subject = request.POST.get('subject', '').strip()
        message = request.POST.get('message', '').strip()
        channels = request.POST.getlist('channels[]') or request.POST.getlist('channels') or ['email']

        if not target or not subject or not message:
            messages.error(request, "Target, Subject, and Message are required.")
            return redirect('admin_panel:broadcast_index')

        now = timezone.now()

        # Build target agent query
        agents_query = Agent.objects.filter(status='active')

        if target == 'professional':
            agents_query = agents_query.filter(
                Q(subscriptions__selected_plan__icontains='professional') | Q(subscriptions__selected_plan__icontains='pro')
            )
        elif target == 'starter':
            agents_query = agents_query.filter(subscriptions__selected_plan__icontains='starter')
        elif target == 'expiring':
            agents_query = agents_query.filter(
                subscriptions__expires_at__gte=now,
                subscriptions__expires_at__lte=now + timezone.timedelta(days=30)
            )

        agents = list(agents_query.distinct())
        sent_count = 0
        push_count = 0

        # Email Delivery Channel
        if 'email' in channels:
            from apps.agents.services.brevo import send_brevo_email
            for agent in agents:
                try:
                    personalized_message = message.replace('[Agent Name]', agent.fullname).replace('{name}', agent.fullname)
                    
                    html_body = f"""
                    <!DOCTYPE html>
                    <html>
                    <head><meta charset="UTF-8"></head>
                    <body style="margin:0;padding:0;background:#f4f6f9;font-family:Arial,sans-serif;">
                      <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f6f9;padding:30px 0;">
                        <tr><td align="center">
                          <table width="600" cellpadding="0" cellspacing="0"
                                 style="background:#ffffff;border-radius:12px;overflow:hidden;
                                        box-shadow:0 4px 20px rgba(0,0,0,0.08);max-width:600px;width:100%;">
                            <tr>
                              <td style="background:#273C8E;padding:28px 40px;text-align:center;">
                                <h1 style="color:#ffffff;margin:0;font-size:22px;letter-spacing:1px;">PadosiAgent</h1>
                              </td>
                            </tr>
                            <tr>
                              <td style="padding:40px 40px 30px; font-size: 14px; color: #475569; line-height: 1.8; white-space: pre-wrap;">{personalized_message}</td>
                            </tr>
                            <tr>
                              <td style="background:#f9fafb;padding:20px 40px;text-align:center;border-top:1px solid #e5e7eb;font-size:11px;color:#94a3b8;">
                                PadosiAgent Platform | You're receiving this because you're a registered agent.
                              </td>
                            </tr>
                          </table>
                        </td></tr>
                      </table>
                    </body>
                    </html>
                    """
                    success = send_brevo_email(agent.email, agent.fullname, subject, html_body)
                    if success:
                        sent_count += 1
                except Exception:
                    pass

        # Push Notification Channel
        if 'notification' in channels:
            from apps.agents.services.fcm import FcmService
            agent_ids = [agent.id for agent in agents]
            if agent_ids:
                tokens = list(AgentDeviceToken.objects.filter(agent_id__in=agent_ids).exclude(token=None).exclude(token='').values_list('token', flat=True).distinct())
                if tokens:
                    push_body = message[:255]
                    fcm_service = FcmService()
                    try:
                        fcm_service.send_to_tokens(tokens, subject, push_body, {
                            'type': 'admin_broadcast',
                            'target': target,
                        })
                        push_count = len(tokens)
                    except Exception:
                        pass

        # Log Broadcast in table
        try:
            AdminBroadcast.objects.create(
                subject=subject,
                message=message,
                target=target,
                channels=','.join(channels),
                sent_count=sent_count + push_count
            )
        except Exception:
            pass

        # Log Admin Activity
        try:
            AdminActivityLog.log(
                action=f"Broadcast sent: '{subject}'",
                model_type='Broadcast',
                details={
                    'target': target,
                    'channels': channels,
                    'email_count': sent_count,
                    'push_count': push_count
                },
                request=request
            )
        except Exception:
            pass

        parts = []
        if sent_count > 0:
            parts.append(f"{sent_count} email(s)")
        if push_count > 0:
            parts.append(f"{push_count} device(s) via push")
        summary = " and ".join(parts) if parts else "0 recipients"

        messages.success(request, f"Broadcast sent successfully to {summary}.")
        return redirect('admin_panel:broadcast_index')

    return redirect('admin_panel:broadcast_index')
