import logging
from datetime import datetime

from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from apps.agents.models import Agent
from apps.event_referral.constants import PALDI_EVENT_NAME, PALDI_OG_TITLE
from apps.event_referral.services.og_meta import paldi_og_context
from apps.event_referral.services.public_leaderboard import get_public_leaderboard_payload

logger = logging.getLogger(__name__)

SEGMENT_MAP = {
    'health': {'name': 'Health', 'cls': 'seg-health'},
    'life': {'name': 'Life', 'cls': 'seg-life'},
    'motor': {'name': 'Motor', 'cls': 'seg-motor'},
    'sme': {'name': 'SME', 'cls': 'seg-sme'},
}


def _profile_photo_absolute(request, profile):
    try:
        rel = profile.profile_photo_url
        if not rel:
            return ''
        if str(rel).startswith(('http://', 'https://')):
            return rel
        return request.build_absolute_uri(rel)
    except Exception:
        return ''


def _format_referrals(count):
    val = int(count or 0)
    if val >= 10:
        return '10+'
    return str(val)


@require_http_methods(['GET'])
def public_leaderboard(request):
    """
    Public live board for event stall screens — ranked by counted paid EV- referrals.
    Uses 100% original database data without any dummy data.
    """
    payload = get_public_leaderboard_payload(
        limit=50,
        photo_url_builder=lambda p: _profile_photo_absolute(request, p),
    )
    rows = payload.get('leaderboard') or []

    # Enrich original database rows with all required fields
    for idx, row in enumerate(rows):
        rank = row.get('rank') or (idx + 1)
        row['rank'] = rank
        row['rank_display'] = f"{rank:02d}" if rank < 10 else str(rank)

        # Referrals display: up to 10; if >= 10, show '10+'
        paid_count = int(row.get('paid_count') or 0)
        row['paid_count'] = paid_count
        row['referrals_display'] = _format_referrals(paid_count)

        # Status
        row['status_display'] = 'Active'

        # Fetch Agent for segments and profile URL
        agent_id = row.get('agent_id')
        agent = None
        if agent_id:
            agent = Agent.objects.filter(id=agent_id).prefetch_related('insuranceSegments').first()

        segments = []
        profile_url = ''
        if agent:
            try:
                raw_segments = agent.ordered_insurance_segments or []
                for s in raw_segments:
                    s_key = str(s).lower().strip()
                    if s_key in SEGMENT_MAP:
                        segments.append(SEGMENT_MAP[s_key])
                    elif s_key:
                        segments.append({'name': s_key.capitalize(), 'cls': 'seg-default'})
            except Exception:
                segments = []

            try:
                profile = agent.get_primary_profile()
                if profile and getattr(profile, 'slug', None):
                    profile_url = reverse('agents:agent_public_profile', kwargs={'slug': profile.slug})
                else:
                    profile_url = f"/profile/{agent.id}/"
            except Exception:
                profile_url = f"/profile/{agent.id}/" if agent else ''

        if not segments:
            segments = [{'name': 'General', 'cls': 'seg-default'}]

        row['segments'] = segments
        row['profile_url'] = profile_url

    context = {
        **payload,
        'leaders': rows,
        'podium_first': rows[0] if len(rows) > 0 else None,
        'podium_second': rows[1] if len(rows) > 1 else None,
        'podium_third': rows[2] if len(rows) > 2 else None,
        'visible_rest': rows[3:15],
        'rest_agents': rows[3:],
        'paldi_event_name': PALDI_EVENT_NAME,
        'page_title': 'Top Performers of the Event | PadosiAgent',
        'current_year': datetime.now().year,
        'hide_site_nav': True,
        'hide_footer': True,
        'hide_chatbot': True,
        'hide_header': True,
    }
    context.update(paldi_og_context(request))
    context['og_share_title'] = 'Top Performers of the Event - Stall Leaderboard | PadosiAgent'
    context.setdefault('og_page_title', 'Top Performers of the Event | PadosiAgent')
    return render(request, 'event_referral/public_leaderboard.html', context)
