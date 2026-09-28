"""Evaluate deadlines, wins, blocks, and dashboard access for event referral challengers."""
import logging
from datetime import datetime

from django.db import transaction

from apps.agents.models import Agent
from apps.event_referral.models import EventReferral, EventReferralParticipant

logger = logging.getLogger(__name__)

BLOCK_MESSAGE = (
    'Your event referral challenge ended. You did not complete the required paid '
    'referrals in time. Please contact support if you need help.'
)


def get_participant_for_agent(agent):
    if not agent:
        return None
    return (
        EventReferralParticipant.objects.filter(agent=agent)
        .select_related('campaign')
        .first()
    )


def event_referral_grants_dashboard(agent):
    """Allow dashboard without Razorpay for active challengers and winners."""
    participant = get_participant_for_agent(agent)
    if not participant:
        return False
    if participant.status == EventReferralParticipant.STATUS_BLOCKED:
        return False
    if participant.status in (
        EventReferralParticipant.STATUS_ACTIVE,
        EventReferralParticipant.STATUS_WON,
    ):
        return True
    return False


def force_lock_all_dashboard_features(participant):
    return (
        participant is not None
        and participant.status == EventReferralParticipant.STATUS_ACTIVE
    )


def _recount_paid(participant):
    return EventReferral.objects.filter(
        participant=participant,
        counts=True,
        state=EventReferral.STATE_PAID,
    ).count()


def _grant_win(participant):
    agent = participant.agent
    plan = participant.reward_plan_slug or 'basic'
    participant.status = EventReferralParticipant.STATUS_WON
    participant.won_at = datetime.now()
    participant.paid_count = _recount_paid(participant)
    participant.save(
        update_fields=['status', 'won_at', 'paid_count', 'updated_at'],
    )
    agent.status = 'pending_approval'
    agent.plan_type = plan
    agent.registration_step = max(agent.registration_step or 1, 2)
    agent.save(update_fields=['status', 'plan_type', 'registration_step', 'updated_at'])
    logger.info(
        'Event referral win: agent #%s participant %s plan=%s',
        agent.id,
        participant.referral_code,
        plan,
    )


def _block_participant(participant, reason=''):
    participant.status = EventReferralParticipant.STATUS_BLOCKED
    participant.blocked_at = datetime.now()
    participant.blocked_reason = reason or 'Deadline passed without enough paid referrals.'
    participant.save(
        update_fields=['status', 'blocked_at', 'blocked_reason', 'updated_at'],
    )
    agent = participant.agent
    agent.status = 'suspended'
    agent.save(update_fields=['status', 'updated_at'])
    logger.info(
        'Event referral blocked: agent #%s participant %s',
        agent.id,
        participant.referral_code,
    )


def evaluate_participant(participant, *, block_on_expire=True):
    """
    Check win/loss for one participant. Returns participant (refreshed) or None.
    """
    if not participant:
        return None
    with transaction.atomic():
        participant = (
            EventReferralParticipant.objects.select_for_update()
            .select_related('agent')
            .filter(pk=participant.pk)
            .first()
        )
        if not participant:
            return None
        if participant.status == EventReferralParticipant.STATUS_WON:
            return participant
        if participant.status == EventReferralParticipant.STATUS_BLOCKED:
            return participant

        participant.paid_count = _recount_paid(participant)
        participant.save(update_fields=['paid_count', 'updated_at'])

        if participant.paid_count >= participant.required_paid_referrals:
            _grant_win(participant)
            return participant

        now = datetime.now()
        if block_on_expire and now >= participant.deadline_at:
            _block_participant(
                participant,
                reason=(
                    f'Required {participant.required_paid_referrals} paid referrals '
                    f'within {participant.window_hours} hours were not completed.'
                ),
            )
            return participant

        return participant


def evaluate_agent(agent, *, block_on_expire=True):
    participant = get_participant_for_agent(agent)
    if not participant:
        return None
    return evaluate_participant(participant, block_on_expire=block_on_expire)


def admin_grant_win(participant):
    """Manual grant from admin."""
    with transaction.atomic():
        participant = EventReferralParticipant.objects.select_for_update().get(pk=participant.pk)
        if participant.status != EventReferralParticipant.STATUS_WON:
            _grant_win(participant)
    participant.refresh_from_db()
    return participant


def admin_restore_participant(participant, *, extend_hours=0):
    with transaction.atomic():
        participant = EventReferralParticipant.objects.select_for_update().get(pk=participant.pk)
        agent = Agent.objects.select_for_update().get(pk=participant.agent_id)
        if extend_hours:
            from datetime import timedelta
            participant.deadline_at = participant.deadline_at + timedelta(hours=int(extend_hours))
        participant.status = EventReferralParticipant.STATUS_ACTIVE
        participant.blocked_at = None
        participant.blocked_reason = ''
        participant.save()
        if agent.status == 'suspended' and agent.plan_type in ('', 'basic', 'starter'):
            agent.status = 'event_challenge' if not agent.plan_type else 'pending_approval'
            agent.save(update_fields=['status', 'updated_at'])
    participant.refresh_from_db()
    return participant
