import json
import logging

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.admin_panel.views.dashboard import _get_admin_from_session
from apps.event_referral.models import EventReferral, EventReferralCampaign, EventReferralParticipant
from apps.event_referral.services.participant_service import (
    _block_participant,
    admin_grant_win,
    admin_restore_participant,
)

logger = logging.getLogger(__name__)


def _require_admin(request):
    admin = _get_admin_from_session(request)
    if not admin:
        return None
    return admin


def admin_dashboard(request):
    if not _require_admin(request):
        return redirect('/admin/login/')

    campaign = EventReferralCampaign.get_current()
    participants = (
        EventReferralParticipant.objects.select_related('agent')
        .order_by('-registered_at')[:200]
    )
    stats = {
        'total': EventReferralParticipant.objects.count(),
        'active': EventReferralParticipant.objects.filter(status='active').count(),
        'won': EventReferralParticipant.objects.filter(status='won').count(),
        'blocked': EventReferralParticipant.objects.filter(status='blocked').count(),
    }
    from django.conf import settings

    public_base = (getattr(settings, 'APP_URL', '') or '').rstrip('/')
    if not public_base:
        public_base = request.build_absolute_uri('/').rstrip('/')

    return render(
        request,
        'event_referral/admin/dashboard.html',
        {
            'campaign': campaign,
            'participants': participants,
            'stats': stats,
            'event_registration_public_url': f'{public_base}/event-registration/',
        },
    )


@require_POST
def admin_toggle_registration(request):
    if not _require_admin(request):
        return redirect('/admin/login/')

    campaign = EventReferralCampaign.get_current()
    campaign.is_enabled = not campaign.is_enabled
    campaign.save(update_fields=['is_enabled', 'updated_at'])
    if campaign.is_enabled:
        messages.success(request, 'Event registration page is now LIVE.')
    else:
        messages.warning(request, 'Event registration page is now OFF (visitors see closed message).')
    return redirect('admin_event_referral_dashboard')


@require_POST
def admin_update_settings(request):
    if not _require_admin(request):
        return redirect('/admin/login/')

    campaign = EventReferralCampaign.get_current()
    campaign.is_enabled = request.POST.get('is_enabled') == 'on'
    try:
        campaign.window_hours = max(1, int(request.POST.get('window_hours', campaign.window_hours)))
        campaign.required_paid_referrals = max(
            1, int(request.POST.get('required_paid_referrals', campaign.required_paid_referrals)),
        )
    except (TypeError, ValueError):
        messages.error(request, 'Invalid numeric settings.')
        return redirect('admin_event_referral_dashboard')

    campaign.reward_plan_slug = (request.POST.get('reward_plan_slug') or 'basic').strip()
    campaign.page_title = (request.POST.get('page_title') or campaign.page_title).strip()
    campaign.page_instructions = (request.POST.get('page_instructions') or '').strip()
    campaign.save()
    messages.success(request, 'Event referral settings saved.')
    return redirect('admin_event_referral_dashboard')


@require_POST
def admin_extend_deadline(request, participant_id):
    if not _require_admin(request):
        return redirect('/admin/login/')
    participant = get_object_or_404(EventReferralParticipant, pk=participant_id)
    try:
        hours = int(request.POST.get('extend_hours', 0))
    except (TypeError, ValueError):
        hours = 0
    if hours > 0:
        admin_restore_participant(participant, extend_hours=hours)
        messages.success(request, f'Extended deadline by {hours} hours.')
    return redirect('admin_event_referral_dashboard')


@require_POST
def admin_update_target(request, participant_id):
    if not _require_admin(request):
        return redirect('/admin/login/')
    participant = get_object_or_404(EventReferralParticipant, pk=participant_id)
    try:
        target = max(1, int(request.POST.get('required_paid_referrals', participant.required_paid_referrals)))
    except (TypeError, ValueError):
        messages.error(request, 'Invalid target.')
        return redirect('admin_event_referral_dashboard')
    participant.required_paid_referrals = target
    participant.save(update_fields=['required_paid_referrals', 'updated_at'])
    messages.success(request, 'Referral target updated for this participant.')
    return redirect('admin_event_referral_dashboard')


@require_POST
def admin_grant_plan(request, participant_id):
    if not _require_admin(request):
        return redirect('/admin/login/')
    participant = get_object_or_404(EventReferralParticipant, pk=participant_id)
    admin_grant_win(participant)
    messages.success(request, 'Basic plan granted.')
    return redirect('admin_event_referral_dashboard')


@require_POST
def admin_block_participant(request, participant_id):
    if not _require_admin(request):
        return redirect('/admin/login/')
    participant = get_object_or_404(EventReferralParticipant, pk=participant_id)
    reason = (request.POST.get('reason') or 'Blocked by admin.').strip()
    _block_participant(participant, reason=reason)
    messages.success(request, 'Participant blocked.')
    return redirect('admin_event_referral_dashboard')


@require_POST
def admin_restore_participant(request, participant_id):
    if not _require_admin(request):
        return redirect('/admin/login/')
    participant = get_object_or_404(EventReferralParticipant, pk=participant_id)
    try:
        hours = int(request.POST.get('extend_hours', 0))
    except (TypeError, ValueError):
        hours = 0
    admin_restore_participant(participant, extend_hours=hours)
    messages.success(request, 'Participant restored.')
    return redirect('admin_event_referral_dashboard')
