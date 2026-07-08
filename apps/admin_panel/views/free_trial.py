"""
apps/admin_panel/views/free_trial.py

Free Trial Manager — 100% Laravel parity.
Laravel source: app/Http/Controllers/Admin/AdminFreeTrialController.php

Routes implemented:
  GET  /padosi-admin/free-trial/                   → free_trial_index
  POST /padosi-admin/free-trial/update-config/     → ft_update_trial_config
  POST /padosi-admin/free-trial/update-discount/   → ft_update_upgrade_discount
  POST /padosi-admin/free-trial/update-referral-config/ → ft_update_referral_config
  POST /padosi-admin/free-trial/generate-promo/    → ft_generate_promo
  POST /padosi-admin/free-trial/promo/<id>/update/ → ft_update_promo
  POST /padosi-admin/free-trial/toggle-promo/      → ft_toggle_promo   (AJAX)
  POST /padosi-admin/free-trial/promo/<id>/delete/ → ft_delete_promo
  GET  /padosi-admin/free-trial/history/           → ft_history         (AJAX JSON)
  GET  /padosi-admin/free-trial/analytics-data/    → ft_analytics_data  (AJAX JSON)
"""

from django.db import transaction
import json
import random
import string
from datetime import datetime, timezone
from django.utils import timezone as django_timezone

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .dashboard import _get_admin_from_session
from ..services.site_settings import get_setting, set_setting
from ..services.referral_service import (
    REFERRAL_TIERS,
    get_tier_for_count,
    generate_referral_code_for_agent,
    apply_tier_reward,
)

# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_TRIAL_CONFIG = {
    'price': 99,
    'duration_days': 30,
    'badge': 'TRIAL',
    'description': 'Try before you commit — 30 days full access',
    'is_active': True,
}


def _dict_from_cursor(cursor):
    """Return list of dicts from a cursor with column names."""
    cols = [col[0] for col in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


def _generate_unique_code(prefix='TRIAL'):
    """Generate a unique promo code with given prefix + 6 random chars."""
    with connection.cursor() as cursor:
        for _ in range(20):
            suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
            code = prefix.upper() + suffix
            cursor.execute("SELECT id FROM promo_codes WHERE code = %s", [code])
            if not cursor.fetchone():
                return code
    return prefix.upper() + ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))


def _log_activity(admin_id, description, model_type='AdminAction', model_id=None):
    """Insert a row into admin_activity_logs exactly as Laravel's AdminActivityLog::log()."""
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
        pass  # Non-fatal — never crash a request because of logging


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN PAGE  (GET /padosi-admin/free-trial/)
# ─────────────────────────────────────────────────────────────────────────────

@require_http_methods(["GET"])
def free_trial_index(request):
    admin = _get_admin_from_session(request)
    if not admin:
        return redirect('admin_login_page')

    trial_config     = get_setting('trial_plan_config', DEFAULT_TRIAL_CONFIG)
    upgrade_discount = get_setting('trial_upgrade_discount', 20)
    referral_config  = get_setting('referral_config', {'eligibility': 'free_trial_only', 'count_free_trial': False})

    with connection.cursor() as cursor:

        # ── Trial Promo Codes (is_free_trial = 1) ──────────────────────────
        cursor.execute("""
            SELECT id, code, discount_type, discount_value, is_active, is_free_trial,
                   trial_plan_name, trial_duration_days, trial_price_override, notes,
                   max_uses, times_used, expires_at, applicable_plan, created_at
            FROM promo_codes
            WHERE is_free_trial = 1
            ORDER BY created_at DESC
        """)
        trial_promo_codes = _dict_from_cursor(cursor)

        # ── Active Trial Agents (plan_type = 'free_trial') ─────────────────
        cursor.execute("""
            SELECT id, fullname, email, mobile, trial_ends_at, upgrade_discount_percent
            FROM agents
            WHERE plan_type = 'free_trial'
            ORDER BY trial_ends_at DESC
            LIMIT 100
        """)
        active_agents = _dict_from_cursor(cursor)

        now_dt = django_timezone.now()
        for a in active_agents:
            end_dt = a.get('trial_ends_at')
            if end_dt:
                from django.conf import settings
                if getattr(settings, 'USE_TZ', False):
                    if django_timezone.is_naive(end_dt):
                        end_dt = django_timezone.make_aware(end_dt)
                else:
                    if not django_timezone.is_naive(end_dt):
                        end_dt = django_timezone.make_naive(end_dt)
                a['is_expired'] = end_dt < now_dt
            else:
                a['is_expired'] = False

        # ── Stats ───────────────────────────────────────────────────────────
        now_str = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')

        # Check if free_trial_history has any rows
        cursor.execute("SELECT COUNT(*) FROM free_trial_history")
        history_total = cursor.fetchone()[0]
        history_empty = (history_total == 0)

        if history_empty:
            cursor.execute("SELECT COUNT(*) FROM agents WHERE plan_type = 'free_trial'")
            stat_total = cursor.fetchone()[0]
        else:
            stat_total = history_total

        cursor.execute(
            "SELECT COUNT(*) FROM agents WHERE plan_type = 'free_trial' AND trial_ends_at > %s",
            [now_str]
        )
        stat_active = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(*) FROM agents WHERE plan_type = 'free_trial' AND trial_ends_at < %s",
            [now_str]
        )
        stat_expired = cursor.fetchone()[0]

        if history_empty:
            stat_by_promo = 0
            stat_by_ref   = 0
            stat_revenue  = cursor.execute("SELECT COUNT(*) FROM agents WHERE plan_type = 'free_trial'") or 0
            cursor.execute("SELECT COUNT(*) FROM agents WHERE plan_type = 'free_trial'")
            stat_revenue = cursor.fetchone()[0] * 99
        else:
            cursor.execute("SELECT COUNT(*) FROM free_trial_history WHERE source = 'promo'")
            stat_by_promo = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM free_trial_history WHERE source = 'referral'")
            stat_by_ref = cursor.fetchone()[0]
            cursor.execute("SELECT COALESCE(SUM(trial_price_paid), 0) FROM free_trial_history")
            stat_revenue = float(cursor.fetchone()[0] or 0)

        cursor.execute("SELECT COUNT(*) FROM promo_codes WHERE is_free_trial = 1 AND is_active = 1")
        stat_codes_active = cursor.fetchone()[0]

        stats = {
            'total':        stat_total,
            'active':       stat_active,
            'expired':      stat_expired,
            'by_promo':     stat_by_promo,
            'by_ref':       stat_by_ref,
            'revenue':      stat_revenue,
            'codes_active': stat_codes_active,
        }

        # ── Monthly Stats (for Chart.js) ────────────────────────────────────
        if history_empty:
            cursor.execute("""
                SELECT DATE_FORMAT(created_at, '%b %Y') as label,
                       YEAR(created_at) as yr, MONTH(created_at) as mo,
                       COUNT(*) as signups, SUM(99) as revenue
                FROM agents
                WHERE plan_type = 'free_trial'
                GROUP BY label, yr, mo
                ORDER BY yr, mo
                LIMIT 12
            """)
        else:
            cursor.execute("""
                SELECT DATE_FORMAT(created_at, '%b %Y') as label,
                       YEAR(created_at) as yr, MONTH(created_at) as mo,
                       COUNT(*) as signups, SUM(trial_price_paid) as revenue
                FROM free_trial_history
                GROUP BY label, yr, mo
                ORDER BY yr, mo
                LIMIT 12
            """)
        monthly_stats_raw = cursor.fetchall()
        monthly_stats = [
            {'label': r[0], 'yr': r[1], 'mo': r[2], 'signups': r[3], 'revenue': float(r[4] or 0)}
            for r in monthly_stats_raw
        ]

        # ── Top Promo Usage Summary ─────────────────────────────────────────
        if history_empty:
            cursor.execute("""
                SELECT code as promo_code, trial_plan_name, times_used as usages,
                       times_used * COALESCE(trial_price_override, 99) as revenue
                FROM promo_codes
                WHERE is_free_trial = 1 AND times_used > 0
                ORDER BY times_used DESC
                LIMIT 10
            """)
        else:
            cursor.execute("""
                SELECT promo_code, MAX(trial_plan_name) as trial_plan_name,
                       COUNT(*) as usages, SUM(trial_price_paid) as revenue
                FROM free_trial_history
                WHERE promo_code IS NOT NULL
                GROUP BY promo_code
                ORDER BY usages DESC
                LIMIT 10
            """)
        promo_usage_summary = [
            {
                'promo_code': r[0],
                'trial_plan_name': r[1],
                'usages': r[2],
                'revenue': float(r[3] or 0),
            }
            for r in cursor.fetchall()
        ]

        # ── History (first page, server-side rendered — no AJAX on initial load) ──
        if history_empty:
            cursor.execute("""
                SELECT id, fullname as agent_name, email as agent_email, mobile as agent_mobile,
                       NULL as promo_code, 'Standard Free Trial' as trial_plan_name,
                       30 as trial_duration_days, 99 as trial_price_paid,
                       0 as discount_amount, NULL as discount_type,
                       'direct' as source,
                       COALESCE(created_at, created_at) as trial_started_at,
                       trial_ends_at
                FROM agents
                WHERE plan_type = 'free_trial'
                ORDER BY created_at DESC
            """)
        else:
            cursor.execute("""
                SELECT id, agent_name, agent_email, agent_mobile,
                       promo_code, trial_plan_name, trial_duration_days, trial_price_paid,
                       discount_amount, discount_type, source, trial_started_at, trial_ends_at
                FROM free_trial_history
                ORDER BY created_at DESC
            """)
        history_rows = cursor.fetchall()
        history_cols = [
            'id', 'agent_name', 'agent_email', 'agent_mobile',
            'promo_code', 'trial_plan_name', 'trial_duration_days',
            'trial_price_paid', 'discount_amount', 'discount_type',
            'source', 'trial_started_at', 'trial_ends_at',
        ]
        history = [dict(zip(history_cols, r)) for r in history_rows]

        for h in history:
            end_dt = h.get('trial_ends_at')
            if end_dt:
                from django.conf import settings
                if getattr(settings, 'USE_TZ', False):
                    if django_timezone.is_naive(end_dt):
                        end_dt = django_timezone.make_aware(end_dt)
                else:
                    if not django_timezone.is_naive(end_dt):
                        end_dt = django_timezone.make_naive(end_dt)
                h['is_expired'] = end_dt < now_dt
            else:
                h['is_expired'] = True

        paginator = Paginator(history, 25)
        page_number = request.GET.get('page', 1)
        history_page = paginator.get_page(page_number)


    from datetime import timedelta
    tomorrow_date_str = (django_timezone.now() + timedelta(days=1)).strftime('%Y-%m-%d')

    context = {
        'admin':              admin,
        'trial_config':       trial_config,
        'upgrade_discount':   upgrade_discount,
        'tomorrow_date_str':  tomorrow_date_str,
        'referral_config':    referral_config,
        'trial_promo_codes':  trial_promo_codes,
        'active_agents':      active_agents,
        'stats':              stats,
        'monthly_stats':      monthly_stats,
        'promo_usage_summary': promo_usage_summary,
        'history':            history_page,
        'history_empty':      history_empty,
    }
    return render(request, 'admin/free_trial/index.html', context)


# ─────────────────────────────────────────────────────────────────────────────
#  CONFIG ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

@require_http_methods(["POST"])
def ft_update_trial_config(request):
    admin = _get_admin_from_session(request)
    if not admin:
        return redirect('admin_login_page')

    price         = request.POST.get('price', '').strip()
    duration_days = request.POST.get('duration_days', '').strip()
    badge         = request.POST.get('badge', 'TRIAL').strip()
    description   = request.POST.get('description', '').strip()
    is_active     = bool(request.POST.get('is_active'))

    if not price or not duration_days:
        messages.error(request, 'Price and duration are required.')
        return redirect('admin_free_trial')

    try:
        price         = float(price)
        duration_days = int(duration_days)
    except ValueError:
        messages.error(request, 'Invalid price or duration.')
        return redirect('admin_free_trial')

    set_setting('trial_plan_config', {
        'price':         price,
        'duration_days': duration_days,
        'badge':         badge or 'TRIAL',
        'description':   description or 'Try before you commit — full access',
        'is_active':     is_active,
    }, 'pricing')

    _log_activity(admin, 'Update Free Trial config', 'SiteSetting')
    messages.success(request, 'Free Trial configuration saved.')
    return redirect('admin_free_trial')


@require_http_methods(["POST"])
def ft_update_upgrade_discount(request):
    admin = _get_admin_from_session(request)
    if not admin:
        return redirect('admin_login_page')

    discount = request.POST.get('upgrade_discount', '').strip()
    try:
        discount = float(discount)
        if not (0 <= discount <= 100):
            raise ValueError
    except ValueError:
        messages.error(request, 'Invalid discount value.')
        return redirect('admin_free_trial')

    set_setting('trial_upgrade_discount', discount, 'pricing')

    # Bulk-update all active trial agents — exact Laravel parity
    now_str = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE agents
            SET upgrade_discount_percent = %s
            WHERE plan_type = 'free_trial' AND trial_ends_at > %s
            """,
            [discount, now_str],
        )
        updated_count = cursor.rowcount

    _log_activity(admin, f'Update trial upgrade discount to {discount}%', 'SiteSetting')
    messages.success(request, f'Discount updated to {discount}%. Applied to {updated_count} active agents.')
    return redirect('admin_free_trial')


@require_http_methods(["POST"])
def ft_update_referral_config(request):
    admin = _get_admin_from_session(request)
    if not admin:
        return redirect('admin_login_page')

    eligibility       = request.POST.get('eligibility', 'free_trial_only')
    count_free_trial  = bool(request.POST.get('count_free_trial'))

    if eligibility not in ('all', 'free_trial_only'):
        messages.error(request, 'Invalid eligibility value.')
        return redirect('admin_free_trial')

    set_setting('referral_config', {
        'eligibility':      eligibility,
        'count_free_trial': count_free_trial,
    }, 'referral')

    _log_activity(
        admin,
        f'Updated Referral Settings -> Eligibility: {eligibility}, '
        f'Count Free Trial: {"ON" if count_free_trial else "OFF"}',
        'SiteSetting',
    )
    messages.success(request, 'Referral configuration updated successfully.')
    return redirect('admin_free_trial')


@require_http_methods(["POST"])
def ft_force_test_credit(request):
    admin = _get_admin_from_session(request)
    if not admin:
        return redirect('admin_login_page')

    agent_id_raw = request.POST.get('agent_id', '').strip()
    if not agent_id_raw:
        messages.error(request, 'The agent id field is required.')
        return redirect('admin_free_trial')

    try:
        agent_id = int(agent_id_raw)
    except ValueError:
        messages.error(request, 'The agent id must be an integer.')
        return redirect('admin_free_trial')

    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                # 2. Lookup agent
                cursor.execute("SELECT id, fullname FROM agents WHERE id = %s LIMIT 1", [agent_id])
                agent_row = cursor.fetchone()
                if not agent_row:
                    from django.http import Http404
                    raise Http404("No Agent found.")

                agent_id = agent_row[0]
                agent_fullname = agent_row[1]

                # 3–4. Lookup or generate referral code (shared service)
                ref = generate_referral_code_for_agent(cursor, agent_id, agent_fullname)
                ref_code_id  = ref['id']
                ref_code_str = ref['code']

                # 5. Insert dummy agent
                import time
                ts = int(time.time())
                dummy_fullname = f"Test Conversion {ts}"
                dummy_email    = f"test{ts}@test.com"
                dummy_mobile   = "99999" + str(random.randint(10000, 99999))

                cursor.execute("""
                    INSERT INTO agents (fullname, email, mobile, status, referred_by_code, created_at, updated_at)
                    VALUES (%s, %s, %s, 'active', %s, NOW(), NOW())
                """, [dummy_fullname, dummy_email, dummy_mobile, ref_code_str])
                dummy_agent_id = cursor.lastrowid

                # 6. Insert referral usage
                cursor.execute("""
                    INSERT INTO referral_usages (referral_code_id, referrer_agent_id, referred_agent_id, referred_agent_name, status, converted_at, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, 'converted', NOW(), NOW(), NOW())
                """, [ref_code_id, agent_id, dummy_agent_id, dummy_fullname])

                # 7. Increment referral_codes.total_referrals
                cursor.execute("""
                    UPDATE referral_codes
                    SET total_referrals = total_referrals + 1, updated_at = NOW()
                    WHERE id = %s
                """, [ref_code_id])

                # 8. Refresh total
                cursor.execute("SELECT total_referrals FROM referral_codes WHERE id = %s LIMIT 1", [ref_code_id])
                new_total = cursor.fetchone()[0]

                # 9–10. Apply tier reward via shared service
                apply_tier_reward(cursor, agent_id, ref_code_id, new_total)

                # 11. Log activity
                log_msg = f"FORCED TEST CONVERSION explicitly added to Agent ID {agent_id}. Reward Tier updated."
                _log_activity(admin, log_msg, 'ReferralCode')

    except Exception as e:
        raise e

    # 12. Flash message
    messages.success(request, f"Successfully FORCED +1 Fake Conversion to Agent ID {agent_id}. Rewards calculated and applied.")
    return redirect('admin_free_trial')


# ─────────────────────────────────────────────────────────────────────────────
#  TRIAL PROMO CODE CRUD
# ─────────────────────────────────────────────────────────────────────────────

@require_http_methods(["POST"])
def ft_generate_promo(request):
    """Generate a new trial promo code. Mirrors generateTrialPromoCode()."""
    admin = _get_admin_from_session(request)
    if not admin:
        return redirect('admin_login_page')

    prefix               = request.POST.get('prefix', 'TRIAL').strip() or 'TRIAL'
    trial_plan_name      = request.POST.get('trial_plan_name', '').strip() or None
    trial_duration_days  = request.POST.get('trial_duration_days', '').strip() or None
    trial_price_override = request.POST.get('trial_price_override', '').strip() or None
    max_uses             = request.POST.get('max_uses', '').strip() or None
    expires_at           = request.POST.get('expires_at', '').strip() or None
    discount_type        = request.POST.get('discount_type', 'fixed') or 'fixed'
    discount_value       = request.POST.get('discount_value', '0').strip() or '0'
    notes                = request.POST.get('notes', '').strip() or None

    # Sanitise
    if discount_type not in ('percentage', 'fixed'):
        discount_type = 'fixed'
    try:
        discount_value = float(discount_value)
    except ValueError:
        discount_value = 0.0

    try:
        trial_duration_days = int(trial_duration_days) if trial_duration_days else None
    except ValueError:
        trial_duration_days = None

    try:
        trial_price_override = float(trial_price_override) if trial_price_override else None
    except ValueError:
        trial_price_override = None

    try:
        max_uses = int(max_uses) if max_uses else None
    except ValueError:
        max_uses = None

    code = _generate_unique_code(prefix)

    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO promo_codes
                (code, discount_type, discount_value, is_active, is_free_trial,
                 applicable_plan, max_uses, times_used, expires_at,
                 trial_plan_name, trial_duration_days, trial_price_override, notes,
                 created_at, updated_at)
            VALUES (%s, %s, %s, 1, 1, 'free_trial', %s, 0, %s, %s, %s, %s, %s, NOW(), NOW())
            """,
            [code, discount_type, discount_value, max_uses, expires_at,
             trial_plan_name, trial_duration_days, trial_price_override, notes],
        )
        new_id = cursor.lastrowid

    _log_activity(admin, f'Generate Trial Promo Code: {code}', 'PromoCode', new_id)
    messages.success(request, f'Promo code <strong>{code}</strong> created! Share this with agents.')
    return redirect('admin_free_trial')


@require_http_methods(["POST"])
def ft_update_promo(request, promo_id):
    """Edit an existing trial promo code. Mirrors updateTrialPromoCode()."""
    admin = _get_admin_from_session(request)
    if not admin:
        return redirect('admin_login_page')

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT id, code FROM promo_codes WHERE id = %s AND is_free_trial = 1",
            [promo_id],
        )
        row = cursor.fetchone()

    if not row:
        messages.error(request, 'Trial promo code not found.')
        return redirect('admin_free_trial')

    code_str = row[1]

    trial_plan_name      = request.POST.get('trial_plan_name', '').strip() or None
    trial_duration_days  = request.POST.get('trial_duration_days', '').strip() or None
    trial_price_override = request.POST.get('trial_price_override', '').strip() or None
    max_uses             = request.POST.get('max_uses', '').strip() or None
    expires_at           = request.POST.get('expires_at', '').strip() or None
    discount_type        = request.POST.get('discount_type', 'fixed') or 'fixed'
    discount_value       = request.POST.get('discount_value', '0').strip() or '0'
    notes                = request.POST.get('notes', '').strip() or None

    if discount_type not in ('percentage', 'fixed'):
        discount_type = 'fixed'
    try:
        discount_value = float(discount_value)
    except ValueError:
        discount_value = 0.0
    try:
        trial_duration_days = int(trial_duration_days) if trial_duration_days else None
    except ValueError:
        trial_duration_days = None
    try:
        trial_price_override = float(trial_price_override) if trial_price_override else None
    except ValueError:
        trial_price_override = None
    try:
        max_uses = int(max_uses) if max_uses else None
    except ValueError:
        max_uses = None
    # datetime-local comes as "YYYY-MM-DDTHH:MM" — convert to MySQL timestamp
    if expires_at and 'T' in expires_at:
        expires_at = expires_at.replace('T', ' ') + ':00'

    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE promo_codes SET
                discount_type = %s, discount_value = %s, max_uses = %s, expires_at = %s,
                trial_plan_name = %s, trial_duration_days = %s, trial_price_override = %s,
                notes = %s, updated_at = NOW()
            WHERE id = %s AND is_free_trial = 1
            """,
            [discount_type, discount_value, max_uses, expires_at,
             trial_plan_name, trial_duration_days, trial_price_override, notes, promo_id],
        )

    _log_activity(admin, f'Updated Trial Promo Code: {code_str}', 'PromoCode', promo_id)
    messages.success(request, f'Promo code <strong>{code_str}</strong> updated successfully!')
    return redirect('admin_free_trial')


@csrf_exempt
@require_http_methods(["POST"])
def ft_toggle_promo(request):
    """AJAX toggle for trial promo code active state. Returns JSON."""
    admin = _get_admin_from_session(request)
    if not admin:
        return JsonResponse({'success': False, 'message': 'Unauthorized'}, status=401)

    try:
        data = json.loads(request.body)
        promo_id = int(data.get('id', 0))
    except (json.JSONDecodeError, ValueError, TypeError):
        return JsonResponse({'success': False, 'message': 'Invalid request'}, status=400)

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT is_active FROM promo_codes WHERE id = %s AND is_free_trial = 1",
            [promo_id],
        )
        row = cursor.fetchone()
        if not row:
            return JsonResponse({'success': False, 'message': 'Not found'}, status=404)

        new_status = 0 if row[0] else 1
        cursor.execute(
            "UPDATE promo_codes SET is_active = %s, updated_at = NOW() WHERE id = %s",
            [new_status, promo_id],
        )

    return JsonResponse({'success': True, 'is_active': bool(new_status)})


@require_http_methods(["POST"])
def ft_delete_promo(request, promo_id):
    """Hard-delete a trial promo code. Mirrors deleteTrialPromoCode()."""
    admin = _get_admin_from_session(request)
    if not admin:
        return redirect('admin_login_page')

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT id, code FROM promo_codes WHERE id = %s AND is_free_trial = 1",
            [promo_id],
        )
        row = cursor.fetchone()
        if not row:
            messages.error(request, 'Trial promo code not found.')
            return redirect('admin_free_trial')

        code_str = row[1]
        cursor.execute("DELETE FROM promo_codes WHERE id = %s", [promo_id])

    _log_activity(admin, f'Deleted Trial Promo Code: {code_str}', 'PromoCode')
    messages.success(request, f'Promo code {code_str} deleted.')
    return redirect('admin_free_trial')


# ─────────────────────────────────────────────────────────────────────────────
#  HISTORY  (AJAX/paginated JSON)
# ─────────────────────────────────────────────────────────────────────────────

@require_http_methods(["GET"])
def ft_history(request):
    """
    AJAX endpoint — returns paginated JSON of free_trial_history rows.
    Falls back to agents table if history is empty.
    Mirrors AdminFreeTrialController::history().
    """
    admin = _get_admin_from_session(request)
    if not admin:
        return JsonResponse({'success': False}, status=401)

    search    = request.GET.get('search', '').strip()
    source    = request.GET.get('source', '').strip()
    page      = max(1, int(request.GET.get('page', 1)))
    per_page  = 20
    offset    = (page - 1) * per_page

    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM free_trial_history")
        history_empty = cursor.fetchone()[0] == 0

    if history_empty:
        # Fallback
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM agents WHERE plan_type = 'free_trial'")
            total = cursor.fetchone()[0]
            cursor.execute(
                """
                SELECT id, fullname, email, mobile,
                       NULL, 'Standard Free Trial', 30, 99, 0, NULL,
                       'direct', created_at, trial_ends_at
                FROM agents
                WHERE plan_type = 'free_trial'
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                [per_page, offset],
            )
            rows = cursor.fetchall()
    else:
        conditions = []
        params = []
        if search:
            conditions.append(
                "(agent_name LIKE %s OR agent_email LIKE %s OR promo_code LIKE %s)"
            )
            like = f'%{search}%'
            params.extend([like, like, like])
        if source:
            conditions.append("source = %s")
            params.append(source)

        where_clause = ('WHERE ' + ' AND '.join(conditions)) if conditions else ''

        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT COUNT(*) FROM free_trial_history {where_clause}", params
            )
            total = cursor.fetchone()[0]

            cursor.execute(
                f"""
                SELECT id, agent_name, agent_email, agent_mobile,
                       promo_code, trial_plan_name, trial_duration_days, trial_price_paid,
                       discount_amount, discount_type, source, trial_started_at, trial_ends_at
                FROM free_trial_history
                {where_clause}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                params + [per_page, offset],
            )
            rows = cursor.fetchall()

    cols = [
        'id', 'agent_name', 'agent_email', 'agent_mobile',
        'promo_code', 'trial_plan_name', 'trial_duration_days',
        'trial_price_paid', 'discount_amount', 'discount_type',
        'source', 'trial_started_at', 'trial_ends_at',
    ]
    data = []
    for r in rows:
        item = dict(zip(cols, r))
        # Convert datetimes to strings for JSON serialisation
        for key in ('trial_started_at', 'trial_ends_at'):
            if item.get(key) and hasattr(item[key], 'isoformat'):
                item[key] = item[key].isoformat()
        item['trial_price_paid'] = float(item.get('trial_price_paid') or 0)
        item['discount_amount']  = float(item.get('discount_amount') or 0)
        data.append(item)

    total_pages = max(1, (total + per_page - 1) // per_page)
    return JsonResponse({
        'data':        data,
        'total':       total,
        'page':        page,
        'per_page':    per_page,
        'total_pages': total_pages,
    })


# ─────────────────────────────────────────────────────────────────────────────
#  ANALYTICS DATA  (AJAX JSON for Chart.js)
# ─────────────────────────────────────────────────────────────────────────────

@require_http_methods(["GET"])
def ft_analytics_data(request):
    """
    AJAX endpoint — monthly stats + top promo breakdown for Chart.js.
    Mirrors AdminFreeTrialController::analyticsData().
    """
    admin = _get_admin_from_session(request)
    if not admin:
        return JsonResponse({'success': False}, status=401)

    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM free_trial_history")
        history_empty = cursor.fetchone()[0] == 0

        if history_empty:
            return JsonResponse({'monthly': [], 'by_promo': []})

        cursor.execute("""
            SELECT DATE_FORMAT(created_at, '%b %Y') as label,
                   COUNT(*) as signups,
                   SUM(trial_price_paid) as revenue,
                   SUM(CASE WHEN source='promo' THEN 1 ELSE 0 END) as via_promo,
                   SUM(CASE WHEN source='referral' THEN 1 ELSE 0 END) as via_referral,
                   SUM(CASE WHEN source='direct' THEN 1 ELSE 0 END) as via_direct
            FROM free_trial_history
            GROUP BY DATE_FORMAT(created_at, '%b %Y'), YEAR(created_at), MONTH(created_at)
            ORDER BY YEAR(created_at), MONTH(created_at)
            LIMIT 12
        """)
        monthly = [
            {
                'label': r[0], 'signups': r[1],
                'revenue': float(r[2] or 0),
                'via_promo': r[3], 'via_referral': r[4], 'via_direct': r[5],
            }
            for r in cursor.fetchall()
        ]

        cursor.execute("""
            SELECT promo_code, trial_plan_name, COUNT(*) as uses, SUM(trial_price_paid) as revenue
            FROM free_trial_history
            WHERE promo_code IS NOT NULL
            GROUP BY promo_code, trial_plan_name
            ORDER BY uses DESC
            LIMIT 10
        """)
        by_promo = [
            {
                'promo_code': r[0], 'trial_plan_name': r[1],
                'uses': r[2], 'revenue': float(r[3] or 0),
            }
            for r in cursor.fetchall()
        ]

    return JsonResponse({'monthly': monthly, 'by_promo': by_promo})
