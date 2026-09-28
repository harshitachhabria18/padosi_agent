import json
import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.referral_championship.models import (
    ChampionshipCampaign,
    ChampionshipParticipant,
    ChampionshipSocialAction,
    ChampionshipScratchUnlock,
    ChampionshipGoogleReviewLog,
    ChampionshipReferral,
    ChampionshipRewardSlab,
)
from apps.agents.models import Agent
from apps.agents.services.og_urls import build_og_absolute_url
from apps.referral_championship.services.attribution_service import bind_referral_session
from apps.referral_championship.services.og_meta import championship_og_context
from apps.agents.services.review_growth import agent_review_count

logger = logging.getLogger(__name__)


def referral_landing_page(request, ref_id):
    """
    Public Referral Landing Page:
    - Displays Referring Agent Card (Photo, Name, Verified, City, Categories, Rating).
    - 3-Step 50% Discount Unlock (Follow -> Scratch 25% -> 50% Unlocked).
    - Non-conditional Google Review Card.
    - CTA to Join PadosiAgent.
    """
    ref_id = str(ref_id).strip().upper()
    campaign = ChampionshipCampaign.get_current()

    participant = ChampionshipParticipant.objects.filter(
        referral_id=ref_id,
        campaign=campaign
    ).first()

    if not participant:
        participant = ChampionshipParticipant.objects.filter(campaign=campaign).first()
        if not participant:
            agent = Agent.objects.first()
            if agent:
                from apps.referral_championship.services.attribution_service import get_or_create_participant
                participant = get_or_create_participant(agent, campaign)

    if not participant:
        return redirect(reverse('agents:agent_registration'))

    # Lock attribution in visitor session
    bind_referral_session(request, ref_id)

    # Log visitor referral entry in 'started' state
    session_key = request.session.session_key or request.session.save() or request.session.session_key
    utm_source = request.GET.get('utm_source', '')
    utm_medium = request.GET.get('utm_medium', '')
    utm_campaign = request.GET.get('utm_campaign', '')

    ChampionshipReferral.objects.get_or_create(
        campaign=campaign,
        referrer=participant,
        session_id=session_key,
        referral_id=participant.referral_id,
        defaults={
            'registration_state': 'started',
            'utm_params': {'source': utm_source, 'medium': utm_medium, 'campaign': utm_campaign},
        }
    )

    referring_agent = participant.agent
    profile = referring_agent.get_primary_profile() if hasattr(referring_agent, 'get_primary_profile') else getattr(referring_agent, 'profile', None)

    # Categories
    categories = []
    if profile:
        services_list = getattr(profile, 'desired_services', None) or getattr(profile, 'investment_types', None)
        if isinstance(services_list, list):
            categories = [str(s).strip().title() for s in services_list if str(s).strip()][:4]
    if not categories:
        categories = ['Life Insurance', 'Health Insurance', 'Motor Insurance']

    # Rating & Reviews
    review_count = agent_review_count(referring_agent)
    average_rating = round(float(getattr(referring_agent, 'average_rating', 5.0) or 5.0), 1)

    # Social progress for this session
    session_id = request.session.session_key or 'anon_guest'
    followed_platforms = list(ChampionshipSocialAction.objects.filter(
        session_id=session_id
    ).values_list('platform', flat=True))

    scratch_rec = ChampionshipScratchUnlock.objects.filter(session_id=session_id).first()
    is_scratched = bool(scratch_rec and scratch_rec.is_revealed)
    is_50_unlocked = bool(is_scratched and len(followed_platforms) >= 1)

    pricing = campaign.pricing_config or {}
    digital_cfg = pricing.get('digital', {'regular_price': 1999, 'campaign_price': 999})
    pro_cfg = pricing.get('professional', {'regular_price': 9999, 'campaign_price': 4999})

    # Log Google Review prompt shown
    ChampionshipGoogleReviewLog.objects.get_or_create(
        session_id=session_id,
        defaults={'ip_address': request.META.get('REMOTE_ADDR')}
    )

    # Rewards slabs and draws for preview
    slabs = ChampionshipRewardSlab.objects.filter(campaign=campaign, is_active=True).order_by('threshold')
    from apps.referral_championship.services.leaderboard_service import get_leaderboard_data
    leaderboard_preview = get_leaderboard_data(campaign, limit=10)

    draws = [
        {'tier': 1, 'prize_name': 'Gold & Tech Goodies', 'eligibility': '50+ referrals', 'winner_count': 5},
        {'tier': 2, 'prize_name': 'Domestic Trip Upgrade', 'eligibility': '100+ referrals', 'winner_count': 3},
        {'tier': 3, 'prize_name': 'Mega International Luxury Draw', 'eligibility': '200+ referrals', 'winner_count': 1},
    ]

    context = {
        'campaign': campaign,
        'participant': participant,
        'referring_agent': referring_agent,
        'profile': profile,
        'categories': categories,
        'review_count': review_count,
        'average_rating': average_rating,
        'followed_platforms': followed_platforms,
        'is_scratched': is_scratched,
        'is_50_unlocked': is_50_unlocked,
        'digital_cfg': digital_cfg,
        'pro_cfg': pro_cfg,
        'slabs': slabs,
        'draws': draws,
        'leaderboard_preview': leaderboard_preview,
        'social_channels': campaign.social_channels or [
            {"platform": "instagram", "name": "Instagram", "url": "https://instagram.com/padosiagent", "icon": "fa-instagram"},
            {"platform": "facebook", "name": "Facebook", "url": "https://facebook.com/padosiagent", "icon": "fa-facebook-f"}
        ],
        'google_review_url': campaign.google_review_url or "https://g.page/r/padosiagent/review",
        'reg_url': f"{reverse('agents:agent_registration')}?ref={ref_id}&campaign={campaign.slug}",
    }
    ref_name = getattr(referring_agent, 'fullname', None) or getattr(referring_agent, 'full_name', None)
    context.update(championship_og_context(request, referring_agent_name=ref_name))
    context['og_page_absolute_url'] = build_og_absolute_url(request, request.get_full_path())
    return render(request, 'referral_championship/landing.html', context)


@require_POST
def record_social_follow_ajax(request):
    """AJAX endpoint for Step 1: Record social channel follow."""
    try:
        data = json.loads(request.body)
        platform = data.get('platform', '').strip().lower()
    except Exception:
        platform = request.POST.get('platform', '').strip().lower()

    if not platform:
        return JsonResponse({'success': False, 'message': 'Platform required'}, status=400)

    session_id = request.session.session_key or request.session.save() or request.session.session_key
    ChampionshipSocialAction.objects.get_or_create(
        session_id=session_id,
        platform=platform
    )

    followed = list(ChampionshipSocialAction.objects.filter(session_id=session_id).values_list('platform', flat=True))
    scratch_rec = ChampionshipScratchUnlock.objects.filter(session_id=session_id).first()
    is_50_unlocked = bool(scratch_rec and scratch_rec.is_revealed and len(followed) >= 1)

    return JsonResponse({
        'success': True,
        'followed_platforms': followed,
        'is_50_unlocked': is_50_unlocked,
        'message': f'Thank you for following us on {platform.title()}!'
    })


@require_POST
def record_scratch_reveal_ajax(request):
    """AJAX endpoint for Step 2: Record scratch reveal (25% revealed)."""
    session_id = request.session.session_key or request.session.save() or request.session.session_key
    scratch, _ = ChampionshipScratchUnlock.objects.get_or_create(
        session_id=session_id,
        defaults={'is_revealed': True, 'revealed_discount_pct': 25, 'final_unlocked_pct': 50}
    )
    scratch.is_revealed = True
    scratch.save()

    followed = list(ChampionshipSocialAction.objects.filter(session_id=session_id).values_list('platform', flat=True))
    is_50_unlocked = len(followed) >= 1

    return JsonResponse({
        'success': True,
        'revealed': True,
        'discount_revealed': 25,
        'is_50_unlocked': is_50_unlocked,
        'message': '25% OFF Revealed! Complete social follow to unlock 50% Campaign Pricing!' if not is_50_unlocked else '50% OFF UNLOCKED 🎉'
    })


@require_POST
def track_google_review_ajax(request):
    """Track non-conditional Google review button click."""
    session_id = request.session.session_key or 'anon'
    ChampionshipGoogleReviewLog.objects.filter(session_id=session_id).update(
        link_clicked_at=timezone.now()
    )
    return JsonResponse({'success': True})


def championship_og_image(request, ref_id=None):
    """Serve the high-res Agent Championship promotional OG image."""
    import os
    from django.conf import settings
    from django.http import HttpResponse, Http404

    champ_img_path = os.path.join(settings.BASE_DIR, 'static', 'img', 'championship_og.jpg')
    if os.path.exists(champ_img_path):
        with open(champ_img_path, 'rb') as f:
            content = f.read()
        response = HttpResponse(content, content_type="image/jpeg")
        response["Cache-Control"] = "public, max-age=604800"
        response["Access-Control-Allow-Origin"] = "*"
        return response
    raise Http404("Championship OG image not found")
