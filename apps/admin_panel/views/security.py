import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.contrib import messages
from django.db.models import Count, Max
from django.db import models

from apps.admin_panel.views.dashboard import _get_admin_from_session
from apps.admin_panel.models import AdminActivityLog

logger = logging.getLogger(__name__)

from apps.admin_panel.models.admin_auth import SecurityThreatLog
from apps.agents.models import BlockedIp, AgentLead


def threat_logs(request):
    admin = _get_admin_from_session(request)
    if not admin:
        return redirect('admin_login_page')
        
    try:
        logs_list = SecurityThreatLog.objects.all().order_by('-id')
        paginator = Paginator(logs_list, 50)
        page_number = request.GET.get('page', 1)
        page_obj = paginator.get_page(page_number)
    except Exception:
        page_obj = []

    context = {
        'threatLogs': page_obj,
    }
    return render(request, 'admin/security/threat_logs.html', context)


def delete_threat_log(request):
    admin = _get_admin_from_session(request)
    if not admin:
        return JsonResponse({'success': False, 'message': 'Unauthorized.'})
        
    if request.method == 'POST':
        log_id = request.POST.get('id')
        if log_id:
            try:
                log = SecurityThreatLog.objects.get(id=log_id)
                log.delete()
                return JsonResponse({'success': True, 'message': 'Threat log deleted successfully.'})
            except SecurityThreatLog.DoesNotExist:
                return JsonResponse({'success': False, 'message': 'Log record not found.'})
    return JsonResponse({'success': False, 'message': 'Invalid request.'})


def blocked_ips(request):
    admin = _get_admin_from_session(request)
    if not admin:
        return redirect('admin_login_page')
        
    blocked_list = BlockedIp.objects.all().order_by('-id')
    paginator = Paginator(blocked_list, 20)
    page_number = request.GET.get('page', 1)
    blocked_page = paginator.get_page(page_number)

    # Top IPs querying contacts to help admin identify scrapers
    recent_activity = (
        AgentLead.objects.values('ip_address')
        .annotate(total_clicks=Count('id'), last_activity=Max('created_at'))
        .filter(ip_address__isnull=False)
        .order_by('-last_activity')[:50]
    )

    threat_logs_mini = SecurityThreatLog.objects.all().order_by('-id')[:50]

    # Map if each threat log IP is currently blocked
    blocked_ips_set = set(BlockedIp.objects.values_list('ip_address', flat=True))
    for log in threat_logs_mini:
        log.is_blocked = log.ip_address in blocked_ips_set

    # Also find corresponding BlockedIp ID for each threat log to enable Lift Block form
    blocked_records_map = {b.ip_address: b.id for b in BlockedIp.objects.all()}
    for log in threat_logs_mini:
        log.blocked_id = blocked_records_map.get(log.ip_address)

    context = {
        'blockedIps': blocked_page,
        'recentActivity': recent_activity,
        'threatLogs': threat_logs_mini,
    }
    return render(request, 'admin/security/blocked_ips.html', context)


def block_ip(request):
    admin = _get_admin_from_session(request)
    if not admin:
        return redirect('admin_login_page')
        
    if request.method == 'POST':
        ip_address = request.POST.get('ip_address', '').strip()
        reason = request.POST.get('reason', '').strip() or 'Manually blocked by admin.'
        
        if ip_address:
            if BlockedIp.objects.filter(ip_address=ip_address).exists():
                messages.error(request, 'IP address is already blocked.')
            else:
                blocked = BlockedIp.objects.create(
                    ip_address=ip_address,
                    reason=reason
                )
                AdminActivityLog.log('Blocked IP address', 'Security', blocked.id, f"IP: {ip_address}", request=request)
                messages.success(request, 'IP address blocked successfully.')
        else:
            messages.error(request, 'IP address is required.')
            
    return redirect('security_threat_logs')


def unblock_ip(request, ip_id):
    admin = _get_admin_from_session(request)
    if not admin:
        return redirect('admin_login_page')
        
    if request.method == 'POST':
        blocked_ip = get_object_or_404(BlockedIp, id=ip_id)
        ip = blocked_ip.ip_address
        blocked_ip.delete()
        AdminActivityLog.log('Unblocked IP address', 'Security', ip_id, f"IP was: {ip}", request=request)
        messages.success(request, 'IP address unblocked successfully.')
    return redirect('security_blocked_ips')
