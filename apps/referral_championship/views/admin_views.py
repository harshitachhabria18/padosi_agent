import csv
import json
import logging
from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from django.contrib import messages
from django.views.decorators.http import require_POST, require_http_methods
from django.db.models import Sum, Count, Q

from apps.admin_panel.views.dashboard import _get_admin_from_session
from apps.referral_championship.models import (
    ChampionshipCampaign,
    ChampionshipParticipant,
    ChampionshipReferral,
    ChampionshipRewardSlab,
    ChampionshipRewardClaim,
    ChampionshipFraudFlag,
    ChampionshipAuditLog,
    ChampionshipLeaderboardCache,
)
from apps.referral_championship.services.leaderboard_service import refresh_leaderboard_cache

logger = logging.getLogger(__name__)


def _is_authorized_admin(request):
    """Verify session admin authentication."""
    admin = _get_admin_from_session(request)
    return admin is not None


def admin_championship_dashboard(request):
    """Main Admin Championship Hub."""
    if not _is_authorized_admin(request):
        return redirect('/admin/login/')

    campaign = ChampionshipCampaign.get_current()

    # Financial & Liability Calculations
    paid_referrals = ChampionshipReferral.objects.filter(campaign=campaign, registration_state__in=['paid', 'active'])
    digital_paid_count = paid_referrals.filter(referred_agent__plan_type='basic').count()
    prof_paid_count = paid_referrals.filter(referred_agent__plan_type='professional').count()
    other_paid_count = paid_referrals.count() - (digital_paid_count + prof_paid_count)

    pricing = campaign.pricing_config or {}
    dig_price = Decimal(str(pricing.get('digital', {}).get('campaign_price', 999)))
    prof_price = Decimal(str(pricing.get('professional', {}).get('campaign_price', 4999)))

    gross_revenue = (digital_paid_count * dig_price) + (prof_paid_count * prof_price) + (other_paid_count * dig_price)
    
    refunded_count = ChampionshipReferral.objects.filter(campaign=campaign, registration_state='refunded').count()
    refund_amount = refunded_count * dig_price
    net_revenue = gross_revenue - refund_amount

    # Reward Liability
    claims = ChampionshipRewardClaim.objects.filter(reward_slab__campaign=campaign)
    potential_liability = Decimal('0.00')
    current_liability = Decimal('0.00')
    rewards_issued = Decimal('0.00')

    for slab in campaign.reward_slabs.filter(is_active=True):
        # Qualified participants who achieved this threshold
        qualified_agents = ChampionshipParticipant.objects.filter(
            campaign=campaign,
            qualifying_referrals_count__gte=slab.threshold
        ).count()
        potential_liability += qualified_agents * slab.value

    for c in claims:
        if c.status in ['approved', 'processing']:
            current_liability += c.reward_slab.value
        elif c.status in ['dispatched', 'delivered', 'redeemed']:
            rewards_issued += c.reward_slab.value

    # Campaign Financial Health Status
    if net_revenue > (potential_liability * Decimal('1.5')):
        health_status = 'SAFE'
        health_color = 'success'
    elif net_revenue >= potential_liability:
        health_status = 'WATCH'
        health_color = 'warning'
    else:
        health_status = 'LIMIT EXCEEDED'
        health_color = 'danger'

    # Stats
    total_participants = ChampionshipParticipant.objects.filter(campaign=campaign).count()
    total_qualifying = ChampionshipReferral.objects.filter(campaign=campaign, is_qualifying=True).count()
    fraud_flags_count = ChampionshipFraudFlag.objects.filter(participant__campaign=campaign, status='flagged').count()

    context = {
        'campaign': campaign,
        'gross_revenue': gross_revenue,
        'refund_amount': refund_amount,
        'net_revenue': net_revenue,
        'digital_paid_count': digital_paid_count,
        'prof_paid_count': prof_paid_count,
        'potential_liability': potential_liability,
        'current_liability': current_liability,
        'rewards_issued': rewards_issued,
        'health_status': health_status,
        'health_color': health_color,
        'total_participants': total_participants,
        'total_qualifying': total_qualifying,
        'fraud_flags_count': fraud_flags_count,
        'slabs': campaign.reward_slabs.all().order_by('threshold'),
        'recent_claims': claims.select_related('participant', 'participant__agent', 'reward_slab')[:15],
    }
    return render(request, 'referral_championship/admin/dashboard.html', context)


@require_POST
def admin_update_campaign_settings(request):
    """Update campaign status, pricing, unlock rules, and social/review settings."""
    if not _is_authorized_admin(request):
        return JsonResponse({'success': False, 'message': 'Unauthorized'}, status=401)

    campaign = ChampionshipCampaign.get_current()
    old_state = {
        'status': campaign.status,
        'pricing': campaign.pricing_config,
        'unlock': campaign.unlock_config,
        'google_url': campaign.google_review_url,
    }

    status = request.POST.get('status', campaign.status)
    if status in ['draft', 'scheduled', 'live', 'paused', 'ended', 'archived']:
        campaign.status = status

    # Pricing updates
    try:
        dig_reg = int(request.POST.get('digital_regular_price', 1999))
        dig_camp = int(request.POST.get('digital_campaign_price', 999))
        dig_ren = int(request.POST.get('digital_renewal_price', 1999))
        prof_reg = int(request.POST.get('prof_regular_price', 9999))
        prof_camp = int(request.POST.get('prof_campaign_price', 4999))
        prof_ren = int(request.POST.get('prof_renewal_price', 9999))

        campaign.pricing_config = {
            "digital": {"regular_price": dig_reg, "campaign_price": dig_camp, "renewal_price": dig_ren, "name": "Starter's Plan"},
            "professional": {"regular_price": prof_reg, "campaign_price": prof_camp, "renewal_price": prof_ren, "name": "Professional's Plan"},
            "discount_percent": 50
        }
    except Exception as e:
        logger.warning(f"Error parsing pricing config: {e}")

    # Unlock updates
    try:
        min_prof = int(request.POST.get('min_profile_percent', 80))
        min_rev = int(request.POST.get('min_reviews', 10))
        campaign.unlock_config = {
            "min_profile_percent": min_prof,
            "min_reviews": min_rev
        }
    except Exception:
        pass

    campaign.google_review_url = request.POST.get('google_review_url', campaign.google_review_url)

    # Social channels update
    ig_url = request.POST.get('instagram_url', 'https://instagram.com/padosiagent')
    fb_url = request.POST.get('facebook_url', 'https://facebook.com/padosiagent')
    campaign.social_channels = [
        {"platform": "instagram", "name": "Instagram", "url": ig_url, "icon": "fa-instagram"},
        {"platform": "facebook", "name": "Facebook", "url": fb_url, "icon": "fa-facebook-f"}
    ]

    campaign.save()

    # Audit log
    admin_info = _get_admin_from_session(request)
    admin_id = admin_info if isinstance(admin_info, (int, str)) else (admin_info.get('id') if isinstance(admin_info, dict) else getattr(admin_info, 'id', admin_info))
    ChampionshipAuditLog.objects.create(
        campaign=campaign,
        admin_user=request.user if request.user.is_authenticated else None,
        action="Campaign Settings Updated",
        old_value=old_state,
        new_value={
            'status': campaign.status,
            'pricing': campaign.pricing_config,
            'unlock': campaign.unlock_config,
            'google_url': campaign.google_review_url
        },
        reason=f"Admin #{admin_id} updated campaign configuration."
    )

    messages.success(request, "Referral Championship settings updated successfully!")
    return redirect('/admin/championship/')


@require_POST
def admin_manage_reward_slab(request):
    """Add or edit a reward slab."""
    if not _is_authorized_admin(request):
        return JsonResponse({'success': False, 'message': 'Unauthorized'}, status=401)

    campaign = ChampionshipCampaign.get_current()
    slab_id = request.POST.get('slab_id')
    threshold = int(request.POST.get('threshold', 5))
    title = request.POST.get('title', '').strip()
    description = request.POST.get('description', '').strip()
    reward_type = request.POST.get('reward_type', 'custom')
    badge_icon = request.POST.get('badge_icon', 'fa-gift')
    value = Decimal(str(request.POST.get('value', '0.00')))
    winner_limit = int(request.POST.get('winner_limit', 0))
    is_active = request.POST.get('is_active') == '1'

    if slab_id:
        slab = get_object_or_404(ChampionshipRewardSlab, id=slab_id, campaign=campaign)
        slab.threshold = threshold
        slab.title = title
        slab.description = description
        slab.reward_type = reward_type
        slab.badge_icon = badge_icon
        slab.value = value
        slab.winner_limit = winner_limit
        slab.is_active = is_active
        slab.save()
        messages.success(request, f'Reward slab "{slab.title}" updated!')
    else:
        ChampionshipRewardSlab.objects.create(
            campaign=campaign,
            threshold=threshold,
            title=title,
            description=description,
            reward_type=reward_type,
            badge_icon=badge_icon,
            value=value,
            winner_limit=winner_limit,
            is_active=is_active
        )
        messages.success(request, f'New reward slab "{title}" created!')

    return redirect('/admin/championship/#rewards')


def admin_leaderboard_view(request):
    """View and export full championship leaderboard."""
    if not _is_authorized_admin(request):
        return redirect('/admin/login/')

    campaign = ChampionshipCampaign.get_current()
    query = request.GET.get('q', '').strip()
    city_filter = request.GET.get('city', '').strip()

    participants = ChampionshipParticipant.objects.filter(campaign=campaign).select_related('agent')
    if query:
        participants = participants.filter(
            Q(agent__fullname__icontains=query) |
            Q(agent__email__icontains=query) |
            Q(referral_id__icontains=query)
        )

    participants = participants.order_by('current_rank', '-qualifying_referrals_count')

    # CSV Export
    if request.GET.get('export') == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="championship_leaderboard_{timezone.now().strftime("%Y%m%d")}.csv"'
        writer = csv.writer(response)
        writer.writerow(['Rank', 'Referral ID', 'Agent Name', 'Email', 'Mobile', 'Qualifying Referrals', 'Unlocked'])
        for p in participants:
            writer.writerow([
                p.current_rank,
                p.referral_id,
                p.agent.fullname,
                p.agent.email,
                p.agent.mobile,
                p.qualifying_referrals_count,
                'Yes' if p.is_unlocked else 'No'
            ])
        return response

    context = {
        'campaign': campaign,
        'participants': participants[:100],
        'total_count': participants.count(),
        'query': query,
    }
    return render(request, 'referral_championship/admin/leaderboard.html', context)


@require_POST
def admin_freeze_leaderboard(request):
    """Freeze or unfreeze the leaderboard."""
    if not _is_authorized_admin(request):
        return JsonResponse({'success': False, 'message': 'Unauthorized'}, status=401)

    freeze = request.POST.get('freeze') == '1'
    campaign = ChampionshipCampaign.get_current()
    ChampionshipLeaderboardCache.objects.filter(campaign=campaign).update(is_frozen=freeze)
    
    status_text = "frozen" if freeze else "unfrozen"
    messages.success(request, f"Leaderboard has been {status_text}.")
    return redirect('/admin/championship/leaderboard/')


def admin_referral_tree_view(request):
    """Visual hierarchical view of referrers and attributed agents."""
    if not _is_authorized_admin(request):
        return redirect('/admin/login/')

    campaign = ChampionshipCampaign.get_current()
    top_referrers = ChampionshipParticipant.objects.filter(
        campaign=campaign,
        qualifying_referrals_count__gt=0
    ).select_related('agent').prefetch_related('referrals', 'referrals__referred_agent')[:30]

    context = {
        'campaign': campaign,
        'top_referrers': top_referrers,
    }
    return render(request, 'referral_championship/admin/referral_tree.html', context)


def admin_fraud_control_view(request):
    """View and resolve fraud flags."""
    if not _is_authorized_admin(request):
        return redirect('/admin/login/')

    flags = ChampionshipFraudFlag.objects.all().select_related('participant', 'participant__agent').order_by('-created_at')
    context = {
        'flags': flags,
    }
    return render(request, 'referral_championship/admin/fraud_control.html', context)


@require_POST
def admin_resolve_fraud_flag(request, flag_id):
    """Take action on a fraud flag (block, reverse, restore, reject)."""
    if not _is_authorized_admin(request):
        return JsonResponse({'success': False, 'message': 'Unauthorized'}, status=401)

    flag = get_object_or_404(ChampionshipFraudFlag, id=flag_id)
    action = request.POST.get('action') # 'block', 'restore', 'reverse'

    if action == 'block':
        flag.status = 'blocked'
        flag.participant.is_fraud_blocked = True
        flag.participant.save()
        messages.warning(request, f"Participant {flag.participant.referral_id} has been blocked.")
    elif action == 'restore':
        flag.status = 'restored'
        flag.participant.is_fraud_blocked = False
        flag.participant.save()
        messages.success(request, f"Participant {flag.participant.referral_id} restored.")
    elif action == 'reverse':
        flag.status = 'reversed'
        if flag.referral:
            from apps.referral_championship.services.qualification_service import revert_championship_qualification
            if flag.referral.referred_agent:
                revert_championship_qualification(flag.referral.referred_agent, reason="fraud")
        messages.info(request, "Referral credit reversed.")

    flag.save()
    refresh_leaderboard_cache(flag.participant.campaign)
    return redirect('/admin/championship/fraud/')
