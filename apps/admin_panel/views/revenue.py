from django.shortcuts import render, redirect
from django.db import connection
from .dashboard import _get_admin_from_session

import datetime
import json

def revenue_dashboard(request):
    admin = _get_admin_from_session(request)
    if not admin:
        return redirect('admin_login')

    with connection.cursor() as cursor:
        # 1. Monthly Revenue by plan (last 12 months)
        cursor.execute("""
            SELECT
                DATE_FORMAT(s.created_at, '%b %Y')  AS label,
                YEAR(s.created_at)                  AS yr,
                MONTH(s.created_at)                 AS mo,
                SUM(CASE WHEN LOWER(s.selected_plan) LIKE '%%professional%%'
                         THEN COALESCE(s.registration_amount, 0) ELSE 0 END) AS professional,
                SUM(CASE WHEN LOWER(s.selected_plan) LIKE '%%starter%%'
                         THEN COALESCE(s.registration_amount, 0) ELSE 0 END) AS starter,
                SUM(CASE WHEN LOWER(s.selected_plan) LIKE '%%trial%%'
                         THEN COALESCE(s.registration_amount, 0) ELSE 0 END) AS trial,
                SUM(COALESCE(s.registration_amount, 0))                       AS total
            FROM agent_subscriptions s
            WHERE s.created_at >= DATE_SUB(UTC_TIMESTAMP(), INTERVAL 12 MONTH)
            AND LOWER(s.payment_status) = 'completed'
            GROUP BY label, yr, mo
            ORDER BY yr ASC, mo ASC
        """)
        monthly_revenue_cols = [col[0] for col in cursor.description]
        monthly_revenue = [dict(zip(monthly_revenue_cols, row)) for row in cursor.fetchall()]

        # 2. Active agent counts
        excluded_statuses = ('suspended', 'incomplete', 'pending_payment', 'pending')
        placeholders = ','.join(['%s'] * len(excluded_statuses))
        
        cursor.execute(f"SELECT COUNT(*) FROM agents WHERE plan_type = 'professional' AND status NOT IN ({placeholders})", excluded_statuses)
        prof_count = cursor.fetchone()[0]

        cursor.execute(f"SELECT COUNT(*) FROM agents WHERE plan_type = 'basic' AND status NOT IN ({placeholders})", excluded_statuses)
        starter_count = cursor.fetchone()[0]

        cursor.execute(f"SELECT COUNT(*) FROM agents WHERE plan_type = 'free_trial' AND status NOT IN ({placeholders})", excluded_statuses)
        trial_count = cursor.fetchone()[0]

        total_subs = prof_count + starter_count + trial_count

        # 3. Revenue collected per plan (all-time, completed payments)
        cursor.execute("SELECT SUM(registration_amount) FROM agent_subscriptions WHERE payment_status = 'completed' AND LOWER(selected_plan) LIKE '%%professional%%'")
        pro_revenue = cursor.fetchone()[0] or 0

        cursor.execute("SELECT SUM(registration_amount) FROM agent_subscriptions WHERE payment_status = 'completed' AND LOWER(selected_plan) LIKE '%%starter%%'")
        starter_revenue = cursor.fetchone()[0] or 0

        cursor.execute("SELECT SUM(registration_amount) FROM agent_subscriptions WHERE payment_status = 'completed' AND LOWER(selected_plan) LIKE '%%trial%%'")
        trial_revenue = cursor.fetchone()[0] or 0

        total_revenue = float(pro_revenue) + float(starter_revenue) + float(trial_revenue)

        # 4. MRR
        mrr_query = """
            SELECT SUM(s.registration_amount / GREATEST(1, TIMESTAMPDIFF(MONTH, s.starts_at, COALESCE(s.expires_at, DATE_ADD(s.starts_at, INTERVAL 12 MONTH))))) as monthly
            FROM agent_subscriptions s
            JOIN agents a ON s.agent_id = a.id
            WHERE a.plan_type = %s
            AND s.payment_status = 'completed'
            AND (s.expires_at IS NULL OR s.expires_at > UTC_TIMESTAMP())
        """
        cursor.execute(mrr_query, ['professional'])
        pro_mrr_raw = cursor.fetchone()[0] or 0

        cursor.execute(mrr_query, ['basic'])
        starter_mrr_raw = cursor.fetchone()[0] or 0

        mrr = int(round(float(pro_mrr_raw) + float(starter_mrr_raw)))
        arr = mrr * 12

        # 5. Revenue this month vs last month
        now = datetime.datetime.now()
        cursor.execute("SELECT SUM(registration_amount) FROM agent_subscriptions WHERE MONTH(created_at) = %s AND YEAR(created_at) = %s AND payment_status = 'completed'", [now.month, now.year])
        revenue_this_month = float(cursor.fetchone()[0] or 0)

        last_month = now.replace(day=1) - datetime.timedelta(days=1)
        cursor.execute("SELECT SUM(registration_amount) FROM agent_subscriptions WHERE MONTH(created_at) = %s AND YEAR(created_at) = %s AND payment_status = 'completed'", [last_month.month, last_month.year])
        revenue_last_month = float(cursor.fetchone()[0] or 0)

        if revenue_last_month > 0:
            revenue_growth = round(((revenue_this_month - revenue_last_month) / revenue_last_month) * 100, 1)
        else:
            revenue_growth = 100 if revenue_this_month > 0 else 0

        # 6. Recent subscriptions
        cursor.execute("""
            SELECT 
                s.*, 
                a.fullname, 
                a.email, 
                ap.display_name
            FROM agent_subscriptions s
            JOIN agents a ON s.agent_id = a.id
            LEFT JOIN agent_profiles ap ON a.id = ap.agent_id
            WHERE s.payment_status = 'completed'
            ORDER BY s.created_at DESC
            LIMIT 15
        """)
        subs_cols = [col[0] for col in cursor.description]
        recent_subs = [dict(zip(subs_cols, row)) for row in cursor.fetchall()]

    # To pass Chart data to JS easily
    labels = []
    prof_data = []
    starter_data = []
    trial_data = []
    for item in monthly_revenue:
        labels.append(item['label'])
        prof_data.append(float(item['professional'] or 0))
        starter_data.append(float(item['starter'] or 0))
        trial_data.append(float(item['trial'] or 0))

    pro_bar = round((float(pro_revenue) / total_revenue) * 100) if total_revenue > 0 else 0
    starter_bar = round((float(starter_revenue) / total_revenue) * 100) if total_revenue > 0 else 0
    trial_bar = max(0, 100 - pro_bar - starter_bar) if total_revenue > 0 else 0

    context = {
        'admin': admin,
        'profCount': prof_count,
        'starterCount': starter_count,
        'trialCount': trial_count,
        'totalSubs': total_subs,
        'mrr': mrr,
        'arr': arr,
        'revenueThisMonth': revenue_this_month,
        'revenueLastMonth': revenue_last_month,
        'revenueGrowth': revenue_growth,
        'totalRevenue': total_revenue,
        'proRevenue': float(pro_revenue),
        'starterRevenue': float(starter_revenue),
        'trialRevenue': float(trial_revenue),
        'proBar': pro_bar,
        'starterBar': starter_bar,
        'trialBar': trial_bar,
        'recentSubs': recent_subs,
        'chart_labels': json.dumps(labels),
        'chart_prof': json.dumps(prof_data),
        'chart_starter': json.dumps(starter_data),
        'chart_trial': json.dumps(trial_data),
    }

    return render(request, 'admin/revenue/dashboard.html', context)
