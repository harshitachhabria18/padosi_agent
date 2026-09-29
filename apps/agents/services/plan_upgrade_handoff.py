"""Consume a one-time app upgrade link and resolve the website plan to open."""
from datetime import datetime

from django.db import transaction

from apps.agents.models import PlanUpgradeHandoff
from plan_upgrade_handoff import (
    ALLOWED_UPGRADE_SLUGS,
    hash_handoff_token,
    normalize_upgrade_slug,
    upgrade_target_allowed,
)


def consume_plan_upgrade_handoff(raw_token):
    """
    Mark a valid unused token as used and return the row.

    Returns None for a missing, expired, reused, or malformed token.
    The raw token is never written to the database or logs.
    """
    raw = (raw_token or '').strip()
    if not raw or len(raw) > 128:
        return None

    now = datetime.now()
    with transaction.atomic():
        row = (
            PlanUpgradeHandoff.objects.select_for_update()
            .filter(token_hash=hash_handoff_token(raw), used_at__isnull=True, expires_at__gt=now)
            .select_related('agent')
            .first()
        )
        if row is None:
            return None
        row.used_at = now
        row.save(update_fields=['used_at'])
        if row.plan_slug not in ALLOWED_UPGRADE_SLUGS or not row.agent_id:
            return None
        return row


def dashboard_upgrade_slug(agent, raw_upgrade):
    """Plan slug the dashboard should open, or '' when the query is not an upgrade."""
    if not agent:
        return ''
    target = normalize_upgrade_slug(raw_upgrade)
    if not upgrade_target_allowed(getattr(agent, 'plan_type', ''), target):
        return ''
    return target
