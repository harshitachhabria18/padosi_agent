"""Issue a short-lived website URL that opens this agent's plan upgrade."""
from datetime import datetime, timedelta

from fastapi import HTTPException, status

from fastapi_app.config import settings
from fastapi_app.models.plan_upgrade_handoff import PlanUpgradeHandoff
from plan_upgrade_handoff import (
    ALLOWED_UPGRADE_SLUGS,
    HANDOFF_TTL_SECONDS,
    build_handoff_url,
    handoff_expiry,
    hash_handoff_token,
    new_handoff_token,
    normalize_upgrade_slug,
    upgrade_target_allowed,
)

MAX_HANDOFFS_PER_MINUTE = 5


def issue_plan_upgrade_handoff(db, agent, plan_slug: str) -> dict:
    target = normalize_upgrade_slug(plan_slug)
    if target not in ALLOWED_UPGRADE_SLUGS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Choose Starter or Professional to upgrade.",
        )
    if not upgrade_target_allowed(getattr(agent, "plan_type", ""), target):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You are already on this plan or a higher plan.",
        )

    now = datetime.now()
    recent = (
        db.query(PlanUpgradeHandoff)
        .filter(
            PlanUpgradeHandoff.agent_id == agent.id,
            PlanUpgradeHandoff.created_at >= now - timedelta(seconds=60),
        )
        .count()
    )
    if recent >= MAX_HANDOFFS_PER_MINUTE:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many upgrade attempts. Please wait a minute and try again.",
        )

    raw = new_handoff_token()
    db.add(PlanUpgradeHandoff(
        token_hash=hash_handoff_token(raw),
        agent_id=agent.id,
        plan_slug=target,
        expires_at=handoff_expiry(now),
        created_at=now,
    ))
    db.commit()
    return {
        "success": True,
        "url": build_handoff_url(settings.APP_URL, raw),
        "expires_in": HANDOFF_TTL_SECONDS,
        "plan_slug": target,
    }
