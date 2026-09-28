"""Track referred agents and count qualifying Razorpay payments."""
import logging
from datetime import datetime

from django.db import transaction

from apps.agents.services.account_auth import is_real_razorpay_id
from apps.event_referral.models import EventReferral, EventReferralParticipant
from apps.event_referral.services.participant_service import evaluate_participant

logger = logging.getLogger(__name__)

EV_PREFIX = 'EV-'


def is_event_referral_code(code):
    return bool(code) and str(code).strip().upper().startswith(EV_PREFIX)


def _participant_for_code(code):
    code_val = str(code).strip().upper()
    return EventReferralParticipant.objects.filter(referral_code=code_val).first()


def _city_for_agent(agent):
    pin = getattr(agent, 'agent_pincode', '') or ''
    draft = getattr(agent, 'registration_draft', None) or {}
    state = ''
    if isinstance(draft, dict):
        state = draft.get('state') or ''
    if pin and state:
        return f'{pin}, {state}'
    return pin or state or ''


def _fraud_reject(participant, referred_agent, reason):
    ref_row, _ = EventReferral.objects.get_or_create(
        participant=participant,
        referred_agent=referred_agent,
        defaults={
            'state': EventReferral.STATE_REJECTED,
            'registered_at': datetime.now(),
            'snapshot_name': referred_agent.fullname or '',
            'snapshot_email': referred_agent.email or '',
            'snapshot_mobile': referred_agent.mobile or '',
            'snapshot_city': _city_for_agent(referred_agent),
            'reject_reason': reason,
        },
    )
    if ref_row.state != EventReferral.STATE_REJECTED:
        ref_row.state = EventReferral.STATE_REJECTED
        ref_row.counts = False
        ref_row.reject_reason = reason
        ref_row.save()
    return ref_row


def register_referred_agent(referred_agent):
    """Upsert a registered row when a referred agent record exists."""
    if not referred_agent or not is_event_referral_code(referred_agent.referred_by_code):
        return None
    participant = _participant_for_code(referred_agent.referred_by_code)
    if not participant:
        return None
    if participant.agent_id == referred_agent.id:
        _fraud_reject(participant, referred_agent, 'Self-referral')
        return None
    referrer = participant.agent
    if referrer and referred_agent.email and referrer.email:
        if referred_agent.email.lower() == referrer.email.lower():
            _fraud_reject(participant, referred_agent, 'Same email as referrer')
            return None
    if referrer and referred_agent.mobile and referrer.mobile:
        ref_m = ''.join(c for c in str(referrer.mobile) if c.isdigit())[-10:]
        new_m = ''.join(c for c in str(referred_agent.mobile) if c.isdigit())[-10:]
        if ref_m and new_m and ref_m == new_m:
            _fraud_reject(participant, referred_agent, 'Same mobile as referrer')
            return None

    now = datetime.now()
    ref_row, created = EventReferral.objects.get_or_create(
        participant=participant,
        referred_agent=referred_agent,
        defaults={
            'state': EventReferral.STATE_REGISTERED,
            'registered_at': now,
            'snapshot_name': referred_agent.fullname or '',
            'snapshot_email': referred_agent.email or '',
            'snapshot_mobile': referred_agent.mobile or '',
            'snapshot_city': _city_for_agent(referred_agent),
            'snapshot_plan': referred_agent.plan_type or '',
            'snapshot_payment_status': 'pending',
        },
    )
    if not created and ref_row.state == EventReferral.STATE_REGISTERED:
        ref_row.snapshot_name = referred_agent.fullname or ref_row.snapshot_name
        ref_row.snapshot_plan = referred_agent.plan_type or ref_row.snapshot_plan
        ref_row.save(update_fields=['snapshot_name', 'snapshot_plan', 'updated_at'])
    return ref_row


def qualify_event_referral(referred_agent, subscription):
    """Count a paid referral after Razorpay capture (idempotent)."""
    if not referred_agent or not subscription:
        return
    if getattr(subscription, 'payment_status', '') != 'completed':
        return
    pay_id = getattr(subscription, 'razorpay_payment_id', '') or ''
    order_id = getattr(subscription, 'razorpay_order_id', '') or ''
    if not is_real_razorpay_id(pay_id, 'pay_') and not is_real_razorpay_id(order_id, 'order_'):
        return
    if not is_event_referral_code(referred_agent.referred_by_code):
        return

    participant = _participant_for_code(referred_agent.referred_by_code)
    if not participant:
        return
    if participant.agent_id == referred_agent.id:
        return

    register_referred_agent(referred_agent)
    paid_at = datetime.now()

    with transaction.atomic():
        participant = (
            EventReferralParticipant.objects.select_for_update()
            .filter(pk=participant.pk)
            .first()
        )
        if not participant or participant.status == EventReferralParticipant.STATUS_BLOCKED:
            return
        if participant.status == EventReferralParticipant.STATUS_WON:
            return

        ref_row = (
            EventReferral.objects.select_for_update()
            .filter(participant=participant, referred_agent=referred_agent)
            .first()
        )
        if not ref_row:
            ref_row = EventReferral.objects.create(
                participant=participant,
                referred_agent=referred_agent,
                state=EventReferral.STATE_REGISTERED,
                registered_at=paid_at,
                snapshot_name=referred_agent.fullname or '',
                snapshot_email=referred_agent.email or '',
                snapshot_mobile=referred_agent.mobile or '',
                snapshot_city=_city_for_agent(referred_agent),
            )

        if ref_row.state == EventReferral.STATE_PAID and ref_row.counts:
            return

        plan_slug = referred_agent.plan_type or ''
        ref_row.snapshot_plan = plan_slug
        ref_row.snapshot_payment_status = 'completed'
        ref_row.paid_at = paid_at
        ref_row.state = EventReferral.STATE_PAID

        if paid_at <= participant.deadline_at:
            ref_row.counts = True
        else:
            ref_row.counts = False
            ref_row.reject_reason = 'Payment after referrer deadline'
        ref_row.save()

        participant.paid_count = EventReferral.objects.filter(
            participant=participant,
            counts=True,
            state=EventReferral.STATE_PAID,
        ).count()
        participant.save(update_fields=['paid_count', 'updated_at'])

    evaluate_participant(participant)


def revert_event_referral(referred_agent, reason='refund'):
    """Drop a referral from the count if referrer has not won yet."""
    if not referred_agent:
        return
    ref_row = EventReferral.objects.filter(referred_agent=referred_agent, counts=True).select_related(
        'participant',
    ).first()
    if not ref_row:
        ref_row = EventReferral.objects.filter(referred_agent=referred_agent).select_related(
            'participant',
        ).first()
    if not ref_row:
        return
    participant = ref_row.participant
    if participant.status == EventReferralParticipant.STATUS_WON:
        ref_row.state = EventReferral.STATE_REFUNDED
        ref_row.counts = False
        ref_row.save(update_fields=['state', 'counts', 'updated_at'])
        return

    with transaction.atomic():
        participant = EventReferralParticipant.objects.select_for_update().get(pk=participant.pk)
        ref_row = EventReferral.objects.select_for_update().get(pk=ref_row.pk)
        ref_row.state = EventReferral.STATE_REFUNDED
        ref_row.counts = False
        ref_row.reject_reason = reason
        ref_row.save()
        participant.paid_count = EventReferral.objects.filter(
            participant=participant,
            counts=True,
            state=EventReferral.STATE_PAID,
        ).count()
        participant.save(update_fields=['paid_count', 'updated_at'])
