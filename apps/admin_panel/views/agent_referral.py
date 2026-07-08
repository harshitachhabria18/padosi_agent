"""
apps/admin_panel/views/agent_referral.py

Agent-facing Referral Dashboard.
Mirrors AgentDashboardController::referral() from Laravel.

Routes (registered in padosiagent/urls.py):
    GET /join/<code>/               → referral_join   (capture code in session → redirect to registration)
    GET /agent/referral/            → agent_referral_dashboard
"""

import urllib.parse
from django.db import connection, transaction
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from ..services.referral_service import (
    REFERRAL_TIERS,
    generate_referral_code_for_agent,
    get_tier_for_count,
    get_next_tier,
    credit_referral,
)
from ..services.site_settings import get_setting


def _dict_from_cursor(cursor):
    cols = [col[0] for col in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


# ─────────────────────────────────────────────────────────────────────────────
#  REFERRAL JOIN  GET /join/<code>/
#  Mirrors the Route::get('/join/{refCode}', ...) closure in Laravel web.php
# ─────────────────────────────────────────────────────────────────────────────

def referral_join(request, ref_code):
    code_upper = ref_code.upper()

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT id, code FROM referral_codes WHERE code = %s AND is_active = 1 LIMIT 1",
            [code_upper],
        )
        row = cursor.fetchone()
        if row:
            # Increment clicks
            cursor.execute(
                "UPDATE referral_codes SET clicks = clicks + 1, updated_at = NOW() WHERE id = %s",
                [row[0]],
            )
            # Store in session (mirrors: session(['ref_code' => $code->code]))
            request.session['ref_code'] = code_upper

    # Redirect to agent registration with query params matching Laravel
    return redirect(f'/?ref={code_upper}&show_trial=1')


# ─────────────────────────────────────────────────────────────────────────────
#  AGENT REFERRAL DASHBOARD  GET /agent/referral/
#  Mirrors AgentDashboardController::referral()
# ─────────────────────────────────────────────────────────────────────────────

@require_http_methods(["GET"])
def agent_referral_dashboard(request):
    agent_id = request.session.get('current_agent_id')
    if not agent_id:
        return redirect('/')

    with connection.cursor() as cursor:
        # Load agent
        cursor.execute(
            "SELECT id, fullname, email, plan_type, referred_by_code FROM agents WHERE id = %s LIMIT 1",
            [agent_id],
        )
        agent_row = cursor.fetchone()
        if not agent_row:
            return redirect('/')
        agent = {
            'id':               agent_row[0],
            'fullname':         agent_row[1],
            'email':            agent_row[2],
            'plan_type':        agent_row[3],
            'referred_by_code': agent_row[4],
        }

        # Check referral eligibility (mirrors $showReferral logic)
        referral_config = get_setting('referral_config', {'eligibility': 'free_trial_only'})
        eligibility = referral_config.get('eligibility', 'free_trial_only')
        show_referral = (eligibility == 'all' or agent['plan_type'] == 'free_trial')
        if not show_referral:
            # Redirect to agent dashboard with error
            return redirect('/')

        # Load or generate referral code
        ref = generate_referral_code_for_agent(cursor, agent['id'], agent['fullname'])
        ref_code_id  = ref['id']
        ref_code_str = ref['code']

        # Auto-sync total_referrals (mirrors Laravel's accuracy sync on page load)
        cursor.execute(
            "SELECT COUNT(*) FROM referral_usages WHERE referral_code_id = %s AND status = 'converted'",
            [ref_code_id],
        )
        actual_conversions = cursor.fetchone()[0]

        if ref.get('total_referrals') != actual_conversions:
            cursor.execute(
                "UPDATE referral_codes SET total_referrals = %s, updated_at = NOW() WHERE id = %s",
                [actual_conversions, ref_code_id],
            )
            ref['total_referrals'] = actual_conversions

        # Count pending referrals
        cursor.execute(
            "SELECT COUNT(*) FROM referral_usages WHERE referral_code_id = %s AND status != 'converted'",
            [ref_code_id],
        )
        pending_count = cursor.fetchone()[0]

        # Load referred agents with their plan & status
        cursor.execute(
            """
            SELECT ru.id, ru.referred_agent_name, ru.status, ru.converted_at, ru.created_at,
                   a.fullname as ref_fullname, a.email as ref_email,
                   a.plan_type as ref_plan_type, a.status as ref_status
            FROM referral_usages ru
            LEFT JOIN agents a ON a.id = ru.referred_agent_id
            WHERE ru.referral_code_id = %s
            ORDER BY ru.created_at DESC
            """,
            [ref_code_id],
        )
        referred_agents = _dict_from_cursor(cursor)

    # Build referral URL (mirrors route('referral.join', ['refCode' => $refCode->code]))
    base_url = request.build_absolute_uri('/').rstrip('/')
    referral_url = f"{base_url}/join/{ref_code_str}/"

    # Tier calculations
    total_referrals = ref['total_referrals']
    current_tier    = get_tier_for_count(total_referrals)
    next_tier_obj   = get_next_tier(total_referrals)

    # Progress bar calculation (mirrors Blade logic)
    if next_tier_obj:
        next_target = next_tier_obj['min']
        prev_min = 0
        for t in REFERRAL_TIERS:
            if t['min'] < next_target:
                prev_min = t['min']
        raw_pct = 0
        span = next_target - prev_min
        if span > 0 and total_referrals >= prev_min:
            raw_pct = round(((total_referrals - prev_min) / span) * 100)
        progress_pct    = min(100, max(0, raw_pct))
        progress_label  = f"{total_referrals} / {next_target} conversions"
        next_goal_text  = f"{next_target - total_referrals} more to unlock next tier!"
    else:
        progress_pct   = 100
        progress_label = f"{total_referrals} / 15 ✓"
        next_goal_text = "🎉 All tiers unlocked! Claim your reward when upgrading."

    # Current tier label (mirrors Blade $tierLabel)
    tier_label = 'None Yet 🏅'
    if current_tier:
        rw = current_tier.get('reward', '')
        if rw == 'pro_plan_1rs':
            tier_label = 'Tier 3: Pro @ ₹1 🥇'
        elif rw == 'discount_50':
            tier_label = 'Tier 2: 50% OFF 🥈'
        elif rw == 'discount_25':
            tier_label = 'Tier 1: 25% OFF 🥉'

    # WhatsApp & Email share messages (mirrors Blade pre-filled messages)
    wa_message = (
        f"🚀 I've already started my digital growth journey with PadosiAgent and the response is amazing.\n\n"
        f"Now it's your turn.\n\n"
        f"As my contact, you get SPECIAL TRIAL ACCESS just at ₹99 for 30 days.\n"
        f"(No Promo Code required).\n\n"
        f"👉 Click below & register:\n{referral_url}\n\n"
        f"Once you're in, you'll understand why smart agents are shifting online."
    )
    wa_url      = f"https://wa.me/?text={urllib.parse.quote(wa_message)}"
    email_sub   = urllib.parse.quote("Special Invitation: Join PadosiAgent Digital Growth")
    email_body  = urllib.parse.quote(wa_message)
    email_url   = f"mailto:?subject={email_sub}&body={email_body}"

    return render(request, 'agent/referral.html', {
        'agent':            agent,
        'ref_code':         ref_code_str,
        'referral_url':     referral_url,
        'total_referrals':  total_referrals,
        'actual_conversions': actual_conversions,
        'pending_count':    pending_count,
        'clicks':           ref.get('clicks', 0),
        'referred_agents':  referred_agents,
        'current_tier':     current_tier,
        'next_tier':        next_tier_obj,
        'tier_label':       tier_label,
        'progress_pct':     progress_pct,
        'progress_label':   progress_label,
        'next_goal_text':   next_goal_text,
        'wa_url':           wa_url,
        'email_url':        email_url,
        'tiers':            REFERRAL_TIERS,
    })
