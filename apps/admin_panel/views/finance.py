import json
from datetime import timedelta

from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.timezone import now
from django.views.decorators.http import require_POST

from apps.admin_panel.decorators import admin_login_required
from apps.admin_panel.models import AdminActivityLog
from apps.agents.models import AgentSubscription


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _date_from(period: str):
    """Return the start datetime for the selected period filter (or None for 'all')."""
    today = now()
    if period == 'month':
        return today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    elif period == 'quarter':
        q_start_month = ((today.month - 1) // 3) * 3 + 1
        return today.replace(month=q_start_month, day=1, hour=0, minute=0, second=0, microsecond=0)
    elif period == 'year':
        return today.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    return None


def _fmt(value) -> str:
    """Format a number with Indian comma style."""
    try:
        v = int(round(float(value or 0)))
        return f"{v:,}"
    except Exception:
        return "0"


# ─── Index ───────────────────────────────────────────────────────────────────

@admin_login_required
def index(request):
    """Finance & Accounts dashboard — mirrors AdminFinanceController::index."""
    period      = request.GET.get('period', 'all')
    date_from   = _date_from(period)

    # ── KPI aggregates ────────────────────────────────────────────────────────
    qs = AgentSubscription.objects.all()
    if date_from:
        qs = qs.filter(created_at__gte=date_from)

    from django.db.models import Sum, Count, Q
    agg = qs.aggregate(
        total_collected = Sum('registration_amount', filter=Q(payment_status='completed')),
        total_pending   = Sum('registration_amount', filter=Q(payment_status='pending')),
        total_failed    = Sum('registration_amount', filter=Q(payment_status='failed')),
        txn_completed   = Count('id', filter=Q(payment_status='completed')),
        txn_pending     = Count('id', filter=Q(payment_status='pending')),
        txn_failed      = Count('id', filter=Q(payment_status='failed')),
    )

    total_collected = float(agg['total_collected'] or 0)
    total_pending   = float(agg['total_pending']   or 0)
    total_failed    = float(agg['total_failed']    or 0)
    total_attempted = total_collected + total_pending + total_failed
    collection_rate = round((total_collected / total_attempted) * 100, 1) if total_attempted > 0 else 0
    txn_completed   = agg['txn_completed'] or 0
    txn_pending     = agg['txn_pending']   or 0
    txn_failed      = agg['txn_failed']    or 0

    # ── Monthly cash flow (last 12 months, always fixed) ──────────────────────
    with connection.cursor() as cur:
        cur.execute("""
            SELECT
                DATE_FORMAT(created_at, '%%b %%Y') AS label,
                YEAR(created_at)  AS yr,
                MONTH(created_at) AS mo,
                SUM(CASE WHEN payment_status='completed' THEN registration_amount ELSE 0 END) AS collected,
                SUM(CASE WHEN payment_status='pending'   THEN registration_amount ELSE 0 END) AS pending,
                SUM(CASE WHEN payment_status='failed'    THEN registration_amount ELSE 0 END) AS failed,
                COUNT(*) AS total_txn,
                SUM(CASE WHEN payment_status='completed' THEN 1 ELSE 0 END) AS success_txn
            FROM agent_subscriptions
            WHERE created_at >= DATE_SUB(UTC_TIMESTAMP(), INTERVAL 12 MONTH)
            GROUP BY label, yr, mo
            ORDER BY yr ASC, mo ASC
        """)
        cols = [c[0] for c in cur.description]
        monthly_cashflow = [dict(zip(cols, row)) for row in cur.fetchall()]

    # ── Plan-wise P&L breakdown ───────────────────────────────────────────────
    with connection.cursor() as cur:
        cur.execute("""
            SELECT
                selected_plan,
                COUNT(*) AS total_transactions,
                SUM(CASE WHEN payment_status='completed' THEN 1 ELSE 0 END) AS successful,
                SUM(CASE WHEN payment_status='failed'    THEN 1 ELSE 0 END) AS failed_cnt,
                SUM(CASE WHEN payment_status='pending'   THEN 1 ELSE 0 END) AS pending_cnt,
                SUM(CASE WHEN payment_status='completed' THEN registration_amount ELSE 0 END) AS collected,
                SUM(CASE WHEN payment_status='failed'    THEN registration_amount ELSE 0 END) AS failed_amount,
                SUM(CASE WHEN payment_status='pending'   THEN registration_amount ELSE 0 END) AS pending_amount,
                SUM(registration_amount) AS total_value
            FROM agent_subscriptions
            GROUP BY selected_plan
            ORDER BY collected DESC
        """)
        cols = [c[0] for c in cur.description]
        plan_breakdown_raw = [dict(zip(cols, row)) for row in cur.fetchall()]

    # Compute collection rate % for each plan
    plan_breakdown = []
    for p in plan_breakdown_raw:
        tv = float(p['total_value'] or 0)
        cl = float(p['collected']   or 0)
        p['collection_rate'] = round((cl / tv) * 100) if tv > 0 else 0
        plan_name = (p['selected_plan'] or '').lower()
        p['color'] = (
            '#1d7d5d' if 'professional' in plan_name or 'pro' in plan_name
            else '#f59e0b' if 'starter' in plan_name or 'basic' in plan_name
            else '#7c3aed'
        )
        plan_breakdown.append(p)

    # ── Renewals due in next 30 days ──────────────────────────────────────────
    now_dt     = now()
    in_30_days = now_dt + timedelta(days=30)
    with connection.cursor() as cur:
        cur.execute("""
            SELECT
                s.id, s.selected_plan, s.registration_amount, s.expires_at,
                a.fullname, a.email, a.mobile,
                ap.display_name
            FROM agent_subscriptions s
            JOIN agents a ON s.agent_id = a.id
            LEFT JOIN agent_profiles ap ON a.id = ap.agent_id
            WHERE s.payment_status = 'completed'
              AND s.expires_at BETWEEN %s AND %s
            ORDER BY s.expires_at ASC
            LIMIT 20
        """, [now_dt, in_30_days])
        cols = [c[0] for c in cur.description]
        renewals_raw = [dict(zip(cols, row)) for row in cur.fetchall()]

    renewals_due = []
    for r in renewals_raw:
        exp = r['expires_at']
        if exp:
            days_left = (exp - now_dt).days
        else:
            days_left = 0
        r['days_left']    = abs(days_left)
        r['urgent']       = abs(days_left) <= 7
        r['display_name'] = r['display_name'] or r['fullname'] or ''
        r['expires_fmt']  = exp.strftime('%d %b %Y') if exp else '—'
        renewals_due.append(r)

    renewals_total_amount = sum(float(r['registration_amount'] or 0) for r in renewals_due)

    # ── Overdue / pending payments (unpaid > 3 days old) ─────────────────────
    three_days_ago = now_dt - timedelta(days=3)
    with connection.cursor() as cur:
        cur.execute("""
            SELECT
                s.id, s.selected_plan, s.registration_amount, s.payment_status,
                s.created_at,
                a.fullname, a.email, a.mobile,
                ap.display_name
            FROM agent_subscriptions s
            JOIN agents a ON s.agent_id = a.id
            LEFT JOIN agent_profiles ap ON a.id = ap.agent_id
            WHERE s.payment_status IN ('pending', 'failed')
              AND s.created_at < %s
            ORDER BY s.registration_amount DESC
            LIMIT 20
        """, [three_days_ago])
        cols = [c[0] for c in cur.description]
        overdue_raw = [dict(zip(cols, row)) for row in cur.fetchall()]

    overdue_payments = []
    for o in overdue_raw:
        created = o['created_at']
        o['days_old']    = (now_dt - created).days if created else 0
        o['display_name'] = o['display_name'] or o['fullname'] or ''
        overdue_payments.append(o)

    # ── Recent transactions (latest 30) ───────────────────────────────────────
    with connection.cursor() as cur:
        cur.execute("""
            SELECT
                s.id, s.selected_plan, s.registration_amount,
                s.payment_status, s.starts_at, s.expires_at, s.created_at,
                a.fullname, a.email, a.mobile,
                ap.display_name
            FROM agent_subscriptions s
            JOIN agents a ON s.agent_id = a.id
            LEFT JOIN agent_profiles ap ON a.id = ap.agent_id
            ORDER BY s.created_at DESC
            LIMIT 30
        """)
        cols = [c[0] for c in cur.description]
        recent_txns_raw = [dict(zip(cols, row)) for row in cur.fetchall()]

    recent_txns = []
    for t in recent_txns_raw:
        plan = (t['selected_plan'] or '').lower()
        is_pro     = 'professional' in plan or 'pro' in plan
        is_starter = 'starter' in plan or 'basic' in plan
        t['plan_color'] = '#1d7d5d' if is_pro else ('#f59e0b' if is_starter else '#7c3aed')
        t['plan_bg']    = '#dcfce7' if is_pro else ('#fef9c3' if is_starter else '#ede9fe')
        t['display_name'] = t['display_name'] or t['fullname'] or ''
        # human-readable time ago
        created = t['created_at']
        if created:
            diff  = now_dt - created
            secs  = int(diff.total_seconds())
            if secs < 60:
                t['time_ago'] = 'just now'
            elif secs < 3600:
                t['time_ago'] = f"{secs // 60}m ago"
            elif secs < 86400:
                t['time_ago'] = f"{secs // 3600}h ago"
            else:
                t['time_ago'] = f"{diff.days}d ago"
            t['created_fmt'] = created.strftime('%d %b %Y')
        else:
            t['time_ago']    = ''
            t['created_fmt'] = '—'
        t['expires_fmt'] = t['expires_at'].strftime('%d %b %Y') if t['expires_at'] else '—'
        # data-search string for client-side filter
        t['search_str'] = f"{t['display_name']} {t['email']} {t['selected_plan'] or ''}".lower()
        recent_txns.append(t)

    # ── MRR / ARR ─────────────────────────────────────────────────────────────
    with connection.cursor() as cur:
        cur.execute("""
            SELECT COALESCE(SUM(
                s.registration_amount /
                GREATEST(1, TIMESTAMPDIFF(MONTH, s.starts_at,
                    COALESCE(s.expires_at, DATE_ADD(s.starts_at, INTERVAL 12 MONTH))))
            ), 0) AS mrr
            FROM agent_subscriptions s
            JOIN agents a ON s.agent_id = a.id
            WHERE a.plan_type IN ('professional', 'pro')
              AND s.payment_status = 'completed'
              AND (s.expires_at IS NULL OR s.expires_at > UTC_TIMESTAMP())
              AND s.starts_at IS NOT NULL
        """)
        prof_mrr = float(cur.fetchone()[0] or 0)

    with connection.cursor() as cur:
        cur.execute("""
            SELECT COALESCE(SUM(
                s.registration_amount /
                GREATEST(1, TIMESTAMPDIFF(MONTH, s.starts_at,
                    COALESCE(s.expires_at, DATE_ADD(s.starts_at, INTERVAL 12 MONTH))))
            ), 0) AS mrr
            FROM agent_subscriptions s
            JOIN agents a ON s.agent_id = a.id
            WHERE a.plan_type IN ('basic', 'starter')
              AND s.payment_status = 'completed'
              AND (s.expires_at IS NULL OR s.expires_at > UTC_TIMESTAMP())
              AND s.starts_at IS NOT NULL
        """)
        starter_mrr = float(cur.fetchone()[0] or 0)

    mrr = int(round(prof_mrr + starter_mrr))
    arr = mrr * 12

    # ── Serialise cashflow for Chart.js ───────────────────────────────────────
    cashflow_labels    = json.dumps([m['label']     for m in monthly_cashflow])
    cashflow_collected = json.dumps([float(m['collected'] or 0) for m in monthly_cashflow])
    cashflow_pending   = json.dumps([float(m['pending']   or 0) for m in monthly_cashflow])
    cashflow_failed    = json.dumps([float(m['failed']    or 0) for m in monthly_cashflow])

    return render(request, 'admin/finance.html', {
        'period':           period,
        # KPIs
        'total_collected':  total_collected,
        'total_pending':    total_pending,
        'total_failed':     total_failed,
        'total_attempted':  total_attempted,
        'collection_rate':  collection_rate,
        'txn_completed':    txn_completed,
        'txn_pending':      txn_pending,
        'txn_failed':       txn_failed,
        # Chart data (JSON strings)
        'cashflow_labels':    cashflow_labels,
        'cashflow_collected': cashflow_collected,
        'cashflow_pending':   cashflow_pending,
        'cashflow_failed':    cashflow_failed,
        # Plan breakdown
        'plan_breakdown':   plan_breakdown,
        # Panels
        'renewals_due':           renewals_due,
        'renewals_total_amount':  renewals_total_amount,
        'overdue_payments':       overdue_payments,
        # Table
        'recent_txns':      recent_txns,
        # MRR / ARR
        'mrr': mrr,
        'arr': arr,
    })


# ─── Mark Payment ─────────────────────────────────────────────────────────────

@admin_login_required
@require_POST
def mark_payment(request):
    """Update a subscription's payment_status. Accepts AJAX or form POST."""
    sub_id = request.POST.get('subscription_id')
    status = request.POST.get('status', '').strip()

    VALID = {'completed', 'failed', 'pending'}
    if not sub_id or status not in VALID:
        return JsonResponse({'success': False, 'message': 'Invalid data.'}, status=400)

    try:
        sub = AgentSubscription.objects.get(pk=sub_id)
    except AgentSubscription.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Subscription not found.'}, status=404)

    old_status = sub.payment_status
    sub.payment_status = status
    sub.updated_at     = now()
    sub.save(update_fields=['payment_status', 'updated_at'])

    AdminActivityLog.log(
        f'Mark payment {old_status} → {status}',
        'AgentSubscription', sub.id,
        request=request
    )

    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    if is_ajax:
        return JsonResponse({'success': True, 'new_status': status})

    from django.shortcuts import redirect
    from django.contrib import messages
    messages.success(request, f'Payment #{sub_id} marked as {status}.')
    return redirect(request.META.get('HTTP_REFERER', '/admin/finance/'))
