"""
apps/admin_panel/views/referrals.py

Admin Referral Analytics & Management.
Mirrors AdminFreeTrialController::referrals() and related methods from Laravel.

Routes:
    GET  /admin/referrals/                          → admin_referrals_index
    POST /admin/referrals/toggle-code/              → admin_referrals_toggle_code   (AJAX JSON)
    POST /admin/referrals/<id>/mark-claimed/        → admin_referrals_mark_claimed
    POST /admin/referrals/generate-missing-codes/   → admin_referrals_generate_missing
    POST /admin/referrals/update-tiers/             → admin_referrals_update_tiers
"""

import json
import random
import string

from django.contrib import messages
from django.db import connection, transaction
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from .dashboard import _get_admin_from_session
from ..services.referral_service import (
    REFERRAL_TIERS,
    generate_referral_code_for_agent,
    apply_tier_reward,
    get_tier_for_count,
)


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _dict_from_cursor(cursor):
    cols = [col[0] for col in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


def _log_activity(admin_id, description, model_type='AdminAction', model_id=None):
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO admin_activity_logs
                    (admin_id, description, model_type, model_id, created_at, updated_at)
                VALUES (%s, %s, %s, %s, NOW(), NOW())
                """,
                [admin_id, description, model_type, model_id],
            )
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN PAGE  GET /admin/referrals/
# ─────────────────────────────────────────────────────────────────────────────

@require_http_methods(["GET"])
def admin_referrals_index(request):
    admin = _get_admin_from_session(request)
    if not admin:
        return redirect('admin_login_page')

    search       = request.GET.get('search', '').strip()
    plan_filter  = request.GET.get('plan_type', '').strip()
    reward_filter = request.GET.get('reward_status', '').strip()
    status_filter = request.GET.get('status', '').strip()
    page_num     = max(1, int(request.GET.get('page', 1)))
    per_page     = 20

    with connection.cursor() as cursor:
        # ── Global KPI Stats ──
        cursor.execute("SELECT COUNT(*) FROM referral_codes")
        total_codes = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM referral_codes WHERE is_active = 1")
        active_codes = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM referral_usages")
        total_signups = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM referral_usages WHERE status = 'converted'")
        converted = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM referral_usages WHERE status != 'converted'")
        pending = cursor.fetchone()[0]

        conv_rate = round((converted / total_signups * 100), 1) if total_signups > 0 else 0

        cursor.execute("SELECT COUNT(*) FROM referral_codes WHERE reward_type = 'discount_25'")
        rewards_25pct = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM referral_codes WHERE reward_type = 'discount_50'")
        rewards_50pct = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM referral_codes WHERE reward_type = 'pro_plan_1rs'")
        rewards_pro1rs = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(*) FROM referral_codes "
            "WHERE reward_type IS NOT NULL AND reward_claimed = 0"
        )
        unclaimed = cursor.fetchone()[0]

        stats = {
            'total_codes':    total_codes,
            'active_codes':   active_codes,
            'total_signups':  total_signups,
            'converted':      converted,
            'pending':        pending,
            'conv_rate':      conv_rate,
            'rewards_25pct':  rewards_25pct,
            'rewards_50pct':  rewards_50pct,
            'rewards_pro1rs': rewards_pro1rs,
            'unclaimed':      unclaimed,
        }

        # ── Plan breakdown of converted referred agents ──
        cursor.execute("""
            SELECT a.plan_type, COUNT(*) as cnt
            FROM referral_usages ru
            JOIN agents a ON a.id = ru.referred_agent_id
            WHERE ru.status = 'converted'
            GROUP BY a.plan_type
        """)
        plan_breakdown = _dict_from_cursor(cursor)

        # Compute total_plan = sum of all cnt values (matches Laravel's $planBreakdown->sum('cnt'))
        total_plan = sum(row['cnt'] for row in plan_breakdown)
        for row in plan_breakdown:
            row['pct'] = round((row['cnt'] / total_plan) * 100) if total_plan > 0 else 0

        # ── Build WHERE clauses for agent codes query ──
        where_parts = []
        params = []

        if search:
            where_parts.append("""
                (rc.code LIKE %s
                 OR a.fullname LIKE %s
                 OR a.email LIKE %s
                 OR a.mobile LIKE %s)
            """)
            like = f'%{search}%'
            params += [like, like, like, like]

        if plan_filter == 'free_trial':
            where_parts.append("a.plan_type = 'free_trial'")
        elif plan_filter == 'paid':
            where_parts.append("a.plan_type != 'free_trial'")

        if reward_filter == 'none':
            where_parts.append("rc.reward_type IS NULL")
        elif reward_filter == 'unclaimed':
            where_parts.append("rc.reward_type IS NOT NULL AND rc.reward_claimed = 0")
        elif reward_filter == 'claimed':
            where_parts.append("rc.reward_claimed = 1")

        if status_filter == 'active':
            where_parts.append("rc.is_active = 1")
        elif status_filter == 'inactive':
            where_parts.append("rc.is_active = 0")

        where_sql = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

        # ── Count total for pagination ──
        cursor.execute(f"""
            SELECT COUNT(*)
            FROM referral_codes rc
            LEFT JOIN agents a ON a.id = rc.agent_id
            {where_sql}
        """, params)
        total_codes_filtered = cursor.fetchone()[0]
        total_pages = max(1, (total_codes_filtered + per_page - 1) // per_page)
        offset = (page_num - 1) * per_page

        # ── Agent codes with full detail ──
        cursor.execute(f"""
            SELECT rc.id, rc.agent_id, rc.code, rc.is_active, rc.total_referrals,
                   rc.pending_referrals, rc.clicks, rc.reward_type,
                   rc.reward_claimed, rc.reward_claimed_at, rc.created_at,
                   a.fullname, a.email, a.mobile, a.plan_type, a.status as agent_status
            FROM referral_codes rc
            LEFT JOIN agents a ON a.id = rc.agent_id
            {where_sql}
            ORDER BY rc.total_referrals DESC
            LIMIT %s OFFSET %s
        """, params + [per_page, offset])
        all_codes = _dict_from_cursor(cursor)

        # ── Per-code: load referred agents ──
        code_ids = [c['id'] for c in all_codes]
        referred_map = {}
        if code_ids:
            placeholders = ','.join(['%s'] * len(code_ids))
            cursor.execute(f"""
                SELECT ru.id, ru.referral_code_id, ru.referred_agent_id,
                       ru.referred_agent_name, ru.status, ru.converted_at, ru.created_at,
                       a.fullname as ref_fullname, a.email as ref_email,
                       a.plan_type as ref_plan_type, a.status as ref_status,
                       a.created_at as ref_created_at
                FROM referral_usages ru
                LEFT JOIN agents a ON a.id = ru.referred_agent_id
                WHERE ru.referral_code_id IN ({placeholders})
                ORDER BY ru.created_at DESC
            """, code_ids)
            for row in _dict_from_cursor(cursor):
                cid = row['referral_code_id']
                referred_map.setdefault(cid, []).append(row)

        # ── Recent activity feed (last 30) ──
        cursor.execute("""
            SELECT ru.id, ru.referred_agent_name, ru.status, ru.created_at,
                   ru.converted_at,
                   a_ref.fullname  as referred_fullname,
                   a_ref.plan_type as referred_plan_type,
                   a_ref.status    as referred_status,
                   a_rer.fullname  as referrer_fullname
            FROM referral_usages ru
            LEFT JOIN agents a_ref ON a_ref.id = ru.referred_agent_id
            LEFT JOIN agents a_rer ON a_rer.id = ru.referrer_agent_id
            ORDER BY ru.created_at DESC
            LIMIT 30
        """)
        recent_usages = _dict_from_cursor(cursor)

    # Build pagination object
    pagination = {
        'current_page':  page_num,
        'total_pages':   total_pages,
        'total_items':   total_codes_filtered,
        'has_prev':      page_num > 1,
        'has_next':      page_num < total_pages,
        'prev_page':     page_num - 1,
        'next_page':     page_num + 1,
        'page_range':    range(max(1, page_num - 2), min(total_pages + 1, page_num + 3)),
    }

    # Attach referred usages and tier labels to each code
    for code in all_codes:
        code['usages']    = referred_map.get(code['id'], [])
        code['converted'] = sum(1 for u in code['usages'] if u['status'] == 'converted')
        code['pending_c'] = sum(1 for u in code['usages'] if u['status'] != 'converted')
        tier = get_tier_for_count(code['total_referrals'] or 0)
        code['tier'] = tier

    return render(request, 'admin/referrals/index.html', {
        'stats':         stats,
        'all_codes':     all_codes,
        'recent_usages': recent_usages,
        'plan_breakdown': plan_breakdown,
        'pagination':    pagination,
        'tiers':         REFERRAL_TIERS,
        # Filter echo-back
        'search':        search,
        'plan_filter':   plan_filter,
        'reward_filter': reward_filter,
        'status_filter': status_filter,
    })


# ─────────────────────────────────────────────────────────────────────────────
#  TOGGLE CODE  POST /admin/referrals/toggle-code/  (AJAX JSON)
# ─────────────────────────────────────────────────────────────────────────────

@require_http_methods(["POST"])
def admin_referrals_toggle_code(request):
    admin = _get_admin_from_session(request)
    if not admin:
        return JsonResponse({'success': False, 'error': 'Unauthorized'}, status=401)

    try:
        body = json.loads(request.body)
        code_id = int(body.get('id', 0))
    except (json.JSONDecodeError, ValueError, TypeError):
        return JsonResponse({'success': False, 'error': 'Invalid payload'}, status=400)

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT id, is_active FROM referral_codes WHERE id = %s LIMIT 1",
            [code_id],
        )
        row = cursor.fetchone()
        if not row:
            return JsonResponse({'success': False, 'error': 'Not found'}, status=404)

        new_status = 0 if row[1] else 1
        cursor.execute(
            "UPDATE referral_codes SET is_active = %s, updated_at = NOW() WHERE id = %s",
            [new_status, code_id],
        )

    return JsonResponse({'success': True, 'is_active': bool(new_status)})


# ─────────────────────────────────────────────────────────────────────────────
#  MARK CLAIMED  POST /admin/referrals/<id>/mark-claimed/
# ─────────────────────────────────────────────────────────────────────────────

@require_http_methods(["POST"])
def admin_referrals_mark_claimed(request, code_id):
    admin = _get_admin_from_session(request)
    if not admin:
        return redirect('admin_login_page')

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT id, agent_id FROM referral_codes WHERE id = %s LIMIT 1",
            [code_id],
        )
        row = cursor.fetchone()
        if not row:
            messages.error(request, 'Referral code not found.')
            return redirect('admin_referrals_index')

        agent_id = row[1]
        cursor.execute(
            """
            UPDATE referral_codes
            SET reward_claimed = 1, reward_claimed_at = NOW(), updated_at = NOW()
            WHERE id = %s
            """,
            [code_id],
        )

    _log_activity(
        admin,
        f"Mark referral reward claimed for agent #{agent_id}",
        'ReferralCode',
        code_id,
    )
    messages.success(request, 'Reward marked as claimed.')
    return redirect('admin_referrals_index')


# ─────────────────────────────────────────────────────────────────────────────
#  GENERATE MISSING CODES  POST /admin/referrals/generate-missing-codes/
# ─────────────────────────────────────────────────────────────────────────────

@require_http_methods(["POST"])
def admin_referrals_generate_missing(request):
    admin = _get_admin_from_session(request)
    if not admin:
        return redirect('admin_login_page')

    count = 0
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT id, fullname FROM agents WHERE status = 'active'"
        )
        agents = _dict_from_cursor(cursor)

        for agent in agents:
            cursor.execute(
                "SELECT COUNT(*) FROM referral_codes WHERE agent_id = %s",
                [agent['id']],
            )
            if cursor.fetchone()[0] == 0:
                generate_referral_code_for_agent(cursor, agent['id'], agent['fullname'])
                count += 1

    _log_activity(admin, f"Generated {count} missing referral codes for active agents.", 'ReferralCode')
    messages.success(request, f'Generated {count} missing referral codes for active agents.')
    return redirect('admin_referrals_index')


# ─────────────────────────────────────────────────────────────────────────────
#  UPDATE TIERS  POST /admin/referrals/update-tiers/
#  Mirrors AdminFreeTrialController::updateReferralTiers()
# ─────────────────────────────────────────────────────────────────────────────

@require_http_methods(["POST"])
def admin_referrals_update_tiers(request):
    admin = _get_admin_from_session(request)
    if not admin:
        return redirect('admin_login_page')

    config = {
        'tier1_min':    int(request.POST.get('tier1_min', 5)),
        'tier1_reward': 'discount_25',
        'tier2_min':    int(request.POST.get('tier2_min', 10)),
        'tier2_reward': 'discount_50',
        'tier3_min':    int(request.POST.get('tier3_min', 15)),
        'tier3_reward': 'pro_plan_1rs',
    }

    with connection.cursor() as cursor:
        cursor.execute("""
            INSERT INTO site_settings (`key`, `value`, `group`, created_at, updated_at)
            VALUES ('referral_tier_config', %s, 'referral', NOW(), NOW())
            ON DUPLICATE KEY UPDATE `value` = VALUES(`value`), updated_at = NOW()
        """, [__import__('json').dumps(config)])

    _log_activity(admin, 'Update referral tier config', 'SiteSetting')
    messages.success(request, 'Referral tier configuration updated.')
    return redirect('admin_referrals_index')
