"""Complete event referral registration after the shared agent registration form (step 1)."""
import logging
import re

from django.db import transaction
from django.http import JsonResponse
from django.urls import reverse

from apps.agents.models import Agent
from apps.event_referral.models import EventReferralCampaign, EventReferralParticipant

logger = logging.getLogger(__name__)


def _normalize_mobile(raw):
    digits = re.sub(r'\D', '', str(raw or ''))
    if len(digits) == 12 and digits.startswith('91'):
        digits = digits[2:]
    return digits if len(digits) == 10 else ''


def finalize_event_referral_registration(request, draft):
    """
    Create event_challenge agent from draft, participant row, login, redirect dashboard.
    Called from register_step1 when session event_referral_registration is set.
    """
    from apps.agents.views.registration import (
        _email_belongs_to_portal_account,
        create_agent_from_draft,
        create_or_link_django_user,
    )
    from apps.agents.services.razorpay_checkout import login_agent_user

    campaign = EventReferralCampaign.get_current()
    if not campaign.is_enabled:
        return JsonResponse(
            {'success': False, 'message': 'Event registration is currently closed.'},
            status=403,
        )

    email = (draft.email or '').strip().lower()
    if _email_belongs_to_portal_account(email):
        return JsonResponse(
            {
                'success': False,
                'message': 'This email is already registered. Please log in instead.',
                'redirect': reverse('agents:agent_login'),
            },
            status=422,
        )

    existing = Agent.objects.filter(email__iexact=email).first()
    if existing and existing.status not in ('event_challenge', 'incomplete', 'pending_payment'):
        if existing.status in ('active', 'pending_approval', 'pending_accounts_payment'):
            return JsonResponse(
                {
                    'success': False,
                    'message': f'You are already registered with {email}. Please login.',
                    'redirect': reverse('agents:agent_login'),
                },
                status=422,
            )

    mobile = _normalize_mobile(draft.mobile)
    if not mobile:
        return JsonResponse(
            {'success': False, 'message': 'Valid 10-digit mobile is required.'},
            status=400,
        )

    try:
        with transaction.atomic():
            agent = create_agent_from_draft(
                draft,
                plan_type='',
                plan_name='Event Referral Challenge',
                status='event_challenge',
            )
            if draft.state:
                agent.registration_draft = {'state': draft.state}
                agent.save(update_fields=['registration_draft', 'updated_at'])

            if not EventReferralParticipant.objects.filter(agent=agent).exists():
                EventReferralParticipant.create_for_agent(agent, campaign=campaign)

            from apps.event_referral.services.paldi_event import assign_paldi_event_to_agent
            assign_paldi_event_to_agent(agent)

            user = create_or_link_django_user(agent, plain_password=mobile)
    except Exception as exc:
        logger.exception('Event referral finalize failed for %s: %s', email, exc)
        return JsonResponse(
            {'success': False, 'message': 'Registration failed. Please try again.'},
            status=500,
        )

    try:
        from apps.agents.models import RegistrationActivityLog
        RegistrationActivityLog.log(
            RegistrationActivityLog.EVENT_FORM_SUBMIT,
            request=request,
            agent=agent,
            draft_id=draft.pk,
            extra_details={'event': 'Paldi', 'source': 'paldi_event_registration'},
        )
        RegistrationActivityLog.log(
            RegistrationActivityLog.EVENT_PENDING_REGISTRATION,
            request=request,
            agent=agent,
            draft_id=draft.pk,
            extra_details={'event': 'Paldi', 'status': agent.status, 'source': 'paldi_event_registration'},
        )
    except Exception as exc:
        logger.warning('Paldi registration activity log failed: %s', exc)

    try:
        from apps.agents.services.brevo import email_service
        from apps.event_referral.constants import PALDI_REGISTRATION_TITLE
        email_service.send_welcome(
            email,
            draft.fullname or email,
            mobile,
            PALDI_REGISTRATION_TITLE,
            attachment_path=None,
            subject='Welcome to Paldi — your PadosiAgent login details',
        )
    except Exception as exc:
        logger.warning('Event welcome email failed: %s', exc)

    login_agent_user(request, user)
    request.session.pop('event_referral_registration', None)
    request.session.pop('current_draft_id', None)
    request.session.pop('reg_step', None)
    request.session['suppress_review_share_popup'] = True
    request.session['event_referral_welcome_dashboard'] = True
    request.session.modified = True

    participant = EventReferralParticipant.objects.filter(agent=agent).first()
    target = participant.required_paid_referrals if participant else campaign.required_paid_referrals

    return JsonResponse(
        {
            'success': True,
            'message': (
                f'Account created! We emailed your login details to {email}. '
                f'Refer {target} paying agents before the timer ends to unlock your Basic plan.'
            ),
            'redirect': reverse('agents:agent_dashboard'),
        },
    )
