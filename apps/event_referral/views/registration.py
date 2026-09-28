import logging

from django.contrib import messages
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from apps.event_referral.models import EventReferralCampaign

logger = logging.getLogger(__name__)


@require_http_methods(['GET'])
def event_registration(request):
    """Same UI as /agent-registration/ — completes to event referral dashboard."""
    campaign = EventReferralCampaign.get_current()

    if request.user.is_authenticated:
        from apps.agents.services.account_auth import agent_can_access_dashboard, resolve_agent_for_user
        agent = resolve_agent_for_user(request.user)
        if agent and agent_can_access_dashboard(agent):
            return redirect('agents:agent_dashboard')

    if campaign.is_enabled:
        request.session['event_referral_registration'] = True
    else:
        request.session.pop('event_referral_registration', None)
    request.session.modified = True

    from apps.agents.views.registration import _get_registration_context
    from apps.event_referral.services.og_meta import paldi_og_context

    context = _get_registration_context(request)
    context.update(
        {
            'event_referral_mode': True,
            'event_referral_campaign': campaign,
            'registration_closed': not campaign.is_enabled,
            'register_step1_url': reverse('agents:agent_register_step1'),
            'hide_header': True,
        },
    )
    context.update(paldi_og_context(request))
    if not campaign.is_enabled:
        messages.warning(request, 'Event registration is currently closed.')

    return render(request, 'agents/registration.html', context)
