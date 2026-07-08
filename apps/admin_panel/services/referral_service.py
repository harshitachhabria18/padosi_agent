"""
apps/admin_panel/services/referral_service.py

Shared Referral Service — canonical single source of truth.

All tier logic, referral code generation, referral crediting, and reward
assignment flow through this module.  Both the Testing Module and the organic
Registration hook call these helpers so the business rules are NEVER duplicated.

Tier table (Django canonical — consistent across all surfaces):
    5  referrals  → discount_25   / 25%  upgrade discount
    10 referrals  → discount_50   / 50%  upgrade discount
    15 referrals  → pro_plan_1rs  / 100% upgrade discount (Pro @ ₹1)
"""

import random
import re
import string

from django.db import connection


# ─────────────────────────────────────────────────────────────────────────────
#  TIER TABLE  — ONE place, never duplicated
# ─────────────────────────────────────────────────────────────────────────────

REFERRAL_TIERS = [
    {'min': 5,  'max': 9,       'reward': 'discount_25',  'discount': 25},
    {'min': 10, 'max': 14,      'reward': 'discount_50',  'discount': 50},
    {'min': 15, 'max': 9999999, 'reward': 'pro_plan_1rs', 'discount': 100},
]


def get_tier_for_count(total_referrals: int) -> dict | None:
    """
    Return the highest tier the agent has reached, or None if below Tier 1.

    Mirrors ReferralCode::currentTier() from Laravel but uses the Django
    canonical 5/10/15 milestones everywhere.
    """
    tier = None
    for t in REFERRAL_TIERS:
        if total_referrals >= t['min']:
            tier = t
    return tier


def get_next_tier(total_referrals: int) -> dict | None:
    """Return the next tier the agent has not yet reached, or None if maxed."""
    for t in REFERRAL_TIERS:
        if total_referrals < t['min']:
            return t
    return None


# ─────────────────────────────────────────────────────────────────────────────
#  REFERRAL CODE GENERATION  — mirrors ReferralCode::generateForAgent()
# ─────────────────────────────────────────────────────────────────────────────

def generate_referral_code_for_agent(cursor, agent_id: int, agent_fullname: str) -> dict:
    """
    Lookup or generate a referral code for the given agent using the Laravel
    algorithm exactly:
        base = first 4 uppercase alphanumeric chars of fullname (fallback 'REF')
        code = base + 4 random uppercase alphanumeric chars (loop until unique)

    Returns the referral code row dict: {id, code, total_referrals, ...}
    Caller must pass an already-open cursor (inside a transaction).
    """
    cursor.execute(
        "SELECT id, code, total_referrals, is_active, reward_type, reward_claimed "
        "FROM referral_codes WHERE agent_id = %s LIMIT 1",
        [agent_id],
    )
    row = cursor.fetchone()
    if row:
        cols = ['id', 'code', 'total_referrals', 'is_active', 'reward_type', 'reward_claimed']
        return dict(zip(cols, row))

    # Generate new code using Laravel algorithm
    clean_name = re.sub(r'[^A-Z0-9]', '', (agent_fullname or '').upper())
    base = clean_name[:4]
    if len(base) < 2:
        base = 'REF'

    for _ in range(50):
        candidate = base + ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
        cursor.execute("SELECT COUNT(*) FROM referral_codes WHERE code = %s", [candidate])
        if cursor.fetchone()[0] == 0:
            break

    cursor.execute(
        """
        INSERT INTO referral_codes
            (agent_id, code, is_active, total_referrals, pending_referrals,
             clicks, reward_claimed, created_at, updated_at)
        VALUES (%s, %s, 1, 0, 0, 0, 0, NOW(), NOW())
        """,
        [agent_id, candidate],
    )

    cursor.execute(
        "SELECT id, code, total_referrals, is_active, reward_type, reward_claimed "
        "FROM referral_codes WHERE agent_id = %s LIMIT 1",
        [agent_id],
    )
    row = cursor.fetchone()
    cols = ['id', 'code', 'total_referrals', 'is_active', 'reward_type', 'reward_claimed']
    return dict(zip(cols, row))


# ─────────────────────────────────────────────────────────────────────────────
#  APPLY REWARD  — update agents + referral_codes tables based on tier
# ─────────────────────────────────────────────────────────────────────────────

def apply_tier_reward(cursor, agent_id: int, ref_code_id: int, total_referrals: int) -> dict | None:
    """
    Calculate the current tier and, if a tier is reached, write the reward to:
        agents.referral_reward_type
        agents.upgrade_discount_percent
        referral_codes.reward_type

    Returns the tier dict if a tier was applied, None otherwise.
    Caller must pass an already-open cursor (inside a transaction).
    """
    tier = get_tier_for_count(total_referrals)
    if not tier:
        return None

    cursor.execute(
        """
        UPDATE agents
        SET referral_reward_type = %s,
            upgrade_discount_percent = %s,
            updated_at = NOW()
        WHERE id = %s
        """,
        [tier['reward'], tier['discount'], agent_id],
    )
    cursor.execute(
        """
        UPDATE referral_codes
        SET reward_type = %s, updated_at = NOW()
        WHERE id = %s
        """,
        [tier['reward'], ref_code_id],
    )
    return tier


# ─────────────────────────────────────────────────────────────────────────────
#  CREDIT REFERRAL  — core hook called after successful registration
# ─────────────────────────────────────────────────────────────────────────────

def credit_referral(cursor, referred_agent_id: int, referred_agent_name: str, referred_by_code: str) -> bool:
    """
    Credit the referring agent when a new agent completes registration.

    Mirrors AgentRegistrationService::creditReferral() from Laravel but uses
    the Django canonical tier table (5/10/15) instead of Laravel's broken >=5
    hardcode.

    Steps:
      1. Lookup referral_code by code string.
      2. firstOrCreate referral_usage (duplicate prevention).
      3. If already converted → skip (idempotent).
      4. Mark usage as converted.
      5. Recount converted usages for accuracy (mirrors Laravel sync).
      6. Update referral_codes.total_referrals.
      7. Apply tier reward if threshold crossed.

    Returns True if the credit was applied, False if skipped.
    Caller must pass an already-open cursor (inside a transaction).
    """
    if not referred_by_code:
        return False

    cursor.execute(
        "SELECT id, agent_id, total_referrals FROM referral_codes WHERE code = %s LIMIT 1",
        [referred_by_code],
    )
    code_row = cursor.fetchone()
    if not code_row:
        return False

    ref_code_id, referrer_agent_id, _ = code_row

    # firstOrNew behaviour — check for existing usage
    cursor.execute(
        "SELECT id, status FROM referral_usages "
        "WHERE referral_code_id = %s AND referred_agent_id = %s LIMIT 1",
        [ref_code_id, referred_agent_id],
    )
    usage_row = cursor.fetchone()

    if usage_row:
        usage_id, usage_status = usage_row
        if usage_status == 'converted':
            return False  # Already credited — idempotent
        # Update existing pending → converted
        cursor.execute(
            """
            UPDATE referral_usages
            SET status = 'converted', converted_at = NOW(), updated_at = NOW()
            WHERE id = %s
            """,
            [usage_id],
        )
    else:
        cursor.execute(
            """
            INSERT INTO referral_usages
                (referral_code_id, referrer_agent_id, referred_agent_id,
                 referred_agent_name, status, converted_at, created_at, updated_at)
            VALUES (%s, %s, %s, %s, 'converted', NOW(), NOW(), NOW())
            """,
            [ref_code_id, referrer_agent_id, referred_agent_id, referred_agent_name],
        )

    # Recount converted usages (mirrors Laravel's accuracy sync)
    cursor.execute(
        "SELECT COUNT(*) FROM referral_usages "
        "WHERE referral_code_id = %s AND status = 'converted'",
        [ref_code_id],
    )
    active_count = cursor.fetchone()[0]

    cursor.execute(
        "UPDATE referral_codes SET total_referrals = %s, updated_at = NOW() WHERE id = %s",
        [active_count, ref_code_id],
    )

    apply_tier_reward(cursor, referrer_agent_id, ref_code_id, active_count)
    return True
