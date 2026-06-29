import json
from datetime import datetime, timedelta
from django.shortcuts import render
from django.db import connection
from django.db.models import Count, Sum, Case, When, IntegerField
from django.db.models.functions import Coalesce
from django.utils import timezone
from apps.admin_panel.decorators import admin_login_required
from apps.agents.models import Agent, AgentSubscription, AgentLead, AgentReview, AgentProfileView
from apps.admin_panel.models import ContactSubmission

@admin_login_required
def admin_dashboard(request):
    try:
        # 1. Period (months)
        try:
            period_months = int(request.GET.get('period', 12))
            if period_months not in [3, 6, 12]:
                period_months = 12
        except ValueError:
            period_months = 12

        # 2. Total Agents
        total_agents = Agent.objects.count()

        # 3. Active Agents
        active_count = Agent.objects.filter(status='active').count()
        active_percent = round((active_count / total_agents) * 100) if total_agents > 0 else 0

        # 4. Growth
        now = timezone.now()
        new_this_month = Agent.objects.filter(
            created_at__month=now.month,
            created_at__year=now.year
        ).count()
        
        # Previous month calculation
        first_day_this_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        last_day_last_month = first_day_this_month - timedelta(days=1)
        prev_month = last_day_last_month.month
        prev_month_year = last_day_last_month.year
        
        last_month_count = Agent.objects.filter(
            created_at__month=prev_month,
            created_at__year=prev_month_year
        ).count()
        
        growth_percent = round(((new_this_month - last_month_count) / last_month_count) * 100) if last_month_count > 0 else 0

        # 5. Distributors
        # Based on: DB::table('agents')->where('user_types', 'LIKE', '%distributor%')->orWhere('profession', 'LIKE', '%distributor%')->count()
        distributors = Agent.objects.filter(user_types__icontains='distributor').count()

        # 6. Retention Rate
        retention_rate = active_percent

        # 7. Subscription Plans Breakdown
        raw_plans = AgentSubscription.objects.values('selected_plan').annotate(c=Count('id'))
        plan_breakdown = {}
        for entry in raw_plans:
            plan_key = (entry['selected_plan'] or '').strip()
            count = entry['c']
            name = plan_key
            if '{' in plan_key:
                try:
                    decoded = json.loads(plan_key)
                    name = decoded.get('name') or decoded.get('type') or 'Other'
                except json.JSONDecodeError:
                    pass
            plan_breakdown[name] = plan_breakdown.get(name, 0) + count

        total_subs = sum(plan_breakdown.values())
        prof_count = plan_breakdown.get("Professional's Plan", 0) + plan_breakdown.get("Professional Plan", 0)
        starter_count = plan_breakdown.get("Starter's Plan", 0) + plan_breakdown.get("Starter Plan", 0)
        upgrade_rate = round((prof_count / total_subs) * 100) if total_subs > 0 else 0

        # 8. Page Views (from shared sessions table)
        with connection.cursor() as cursor:
            try:
                cursor.execute("SELECT COUNT(*) FROM sessions")
                page_views = cursor.fetchone()[0]
            except Exception:
                page_views = 0

        # 9. Leads
        total_leads = AgentLead.objects.count()
        new_leads_today = AgentLead.objects.filter(created_at__date=now.date()).count()

        # 10. Reviews
        pending_reviews = AgentReview.objects.filter(is_approved=False).count()
        total_reviews = AgentReview.objects.count()

        # 11. Contacts
        pending_contacts = ContactSubmission.objects.filter(status='pending').count()

        # 12. Profile Views
        try:
            profile_views = AgentProfileView.objects.count()
        except Exception:
            profile_views = 0

        # 13. Top Agents by Leads
        top_agents_by_leads = Agent.objects.annotate(
            lead_count=Count('leads'),
            whatsapp_count=Coalesce(
                Sum(Case(When(leads__interaction_type='whatsapp', then=1), default=0, output_field=IntegerField())),
                0
            ),
            call_count=Coalesce(
                Sum(Case(When(leads__interaction_type='call', then=1), default=0, output_field=IntegerField())),
                0
            )
        ).filter(lead_count__gt=0).order_by('-lead_count')[:5]

        # 14. Recent Leads
        recent_leads = AgentLead.objects.select_related('agent').order_by('-created_at')[:5]

        # 15. Month-over-Month Registration Data (Raw SQL matching Laravel)
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT DATE_FORMAT(created_at, '%%b %%y') as label, COUNT(*) as total 
                FROM agents 
                WHERE created_at >= DATE_SUB(LAST_DAY(UTC_TIMESTAMP()), INTERVAL %s MONTH)
                GROUP BY label, YEAR(created_at), MONTH(created_at)
                ORDER BY YEAR(created_at) ASC, MONTH(created_at) ASC
            """, [period_months])
            rows = cursor.fetchall()
            mom_data = [{'label': r[0], 'total': r[1]} for r in rows]

        # 16. City Data (Raw SQL matching Laravel)
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT COALESCE(ap.address, 'Other') as label, COUNT(*) as total 
                FROM agents a
                LEFT JOIN agent_profiles ap ON a.id = ap.agent_id
                GROUP BY label 
                ORDER BY total DESC 
                LIMIT 8
            """)
            rows = cursor.fetchall()
            city_data = [{'label': r[0], 'total': r[1]} for r in rows]

        # 17. Renewal Stats (Raw SQL matching Laravel)
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT 
                    SUM(CASE WHEN expires_at < UTC_TIMESTAMP() THEN 1 ELSE 0 END) as expired,
                    SUM(CASE WHEN expires_at BETWEEN UTC_TIMESTAMP() AND DATE_ADD(UTC_TIMESTAMP(), INTERVAL 30 DAY) THEN 1 ELSE 0 END) as next_30,
                    SUM(CASE WHEN expires_at BETWEEN DATE_ADD(UTC_TIMESTAMP(), INTERVAL 31 DAY) AND DATE_ADD(UTC_TIMESTAMP(), INTERVAL 60 DAY) THEN 1 ELSE 0 END) as next_60,
                    SUM(CASE WHEN expires_at BETWEEN DATE_ADD(UTC_TIMESTAMP(), INTERVAL 61 DAY) AND DATE_ADD(UTC_TIMESTAMP(), INTERVAL 90 DAY) THEN 1 ELSE 0 END) as next_90
                FROM agent_subscriptions
            """)
            row = cursor.fetchone()
            renewal_stats = {
                'expired': row[0] or 0 if row else 0,
                'next_30': row[1] or 0 if row else 0,
                'next_60': row[2] or 0 if row else 0,
                'next_90': row[3] or 0 if row else 0,
            }

        # 18. Pending Approvals (for Quick Actions badge)
        pending_approvals = Agent.objects.exclude(status='active').count()

    except Exception as e:
        # Fallback/Default values in case of database errors
        total_agents = 0
        active_count = 0
        active_percent = 0
        new_this_month = 0
        growth_percent = 0
        distributors = 0
        retention_rate = 0
        upgrade_rate = 0
        page_views = 0
        total_leads = 0
        new_leads_today = 0
        pending_reviews = 0
        total_reviews = 0
        pending_contacts = 0
        profile_views = 0
        top_agents_by_leads = []
        recent_leads = []
        mom_data = []
        city_data = []
        renewal_stats = {'expired': 0, 'next_30': 0, 'next_60': 0, 'next_90': 0}
        plan_breakdown = {}
        starter_count = 0
        prof_count = 0
        total_subs = 0
        pending_approvals = 0

    # Format numbers with commas for display
    context = {
        'periodMonths': period_months,
        'totalAgents': total_agents,
        'activeCount': active_count,
        'activePercent': active_percent,
        'newThisMonth': new_this_month,
        'growthPercent': growth_percent,
        'distributors': distributors,
        'retentionRate': retention_rate,
        'upgradeRate': upgrade_rate,
        'pageViews': page_views,
        'totalLeads': total_leads,
        'newLeadsToday': new_leads_today,
        'leadsAvg': round(total_leads / max(1, total_agents), 1) if total_agents > 0 else 0.0,
        'pendingReviews': pending_reviews,
        'totalReviews': total_reviews,
        'pendingContacts': pending_contacts,
        'profileViews': profile_views,
        'topAgentsByLeads': top_agents_by_leads,
        'recentLeads': recent_leads,
        'renewalStats': renewal_stats,
        'planBreakdown': plan_breakdown,
        'starterCount': starter_count,
        'profCount': prof_count,
        'totalSubs': total_subs,
        'pending_approvals': pending_approvals,
        
        # JSON strings for ChartJS initialization
        'mom_labels_json': json.dumps([r['label'] for r in mom_data]),
        'mom_totals_json': json.dumps([r['total'] for r in mom_data]),
        'plan_keys_json': json.dumps(list(plan_breakdown.keys())),
        'plan_values_json': json.dumps(list(plan_breakdown.values())),
    }

    return render(request, 'admin/dashboard.html', context)
