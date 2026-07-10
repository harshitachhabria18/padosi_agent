import logging
from django.utils import timezone
from django.db import connection
from django.shortcuts import render, redirect
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.contrib import messages
import json

from .dashboard import _get_admin_from_session

logger = logging.getLogger(__name__)

def _build_agent_list_query(search, plan_filter, status_filter, city_filter, promo_code_filter):
    """
    Builds the raw SQL query and params for the agent list based on Laravel logic.
    """
    query = """
        SELECT
            a.id, a.fullname, a.email, a.mobile, a.status, a.created_at, a.badge,
            ap.address, ap.display_name,
            s.selected_plan, s.expires_at,
            (SELECT AVG(rating) FROM agent_reviews WHERE agent_id = a.id AND is_approved = 1) AS avg_rating,
            (SELECT COUNT(*) FROM agent_reviews WHERE agent_id = a.id AND is_approved = 1) AS review_count
        FROM agents AS a
        LEFT JOIN agent_profiles AS ap ON a.id = ap.agent_id
        LEFT JOIN agent_subscriptions AS s ON a.id = s.agent_id
            AND s.id = (SELECT MAX(id) FROM agent_subscriptions WHERE agent_id = a.id)
        WHERE 1=1
    """
    params = []

    if search:
        query += " AND (a.fullname LIKE %s OR a.email LIKE %s OR ap.display_name LIKE %s)"
        search_param = f"%{search}%"
        params.extend([search_param, search_param, search_param])
        
    if plan_filter and plan_filter != 'All Plans':
        query += " AND s.selected_plan = %s"
        params.append(plan_filter)

    # Status Filter logic
    if status_filter and status_filter != 'All Status':
        query += " AND a.status = %s"
        params.append(status_filter)
    elif not status_filter and not promo_code_filter:
        # Default behavior if status_filter is None/empty and no promo code filter: only active agents
        query += " AND a.status = 'active'"

    if promo_code_filter:
        query += """ AND (
            EXISTS (SELECT 1 FROM invoices WHERE invoices.agent_id = a.id AND invoices.promo_code = %s)
            OR
            EXISTS (SELECT 1 FROM free_trial_history WHERE free_trial_history.agent_id = a.id AND free_trial_history.promo_code = %s)
        )"""
        params.extend([promo_code_filter, promo_code_filter])

    if city_filter:
        query += " AND ap.address LIKE %s"
        params.append(f"%{city_filter}%")

    query += " ORDER BY a.id DESC"
    
    return query, params


def agent_list(request):
    """
    Phase 3B: Active Agents Listing View
    """
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return redirect('admin_login')

    search = request.GET.get('search', '')
    plan_filter = request.GET.get('plan', 'All Plans')
    status_filter = request.GET.get('status', 'All Status')
    city_filter = request.GET.get('city', '')
    promo_code_filter = request.GET.get('promo_code', '')

    query, params = _build_agent_list_query(search, plan_filter, status_filter, city_filter, promo_code_filter)
    
    agents = []
    try:
        with connection.cursor() as cursor:
            cursor.execute(query, params)
            columns = [col[0] for col in cursor.description]
            agents = [dict(zip(columns, row)) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Error fetching agents list: {e}")

    paginator = Paginator(agents, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'agents': agents,
        'search': search,
        'plan_filter': plan_filter,
        'status_filter': status_filter,
        'city_filter': city_filter,
        'promo_code': promo_code_filter,
        'page_obj': page_obj,
    }
    
    return render(request, 'admin/agents/list.html', context)


def manage_agent(request, id):
    """
    Phase 3C: Manage Agent View (Read-Only)
    """
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return redirect('admin_login')

    # 1. Fetch Agent Details via raw SQL mimicking Laravel's showManageAgent
    agent = None
    query = """
        SELECT
            a.id, a.fullname, a.email, a.mobile, a.status, a.created_at, a.experience_range, a.admin_notes, a.achievement_photo_limit,
            ap.address, ap.license_number, ap.experience_years, ap.office_address, ap.pan_number, ap.profile_photo_path,
            ap.is_profile_visible, ap.show_certificates, ap.show_achievements, ap.show_reviews,
            s.selected_plan, s.expires_at,
            (SELECT AVG(rating) FROM agent_reviews WHERE agent_id = a.id AND is_approved = 1) as avg_rating,
            (SELECT COUNT(*) FROM agent_reviews WHERE agent_id = a.id AND is_approved = 1) as review_count,
            (SELECT COUNT(*) FROM agent_reviews WHERE agent_id = a.id AND is_approved = 0) as pending_reviews
        FROM agents AS a
        LEFT JOIN agent_profiles AS ap ON a.id = ap.agent_id
        LEFT JOIN agent_subscriptions AS s ON a.id = s.agent_id
            AND s.id = (SELECT MAX(id) FROM agent_subscriptions WHERE agent_id = a.id)
        WHERE a.id = %s
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute(query, [id])
            row = cursor.fetchone()
            if row:
                columns = [col[0] for col in cursor.description]
                agent = dict(zip(columns, row))
    except Exception as e:
        logger.error(f"Error fetching agent details: {e}")

    if not agent:
        return redirect('admin_agents')

    # 2. Fetch Recent Reviews via Raw SQL mimicking Laravel's showManageAgent
    reviews = []
    reviews_query = """
        SELECT 
            r.id, r.rating, r.review as review_text, r.is_approved, r.created_at,
            u.fullname as client_name
        FROM agent_reviews AS r
        LEFT JOIN users AS u ON r.user_id = u.id
        WHERE r.agent_id = %s
        ORDER BY r.created_at DESC
        LIMIT 10
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute(reviews_query, [id])
            columns = [col[0] for col in cursor.description]
            reviews = [dict(zip(columns, row)) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Error fetching agent reviews: {e}")

    # 3. Fetch Edit Logs using ORM
    # from admin_panel.models.agent_profile_edit_log import AgentProfileEditLog
    from ..models.agent_profile_edit_log import AgentProfileEditLog
    import json
    
    edit_logs_raw = AgentProfileEditLog.objects.filter(agent_id=id).order_by('-created_at', '-id')[:50]
    
    edit_logs = []
    for log in edit_logs_raw:
        parsed_changes = []
        if log.changes:
            try:
                parsed_changes = json.loads(log.changes)
            except json.JSONDecodeError:
                parsed_changes = []
                
        edit_logs.append({
            'id': log.id,
            'step': log.step,
            'step_label': log.step_label,
            'changes': parsed_changes,
            'status_before': log.status_before,
            'status_after': log.status_after,
            'edited_by': log.edited_by,
            'created_at': log.created_at,
        })

    context = {
        'agent': agent,
        'reviews': reviews,
        'edit_logs': edit_logs,
    }
    
    return render(request, 'admin/agents/manage.html', context)


def toggle_status(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request method'})
    
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return JsonResponse({'success': False, 'message': 'Unauthorized'})

    try:
        data = json.loads(request.body)
        agent_id = data.get('id')
        new_status = data.get('status')
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': 'Invalid JSON'})

    if not agent_id or not new_status:
        return JsonResponse({'success': False, 'message': 'Missing data'})

    # Fetch agent to get old_status
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT status FROM agents WHERE id = %s", [agent_id])
            row = cursor.fetchone()
            if not row:
                return JsonResponse({'success': False, 'message': 'Agent not found'})
            old_status = row[0]
            
            # Update status
            cursor.execute("UPDATE agents SET status = %s WHERE id = %s", [new_status, agent_id])
    except Exception as e:
        logger.error(f"Error updating agent status: {e}")
        return JsonResponse({'success': False, 'message': 'Database error'})

    # Log boundary change
    if new_status in ['active', 'suspended', 'rejected']:
        step_label = 'Status Changed by Admin'
        if new_status == 'active':
            step_label = 'Approved by Admin'
        elif new_status == 'suspended':
            step_label = 'Suspended by Admin'
            
        try:
            from ..models.agent_profile_edit_log import AgentProfileEditLog
            AgentProfileEditLog.objects.create(
                agent_id=int(agent_id),
                edited_by='admin',
                edited_by_id=admin_id,
                step=None,
                step_label=step_label,
                changes=json.dumps([]),
                ip_address=request.META.get('REMOTE_ADDR'),
                status_before=old_status,
                status_after=new_status,
                created_at=timezone.now(),
                updated_at=timezone.now(),
            )
        except Exception as e:
            print("AUDIT LOG ERROR:", repr(e))
            raise

    return JsonResponse({'success': True})


def bulk_action_agents(request):
    if request.method != 'POST':
        return redirect('admin_agents_approvals')

    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return redirect('admin_login')

    action = request.POST.get('action')
    agent_ids = request.POST.getlist('agent_ids[]')

    if not agent_ids:
        messages.error(request, 'No agents selected.')
        return redirect('admin_agents_approvals')

    if action == 'approve':
        try:
            from ..models.agent_profile_edit_log import AgentProfileEditLog
            with connection.cursor() as cursor:
                # Get existing statuses to log properly
                format_strings = ','.join(['%s'] * len(agent_ids))
                cursor.execute(f"SELECT id, status FROM agents WHERE id IN ({format_strings})", agent_ids)
                rows = cursor.fetchall()
                old_statuses = {row[0]: row[1] for row in rows}

                # Update statuses
                cursor.execute(f"UPDATE agents SET status = 'active' WHERE id IN ({format_strings})", agent_ids)

                for aid in agent_ids:
                    aid_int = int(aid)
                    old_status = old_statuses.get(aid_int, 'pending')
                    AgentProfileEditLog.objects.create(
                        agent_id=aid_int,
                        edited_by='admin',
                        edited_by_id=admin_id,
                        step=None,
                        step_label='Approved by Admin (Bulk)',
                        changes=json.dumps([]),
                        ip_address=request.META.get('REMOTE_ADDR'),
                        status_before=old_status,
                        status_after='active',
                        created_at=timezone.now(),
                        updated_at=timezone.now(),
                    )
            messages.success(request, 'Selected agents have been approved.')
        except Exception as e:
            logger.error(f"Bulk approve error: {e}")
            messages.error(request, 'Failed to bulk approve agents.')

    return redirect('admin_agents_approvals')


def update_badge(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request method'})
        
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return JsonResponse({'success': False, 'message': 'Unauthorized'})

    try:
        data = json.loads(request.body)
        agent_id = data.get('id')
        badge_data = data.get('badge')
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': 'Invalid JSON'})

    if not agent_id:
        return JsonResponse({'success': False, 'message': 'Missing agent ID'})

    if isinstance(badge_data, list):
        # Filter empty values and join by comma
        badge_value = ','.join(filter(None, badge_data))
    else:
        badge_value = badge_data if badge_data else ''

    try:
        with connection.cursor() as cursor:
            cursor.execute("UPDATE agents SET badge = %s WHERE id = %s", [badge_value, agent_id])
            if cursor.rowcount == 0:
                cursor.execute("SELECT id FROM agents WHERE id = %s", [agent_id])
                if not cursor.fetchone():
                    return JsonResponse({'success': False, 'message': 'Agent not found'})
    except Exception as e:
        logger.error(f"Error updating agent badge: {e}")
        return JsonResponse({'success': False, 'message': 'Database error'})

    return JsonResponse({'success': True})


def update_irdai_license(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request method'})
        
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return JsonResponse({'success': False, 'message': 'Unauthorized'})

    try:
        data = json.loads(request.body)
        agent_id = data.get('id')
        license_number = data.get('license_number')
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': 'Invalid JSON'})

    if not agent_id or license_number is None:
        return JsonResponse({'success': False, 'message': 'Missing required fields'})

    license_number = license_number.strip()

    try:
        with connection.cursor() as cursor:
            # Check if agent exists
            cursor.execute("SELECT id FROM agents WHERE id = %s", [agent_id])
            if not cursor.fetchone():
                return JsonResponse({'success': False, 'message': 'Agent not found'})
            
            # Check if agent profile exists
            cursor.execute("SELECT id FROM agent_profiles WHERE agent_id = %s", [agent_id])
            profile_exists = bool(cursor.fetchone())
            
            if profile_exists:
                cursor.execute(
                    "UPDATE agent_profiles SET license_number = %s, updated_at = %s WHERE agent_id = %s",
                    [license_number, timezone.now(), agent_id]
                )
            else:
                cursor.execute(
                    "INSERT INTO agent_profiles (agent_id, license_number, created_at, updated_at) VALUES (%s, %s, %s, %s)",
                    [agent_id, license_number, timezone.now(), timezone.now()]
                )
                
            return JsonResponse({'success': True, 'message': 'IRDAI license number updated successfully.'})
    except Exception as e:
        logger.error(f"Error updating agent IRDAI license: {e}")
        return JsonResponse({'success': False, 'message': 'Database error.'})


def save_agent_notes(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request method'})
        
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return JsonResponse({'success': False, 'message': 'Unauthorized'})

    try:
        data = json.loads(request.body)
        agent_id = data.get('id')
        notes = data.get('notes')
        admin_notes = data.get('admin_notes')
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': 'Invalid JSON'})

    if not agent_id:
        return JsonResponse({'success': False, 'message': 'Missing agent ID'})

    final_notes = notes if notes is not None else admin_notes

    try:
        with connection.cursor() as cursor:
            cursor.execute("UPDATE agents SET admin_notes = %s WHERE id = %s", [final_notes, agent_id])
            if cursor.rowcount == 0:
                cursor.execute("SELECT id FROM agents WHERE id = %s", [agent_id])
                if not cursor.fetchone():
                    return JsonResponse({'success': False, 'message': 'Agent not found'})
    except Exception as e:
        logger.error(f"Error saving agent notes: {e}")
        return JsonResponse({'success': False, 'message': 'Database error'})

    return JsonResponse({'success': True})


def update_visibility(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request method'})
        
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return JsonResponse({'success': False, 'message': 'Unauthorized'})

    try:
        data = json.loads(request.body)
        field = data.get('field')
        value = 1 if data.get('value') else 0
        agent_id = data.get('id')
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': 'Invalid JSON'})

    valid_fields = ['is_profile_visible', 'show_certificates', 'show_achievements', 'show_reviews']
    if field not in valid_fields:
        return JsonResponse({'success': False, 'message': 'Invalid field'})

    try:
        with connection.cursor() as cursor:
            # We construct the query safely using the whitelisted field string.
            query = f"UPDATE agent_profiles SET {field} = %s, updated_at = %s WHERE agent_id = %s"
            cursor.execute(query, [value, timezone.now(), agent_id])
    except Exception as e:
        logger.error(f"Error updating agent visibility: {e}")
        return JsonResponse({'success': False, 'message': 'Database error'})

    return JsonResponse({'success': True})


from django.contrib import messages

def update_achievement_limit(request):
    if request.method != 'POST':
        return redirect('admin_dashboard')
        
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return redirect('admin_login')

    agent_id = request.POST.get('id')
    raw_limit = request.POST.get('achievement_photo_limit')

    if not agent_id:
        messages.error(request, "Agent ID is required.")
        return redirect('admin_agents')
        
    agent_id = int(agent_id)

    # Check if the column exists
    try:
        with connection.cursor() as cursor:
            cursor.execute("SHOW COLUMNS FROM agents LIKE 'achievement_photo_limit'")
            if not cursor.fetchone():
                messages.error(request, 'Achievement limit column not found. Please run database migration first.')
                return redirect('admin_agents_manage', id=agent_id)
                
            cursor.execute("SELECT id FROM agents WHERE id = %s", [agent_id])
            if not cursor.fetchone():
                messages.error(request, 'Agent not found.')
                return redirect('admin_agents')

            cursor.execute("SELECT selected_plan FROM agent_subscriptions WHERE agent_id = %s ORDER BY id DESC LIMIT 1", [agent_id])
            plan_row = cursor.fetchone()
            selected_plan = plan_row[0] if plan_row else ''
            
    except Exception as e:
        logger.error(f"Error checking achievement limit schema: {e}")
        messages.error(request, 'Database error.')
        return redirect('admin_agents_manage', id=agent_id)

    plan_text = str(selected_plan).lower()
    default_limit = 10 if 'professional' in plan_text else 5

    new_limit = int(raw_limit) if raw_limit and raw_limit.strip() else None

    if new_limit is not None and new_limit < default_limit:
        messages.error(request, f"Custom limit cannot be lower than the default {default_limit} for this plan.")
        return redirect('admin_agents_manage', id=agent_id)

    try:
        with connection.cursor() as cursor:
            cursor.execute("UPDATE agents SET achievement_photo_limit = %s, updated_at = %s WHERE id = %s", [new_limit, timezone.now(), agent_id])
    except Exception as e:
        logger.error(f"Error updating agent achievement limit: {e}")
        messages.error(request, 'Database error updating limit.')
        return redirect('admin_agents_manage', id=agent_id)

    effective = new_limit if new_limit is not None else default_limit
    messages.success(request, f"Achievement photo limit updated successfully. Effective limit: {effective}")
    return redirect('admin_agents_manage', id=agent_id)


def update_plan(request):
    if request.method != 'POST':
        return redirect('admin_dashboard')
        
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return redirect('admin_login')

    agent_id = request.POST.get('id')
    new_plan = request.POST.get('selected_plan')

    if not agent_id or new_plan is None:
        messages.error(request, "Agent ID is required.")
        return redirect('admin_agents')
        
    agent_id = int(agent_id)

    try:
        with connection.cursor() as cursor:
            cursor.execute("SHOW COLUMNS FROM agent_subscriptions")
            columns = [row[0] for row in cursor.fetchall()]
            
            exists_query = "SELECT id FROM agent_subscriptions WHERE agent_id = %s"
            cursor.execute(exists_query, [agent_id])
            exists = bool(cursor.fetchone())

            if exists:
                update_cols = ["selected_plan = %s"]
                update_params = [new_plan]
                
                if 'updated_at' in columns:
                    update_cols.append("updated_at = %s")
                    update_params.append(timezone.now())
                    
                update_params.append(agent_id)
                update_sql = f"UPDATE agent_subscriptions SET {', '.join(update_cols)} WHERE agent_id = %s"
                cursor.execute(update_sql, update_params)
            else:
                payload = {
                    'agent_id': agent_id,
                    'selected_plan': new_plan,
                    'registration_amount': 0,
                    'status': 'active',
                    'payment_status': 'completed',
                    'created_at': timezone.now(),
                    'updated_at': timezone.now(),
                }
                
                if 'transaction_id' in columns:
                    payload['transaction_id'] = 'ADMIN_MANUAL'
                if 'is_active' in columns:
                    payload['is_active'] = 1
                if 'amount' in columns:
                    payload['amount'] = 0
                if 'price' in columns:
                    payload['price'] = 0
                if 'fee' in columns:
                    payload['fee'] = 0
                if 'plan_amount' in columns:
                    payload['plan_amount'] = 0
                    
                final_payload = {k: v for k, v in payload.items() if k in columns}
                
                keys = list(final_payload.keys())
                values = list(final_payload.values())
                placeholders = ', '.join(['%s'] * len(keys))
                keys_str = ', '.join(keys)
                
                insert_sql = f"INSERT INTO agent_subscriptions ({keys_str}) VALUES ({placeholders})"
                cursor.execute(insert_sql, values)

            # Map selected plan name to plan_type for agents table
            if new_plan == "Starter's Plan":
                plan_type = 'basic'
            elif new_plan == "Professional's Plan":
                plan_type = 'professional'
            elif 'trial' in new_plan.lower():
                plan_type = 'free_trial'
            else:
                plan_type = 'standard'

            cursor.execute(
                "UPDATE agents SET plan_type = %s, updated_at = %s WHERE id = %s",
                [plan_type, timezone.now(), agent_id]
            )

    except Exception as e:
        logger.error(f"Error updating agent plan: {e}")
        messages.error(request, 'Database error updating plan.')
        return redirect('admin_agents_manage', id=agent_id)

    messages.success(request, "Subscription plan updated successfully.")
    return redirect('admin_agents_manage', id=agent_id)


def toggle_review_approval(request):
    if request.method != 'POST':
        return redirect('admin_dashboard')
        
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return redirect('admin_login')

    review_id = request.POST.get('review_id')
    is_approved = request.POST.get('is_approved')
    agent_id = request.POST.get('agent_id') # To redirect back properly

    if not review_id or is_approved is None:
        messages.error(request, "Missing review approval parameters.")
        if agent_id:
            return redirect('admin_agents_manage', id=agent_id)
        return redirect('admin_agents')

    try:
        with connection.cursor() as cursor:
            cursor.execute("UPDATE agent_reviews SET is_approved = %s WHERE id = %s", [is_approved, review_id])
    except Exception as e:
        logger.error(f"Error toggling review approval: {e}")
        messages.error(request, 'Database error.')
        if agent_id:
            return redirect('admin_agents_manage', id=agent_id)
        return redirect('admin_agents')

    messages.success(request, "Review status updated.")
    if agent_id:
        return redirect('admin_agents_manage', id=agent_id)
    return redirect('admin_agents')


def update_profile(request):
    if request.method != 'POST':
        return redirect('admin_dashboard')
        
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return redirect('admin_login')

    agent_id = request.POST.get('id')
    fullname = request.POST.get('fullname')
    email = request.POST.get('email')
    mobile = request.POST.get('mobile')
    experience_range = request.POST.get('experience_range')
    address = request.POST.get('address')
    office_address = request.POST.get('office_address')
    license_number = request.POST.get('license_number')
    pan_number = request.POST.get('pan_number')

    if not agent_id:
        messages.error(request, "Agent ID is required.")
        return redirect('admin_agents')
        
    agent_id = int(agent_id)

    try:
        with connection.cursor() as cursor:
            # Update agents table
            cursor.execute("""
                UPDATE agents 
                SET fullname = %s, email = %s, mobile = %s, experience_range = %s, updated_at = %s 
                WHERE id = %s
            """, [fullname, email, mobile, experience_range, timezone.now(), agent_id])

            # Update agent_profiles table
            cursor.execute("""
                UPDATE agent_profiles 
                SET address = %s, office_address = %s, license_number = %s, pan_number = %s, experience_years = %s, updated_at = %s 
                WHERE agent_id = %s
            """, [address, office_address, license_number, pan_number, experience_range, timezone.now(), agent_id])
            
    except Exception as e:
        logger.error(f"Error updating agent profile: {e}")
        messages.error(request, 'Database error updating profile.')
        return redirect('admin_agents_manage', id=agent_id)

    messages.success(request, "Agent profile updated successfully.")
    return redirect('admin_agents_manage', id=agent_id)


def get_agent_json(request, id):
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return JsonResponse({'success': False, 'message': 'Unauthorized'})

    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT 
                    a.id, a.fullname, a.email, a.mobile as phone, a.status, ap.address as location,
                    ap.license_number as license, ap.experience_years as experience, a.admin_notes,
                    s.selected_plan
                FROM agents AS a
                LEFT JOIN agent_profiles AS ap ON a.id = ap.agent_id
                LEFT JOIN agent_subscriptions AS s ON a.id = s.agent_id
                    AND s.id = (SELECT MAX(id) FROM agent_subscriptions WHERE agent_id = a.id)
                WHERE a.id = %s
            """, [id])
            
            row = cursor.fetchone()
            if row:
                columns = [col[0] for col in cursor.description]
                agent = dict(zip(columns, row))
                return JsonResponse({'success': True, 'agent': agent})
                
    except Exception as e:
        logger.error(f"Error getting agent json: {e}")
        
    return JsonResponse({'success': False})


from django.utils.timesince import timesince
from django.db.models import Q

def get_edit_logs(request, id):
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return JsonResponse({'success': False, 'message': 'Unauthorized'})

    try:
        from ..models.agent_profile_edit_log import AgentProfileEditLog
        
        # Step 1: Find the last time admin approved this agent
        last_approved = AgentProfileEditLog.objects.filter(
            agent_id=id,
            edited_by='admin',
            step__isnull=True,
            status_after='active'
        ).order_by('-created_at').first()

        last_approved_at = last_approved.created_at if last_approved else None

        # Build query
        query = AgentProfileEditLog.objects.filter(agent_id=id).exclude(edited_by='admin_marker')
        
        # Exclude boundary log entries themselves (empty changes, admin action)
        query = query.filter(
            Q(edited_by='agent') | 
            Q(edited_by='admin', step__isnull=False)
        ).order_by('-created_at')

        if last_approved_at:
            query = query.filter(created_at__gt=last_approved_at)

        logs_data = []
        for log in query:
            changes = []
            if log.changes:
                try:
                    changes = json.loads(log.changes)
                except json.JSONDecodeError:
                    pass

            diff_for_humans = timesince(log.created_at) + " ago" if log.created_at else ""
            created_at_str = log.created_at.strftime('%d %b %Y, %I:%M %p') if log.created_at else ""
            
            logs_data.append({
                'id': log.id,
                'step_label': log.step_label if log.step_label else 'Profile Edit',
                'step': log.step,
                'edited_by': log.edited_by,
                'changes': changes,
                'status_before': log.status_before,
                'status_after': log.status_after,
                'ip_address': log.ip_address,
                'created_at': created_at_str,
                'diff_for_humans': diff_for_humans,
            })

        return JsonResponse({'success': True, 'logs': logs_data})

    except Exception as e:
        logger.error(f"Error getting edit logs json: {e}")
        return JsonResponse({'success': False, 'message': str(e)})


def _build_queue_query(status_filter, search, plan_filter, city_filter, event_filter, sort_by):
    query = '''
        SELECT
            a.id, a.fullname, a.email, a.mobile, a.status,
            a.created_at, a.updated_at, a.badge, a.registration_step,
            ap.address, ap.display_name, ap.profile_photo_path,
            s.selected_plan, s.expires_at,
            (SELECT AVG(rating) FROM agent_reviews WHERE agent_id = a.id AND is_approved = 1) as avg_rating,
            (SELECT COUNT(*) FROM agent_reviews WHERE agent_id = a.id AND is_approved = 1) as review_count,
            TIMESTAMPDIFF(HOUR, a.created_at, UTC_TIMESTAMP()) as hours_waiting
        FROM agents as a
        LEFT JOIN agent_profiles as ap ON a.id = ap.agent_id
        LEFT JOIN agent_subscriptions as s ON a.id = s.agent_id
            AND s.id = (SELECT MAX(id) FROM agent_subscriptions WHERE agent_id = a.id)
        WHERE 1=1
    '''
    params = []

    if isinstance(status_filter, list):
        query += " AND a.status IN (" + ",".join(["%s"] * len(status_filter)) + ")"
        params.extend(status_filter)
    else:
        query += " AND a.status = %s"
        params.append(status_filter)

    if search:
        query += " AND (a.fullname LIKE %s OR a.email LIKE %s OR ap.display_name LIKE %s)"
        search_param = f"%{search}%"
        params.extend([search_param, search_param, search_param])

    if plan_filter and plan_filter != 'All Plans':
        query += " AND s.selected_plan = %s"
        params.append(plan_filter)

    if city_filter:
        query += " AND ap.address LIKE %s"
        params.append(f"%{city_filter}%")

    if event_filter and event_filter != 'All Events':
        query += " AND a.event_id = %s"
        params.append(event_filter)

    if sort_by == 'oldest':
        query += " ORDER BY a.created_at ASC"
    elif sort_by == 'waiting':
        query += " ORDER BY TIMESTAMPDIFF(HOUR, a.created_at, NOW()) DESC"
    else:
        query += " ORDER BY a.created_at DESC"

    return query, params

def _get_events_list():
    events = []
    try:
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute("SELECT id, name FROM events ORDER BY event_date DESC")
            columns = [col[0] for col in cursor.description]
            events = [dict(zip(columns, row)) for row in cursor.fetchall()]
    except Exception:
        pass
    return events




def agent_approvals(request):
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return redirect('admin_login')

    search = request.GET.get('search', '')
    plan_filter = request.GET.get('plan', 'All Plans')
    sort_by = request.GET.get('sort', 'newest')
    city_filter = request.GET.get('city', '')
    event_filter = request.GET.get('event_id', 'All Events')

    query, params = _build_queue_query('pending_approval', search, plan_filter, city_filter, event_filter, sort_by)

    agents = []
    total_pending = 0
    urgent_count = 0
    total_wait_hours = 0

    try:
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute(query, params)
            columns = [col[0] for col in cursor.description]
            agents = [dict(zip(columns, row)) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Error fetching approvals list: {e}")

    for agent in agents:
        total_pending += 1
        hours_waiting = agent.get('hours_waiting') or 0
        total_wait_hours += hours_waiting
        if hours_waiting > 48:
            urgent_count += 1

    avg_wait_hours = (total_wait_hours / total_pending) if total_pending > 0 else 0

    missing_irdai_agents = []
    try:
        missing_query = """
            SELECT a.id, a.fullname, a.email, a.mobile, a.badge, ap.pan_number, ap.license_number
            FROM agents as a
            LEFT JOIN agent_profiles as ap ON a.id = ap.agent_id
            WHERE a.status = 'active'
              AND (ap.license_number IS NULL OR ap.license_number = '')
            ORDER BY a.id DESC
        """
        with connection.cursor() as cursor:
            cursor.execute(missing_query)
            columns = [col[0] for col in cursor.description]
            missing_irdai_agents = [dict(zip(columns, row)) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Error fetching missing IRDAI agents: {e}")

    for agent in missing_irdai_agents:
        badge_str = agent.get('badge') or ''
        agent['badges'] = [b for b in badge_str.split(',') if b]
        agent['initials'] = agent['fullname'][0].upper() if agent['fullname'] else 'A'

    context = {
        'agents': agents,
        'search': search,
        'plan_filter': plan_filter,
        'city_filter': city_filter,
        'event_filter': event_filter,
        'sort_by': sort_by,
        'events': _get_events_list(),
        'totalPending': total_pending,
        'urgentCount': urgent_count,
        'avgWaitHours': avg_wait_hours,
        'missingIrdaiAgents': missing_irdai_agents,
    }

    return render(request, 'admin/agents/approvals.html', context)


def agent_pending_registrations(request):
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return redirect('admin_login')

    search = request.GET.get('search', '')
    plan_filter = request.GET.get('plan', 'All Plans')
    sort_by = request.GET.get('sort', 'newest')
    city_filter = request.GET.get('city', '')
    event_filter = request.GET.get('event_id', 'All Events')

    query, params = _build_queue_query(['incomplete', 'pending_payment'], search, plan_filter, city_filter, event_filter, sort_by)

    agents = []
    total_pending = 0
    urgent_count = 0
    total_wait_hours = 0

    try:
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute(query, params)
            columns = [col[0] for col in cursor.description]
            agents = [dict(zip(columns, row)) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Error fetching pending registrations list: {e}")

    for agent in agents:
        total_pending += 1
        hours_waiting = agent.get('hours_waiting') or 0
        total_wait_hours += hours_waiting
        if hours_waiting > 48:
            urgent_count += 1

    avg_wait_hours = (total_wait_hours / total_pending) if total_pending > 0 else 0

    context = {
        'agents': agents,
        'search': search,
        'plan_filter': plan_filter,
        'city_filter': city_filter,
        'event_filter': event_filter,
        'sort_by': sort_by,
        'events': _get_events_list(),
        'totalPending': total_pending,
        'urgentCount': urgent_count,
        'avgWaitHours': avg_wait_hours,
    }

    return render(request, 'admin/agents/pending_registrations.html', context)
