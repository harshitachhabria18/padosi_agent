import json
from datetime import datetime, timedelta
from django.shortcuts import render, redirect
from django.db import connection
from django.db.models import Count, Avg, Q
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.core.paginator import Paginator
from django.http import JsonResponse
from apps.admin_panel.views.dashboard import _get_admin_from_session
from apps.admin_panel.models import Agent
from apps.admin_panel.models import AdminActivityLog
def analytics(request):
    admin = _get_admin_from_session(request)
    if not admin:
        return redirect('admin_login_page')

    try:
        # Timeframe filter (defaults to 30 days)
        timeframe = request.GET.get('timeframe', '30')
        if timeframe not in ['7', '30', '90', '365']:
            timeframe = '30'
        timeframe_days = int(timeframe)
        
        start_date = timezone.now() - timedelta(days=timeframe_days)

        # 1. Top Agents by Leads
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT a.id, COUNT(l.id) as leads_count 
                FROM agents a 
                JOIN agent_leads l ON a.id = l.agent_id 
                WHERE l.created_at >= %s 
                GROUP BY a.id 
                HAVING leads_count > 0 
                ORDER BY leads_count DESC 
                LIMIT 10
            """, [start_date])
            top_leads_data = cursor.fetchall()
            
            top_leads = []
            if top_leads_data:
                agent_ids = [row[0] for row in top_leads_data]
                agents_qs = Agent.objects.filter(id__in=agent_ids)
                agent_dict = {a.id: a for a in agents_qs}
                
                from apps.admin_panel.models import AgentProfile, AgentSubscription
                profiles = {p.agent_id: p for p in AgentProfile.objects.filter(agent_id__in=agent_ids)}
                
                for row in top_leads_data:
                    agent = agent_dict.get(row[0])
                    if agent:
                        agent.leads_count = row[1]
                        agent.profile = profiles.get(agent.id)
                        top_leads.append(agent)


        for agent in top_leads:
            latest_sub = AgentSubscription.objects.filter(agent_id=agent.id).order_by('-id').first()
            plan_label = ''
            is_pro = False
            if latest_sub:
                plan_raw = (latest_sub.selected_plan or '').strip()
                plan_label = plan_raw
                if '{' in plan_raw:
                    try:
                        decoded = json.loads(plan_raw)
                        plan_label = decoded.get('name') or decoded.get('type') or plan_raw
                    except json.JSONDecodeError:
                        pass
                is_pro = 'professional' in plan_label.lower() or 'pro' in plan_label.lower()
            
            agent.plan_label = plan_label
            agent.is_pro = is_pro
            
            user_types = getattr(agent, 'user_types', None) or []
            if isinstance(user_types, str):
                try:
                    user_types = json.loads(user_types)
                except json.JSONDecodeError:
                    user_types = [user_types]
            agent.formatted_types = ', '.join([t.capitalize() for t in user_types if t]) or 'Agent'

        # 2. Top Agents by Profile Views
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT a.id, COUNT(v.id) as profile_views_count,
                       (SELECT COALESCE(AVG(rating), 0) FROM agent_reviews WHERE agent_id = a.id AND is_approved = 1) as avg_rating
                FROM agents a 
                JOIN agent_profile_views v ON a.id = v.agent_id 
                WHERE v.created_at >= %s 
                GROUP BY a.id 
                HAVING profile_views_count > 0 
                ORDER BY profile_views_count DESC 
                LIMIT 10
            """, [start_date])
            top_views_data = cursor.fetchall()

            top_views = []
            if top_views_data:
                agent_ids = [row[0] for row in top_views_data]
                agents_qs = Agent.objects.filter(id__in=agent_ids)
                agent_dict = {a.id: a for a in agents_qs}
                
                from apps.admin_panel.models import AgentProfile
                profiles = {p.agent_id: p for p in AgentProfile.objects.filter(agent_id__in=agent_ids)}
                
                for row in top_views_data:
                    agent = agent_dict.get(row[0])
                    if agent:
                        agent.profile_views_count = row[1]
                        agent.avg_rating = row[2]
                        agent.profile = profiles.get(agent.id)
                        top_views.append(agent)


        for agent in top_views:
            # Precalculate rating stars list (full, half, empty) matching the average rating
            stars = round(float(agent.avg_rating or 0) * 2) / 2
            star_list = []
            for s in range(1, 6):
                if s <= stars:
                    star_list.append('full')
                elif s - 0.5 <= stars:
                    star_list.append('half')
                else:
                    star_list.append('empty')
            agent.precalculated_stars = star_list

        # 3. Overall stats
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM agent_leads WHERE created_at >= %s", [start_date])
            overall_leads = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM agent_profile_views WHERE created_at >= %s", [start_date])
            overall_views = cursor.fetchone()[0]
        conversion_rate = round((overall_leads / overall_views) * 100, 2) if overall_views > 0 else 0.00

        # 4. Daily leads breakdown (last 30 days)
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT
                    DATE_FORMAT(created_at, '%d %b') as label,
                    DATE(created_at) as date,
                    SUM(CASE WHEN interaction_type = 'whatsapp' THEN 1 ELSE 0 END) as whatsapp,
                    SUM(CASE WHEN interaction_type = 'call' THEN 1 ELSE 0 END) as `call`
                FROM agent_leads
                WHERE created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)
                GROUP BY DATE(created_at), label
                ORDER BY DATE(created_at) ASC
            """)
            rows = cursor.fetchall()
            daily_leads = [
                {'label': r[0], 'whatsapp': int(r[2] or 0), 'call': int(r[3] or 0)} for r in rows
            ]

    except Exception as e:
        import traceback
        traceback.print_exc()
        top_leads = []
        top_views = []
        overall_leads = 0
        overall_views = 0
        conversion_rate = 0.00
        daily_leads = []
        timeframe = '30'

    context = {
        'topLeads': top_leads,
        'topViews': top_views,
        'timeframe': timeframe,
        'overallLeads': overall_leads,
        'overallViews': overall_views,
        'conversionRate': conversion_rate,
        'daily_leads_labels_json': json.dumps([r['label'] for r in daily_leads]),
        'daily_leads_whatsapp_json': json.dumps([r['whatsapp'] for r in daily_leads]),
        'daily_leads_call_json': json.dumps([r['call'] for r in daily_leads]),
    }

    return render(request, 'admin/analytics.html', context)


def activity_logs(request):
    admin = _get_admin_from_session(request)
    if not admin:
        return redirect('admin_login_page')

    logs_list = AdminActivityLog.objects.all().order_by('-id')
    total_records = logs_list.count()
    
    paginator = Paginator(logs_list, 50)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    # Bulk fetch admin details
    admin_ids = {log.admin_id for log in page_obj if log.admin_id}
    admins = {}
    if admin_ids:
        placeholders = ', '.join(['%s'] * len(admin_ids))
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT id, name FROM admins WHERE id IN ({placeholders})", list(admin_ids))
            for row in cursor.fetchall():
                admins[row[0]] = type('AdminObj', (), {'id': row[0], 'name': row[1]})
    
    # Calculate statistics based on the paginated page collection (matching Laravel's local collection counts)
    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    actions_today = sum(1 for log in page_obj if log.created_at >= today_start)
    
    page_actions = [log.action for log in page_obj if log.action]
    action_types_set = {act.strip().split()[0] for act in page_actions if act.strip()}
    action_types_count = len(action_types_set)
    
    last_log = page_obj[0] if page_obj else None
    last_active_admin_name = 'N/A'
    if last_log and last_log.admin_id:
        admin_obj = admins.get(last_log.admin_id)
        if admin_obj:
            last_active_admin_name = admin_obj.name
        else:
            with connection.cursor() as cursor:
                cursor.execute("SELECT name FROM admins WHERE id = %s", [last_log.admin_id])
                row = cursor.fetchone()
                if row:
                    last_active_admin_name = row[0]

    for log in page_obj:
        log.admin_obj = admins.get(log.admin_id)
        
        # Categorize for template badges/icons
        act = (log.action or '').lower()
        if any(w in act for w in ['login', 'logout', 'auth']):
            log.badge_class, log.badge_icon = 'type-auth', 'fa-key'
        elif any(w in act for w in ['agent', 'approv', 'suspend']):
            log.badge_class, log.badge_icon = 'type-agent', 'fa-user-gear'
        elif any(w in act for w in ['plan', 'pricing', 'subscri']):
            log.badge_class, log.badge_icon = 'type-plan', 'fa-tags'
        elif any(w in act for w in ['broadcast', 'message', 'sent']):
            log.badge_class, log.badge_icon = 'type-broadcast', 'fa-paper-plane'
        elif 'lead' in act:
            log.badge_class, log.badge_icon = 'type-lead', 'fa-bolt'
        elif any(w in act for w in ['review', 'rating']):
            log.badge_class, log.badge_icon = 'type-review', 'fa-star'
        elif any(w in act for w in ['setting', 'config', 'update']):
            log.badge_class, log.badge_icon = 'type-settings', 'fa-sliders'
        elif any(w in act for w in ['banner', 'faq', 'page', 'content']):
            log.badge_class, log.badge_icon = 'type-content', 'fa-file-pen'
        else:
            log.badge_class, log.badge_icon = 'type-default', 'fa-circle-dot'

        # Details serialization helper
        log.details_display = json.dumps(log.details) if isinstance(log.details, (dict, list)) else str(log.details or '')

    context = {
        'logs': page_obj,
        'total_records': total_records,
        'actions_today': actions_today,
        'action_types_count': action_types_count,
        'last_active_admin_name': last_active_admin_name,
    }
    return render(request, 'admin/activity-logs.html', context)


def delete_activity_log(request):
    admin = _get_admin_from_session(request)
    if not admin:
        return JsonResponse({'success': False, 'message': 'Unauthorized'}, status=401)

    if request.method == 'POST':
        log_id = request.POST.get('id')
        if log_id:
            try:
                log = AdminActivityLog.objects.get(id=log_id)
                log.delete()
                return JsonResponse({'success': True, 'message': 'Activity log deleted successfully.'})
            except AdminActivityLog.DoesNotExist:
                return JsonResponse({'success': False, 'message': 'Log record not found.'})
    return JsonResponse({'success': False, 'message': 'Invalid request.'})
