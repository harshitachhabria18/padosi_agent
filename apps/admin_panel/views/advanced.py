import json
from datetime import datetime, timedelta
from django.shortcuts import render
from django.db import connection
from django.db.models import Count, Avg, Q
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.core.paginator import Paginator
from django.http import JsonResponse
from apps.admin_panel.decorators import admin_login_required
from apps.agents.models import Agent, AgentLead, AgentProfileView
from apps.admin_panel.models import AdminActivityLog, Admin

@admin_login_required
def analytics(request):
    try:
        # Timeframe filter (defaults to 30 days)
        timeframe = request.GET.get('timeframe', '30')
        if timeframe not in ['7', '30', '90', '365']:
            timeframe = '30'
        timeframe_days = int(timeframe)
        
        start_date = timezone.now() - timedelta(days=timeframe_days)

        # 1. Top Agents by Leads
        top_leads = Agent.objects.annotate(
            leads_count=Count('leads', filter=Q(leads__created_at__gte=start_date))
        ).filter(leads_count__gt=0).select_related('profile').order_by('-leads_count')[:10]

        for agent in top_leads:
            latest_sub = agent.subscriptions.all().order_by('-id').first()
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
            
            user_types = agent.user_types or []
            if isinstance(user_types, str):
                try:
                    user_types = json.loads(user_types)
                except json.JSONDecodeError:
                    user_types = [user_types]
            agent.formatted_types = ', '.join([t.capitalize() for t in user_types if t]) or 'Agent'

        # 2. Top Agents by Profile Views
        top_views = Agent.objects.annotate(
            profile_views_count=Count('profile_views', filter=Q(profile_views__created_at__gte=start_date)),
            avg_rating=Coalesce(Avg('reviews__rating', filter=Q(reviews__is_approved=True)), 0.0)
        ).filter(profile_views_count__gt=0).select_related('profile').order_by('-profile_views_count')[:10]

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
        overall_leads = AgentLead.objects.filter(created_at__gte=start_date).count()
        overall_views = AgentProfileView.objects.filter(created_at__gte=start_date).count()
        conversion_rate = round((overall_leads / overall_views) * 100, 2) if overall_views > 0 else 0.00

        # 4. Daily leads breakdown (last 30 days)
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT
                    DATE_FORMAT(created_at, '%%d %%b') as label,
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

    except Exception:
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


@admin_login_required
def activity_logs(request):
    logs_list = AdminActivityLog.objects.all().order_by('-id')
    total_records = logs_list.count()
    
    paginator = Paginator(logs_list, 50)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    # Bulk fetch admin details
    admin_ids = {log.admin_id for log in page_obj if log.admin_id}
    admins = {admin.id: admin for admin in Admin.objects.filter(id__in=admin_ids)}
    
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
            try:
                last_active_admin_name = Admin.objects.get(id=last_log.admin_id).name
            except Admin.DoesNotExist:
                pass

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


@admin_login_required
def delete_activity_log(request):
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
