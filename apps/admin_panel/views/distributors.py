import logging
from django.db import connection
from django.shortcuts import render, redirect
from django.core.paginator import Paginator
from django.contrib import messages
import re
import random
import string
import json
from django.contrib.auth.hashers import make_password
from django.utils import timezone
from django.http import JsonResponse, Http404

from .dashboard import _get_admin_from_session

logger = logging.getLogger(__name__)

def _build_distributor_list_query(search, status_filter):
    """
    Builds the raw SQL query and params for the distributor list based on Laravel logic.
    """
    query = """
        SELECT
            u.id, u.fullname, u.email, u.status, u.created_at,
            (SELECT COUNT(*) FROM agents WHERE distributor_id = u.id) AS agents_count
        FROM users AS u
        WHERE u.role = 'distributor'
    """
    params = []

    if search:
        query += " AND (u.fullname LIKE %s OR u.email LIKE %s)"
        search_param = f"%{search}%"
        params.extend([search_param, search_param])

    if status_filter and status_filter != 'all':
        query += " AND u.status = %s"
        params.append(status_filter)

    query += " ORDER BY u.created_at DESC"
    
    return query, params

def distributor_list(request):
    """
    Phase 6B.1: Distributors List View
    """
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return redirect('admin_login')

    search = request.GET.get('search', '')
    status_filter = request.GET.get('status', 'all')

    query, params = _build_distributor_list_query(search, status_filter)
    
    distributors = []
    try:
        with connection.cursor() as cursor:
            cursor.execute(query, params)
            columns = [col[0] for col in cursor.description]
            distributors = [dict(zip(columns, row)) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Error fetching distributors list: {e}")

    paginator = Paginator(distributors, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'search': search,
        'status_filter': status_filter,
    }
    
    return render(request, 'admin/distributors/list.html', context)


def distributor_create(request):
    """
    Phase 6B.2: Distributors Create View
    """
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return redirect('admin_login')
        
    return render(request, 'admin/distributors/create.html')


def _generate_referral_code(fullname):
    # Take first 4 alphanumeric characters from fullname
    base = re.sub(r'[^A-Z0-9]', '', str(fullname).upper())[:4]
    
    # If less than 2 characters use prefix DIST
    if len(base) < 2:
        base = 'DIST'
        
    # Append 4 random uppercase alphanumeric characters
    # Retry if code already exists
    while True:
        random_chars = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
        code = f"{base}{random_chars}"
        
        # Check if exists
        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM referral_codes WHERE code = %s", [code])
            if not cursor.fetchone():
                return code


def distributor_store(request):
    """
    Phase 6B.2: Store Distributor
    """
    if request.method != 'POST':
        return redirect('admin_distributors_create')
        
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return redirect('admin_login')

    fullname = request.POST.get('fullname', '').strip()
    email = request.POST.get('email', '').strip()
    password = request.POST.get('password', '')
    confirm_password = request.POST.get('confirm_password', '')

    errors = {}

    if not fullname:
        errors['fullname'] = 'The fullname field is required.'
    
    if not email:
        errors['email'] = 'The email field is required.'
    else:
        # Check uniqueness
        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM users WHERE email = %s", [email])
            if cursor.fetchone():
                errors['email'] = 'The email has already been taken.'

    if not password:
        errors['password'] = 'The password field is required.'
    elif len(password) < 8:
        errors['password'] = 'The password must be at least 8 characters.'
        
    if password and password != confirm_password:
        errors['confirm_password'] = 'The password confirmation does not match.'

    if errors:
        for field, msg in errors.items():
            messages.error(request, msg)
        return render(request, 'admin/distributors/create.html', {
            'old': {
                'fullname': fullname,
                'email': email,
            },
            'errors': errors
        })

    # Success: Save User
    hashed_password = make_password(password)
    now = timezone.now()

    try:
        with connection.cursor() as cursor:
            # Insert User
            cursor.execute("""
                INSERT INTO users (fullname, email, password, role, status, created_at, updated_at)
                VALUES (%s, %s, %s, 'distributor', 'active', %s, %s)
            """, [fullname, email, hashed_password, now, now])
            
            distributor_id = cursor.lastrowid
            
            # Generate and Insert Referral Code
            ref_code = _generate_referral_code(fullname)
            cursor.execute("""
                INSERT INTO referral_codes (distributor_id, code, is_active, created_at, updated_at, clicks, total_referrals, pending_referrals, reward_claimed)
                VALUES (%s, %s, 1, %s, %s, 0, 0, 0, 0)
            """, [distributor_id, ref_code, now, now])
            
        messages.success(request, 'Distributor created successfully.')
        return redirect('admin_distributors')
        
    except Exception as e:
        logger.error(f"Error creating distributor: {e}")
        messages.error(request, 'Database error occurred while creating distributor.')
        return render(request, 'admin/distributors/create.html', {
            'old': {
                'fullname': fullname,
                'email': email,
            }
        })


def distributor_detail(request, distributor_id):
    """
    Phase 6B.3: Distributor Detail View
    """
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return redirect('admin_login')

    distributor = None
    query_distributor = """
        SELECT
            u.id, u.fullname, u.email, u.status, u.created_at,
            (SELECT COUNT(*) FROM agents WHERE distributor_id = u.id) AS agents_count
        FROM users AS u
        WHERE u.role = 'distributor' AND u.id = %s
    """
    
    referral_code = None
    query_referral = """
        SELECT code FROM referral_codes WHERE distributor_id = %s LIMIT 1
    """

    agents = []
    query_agents = """
        SELECT
            a.id, a.fullname, a.email, a.status, a.created_at,
            s.selected_plan
        FROM agents AS a
        LEFT JOIN agent_subscriptions AS s ON a.id = s.agent_id
            AND s.id = (SELECT MAX(id) FROM agent_subscriptions WHERE agent_id = a.id)
        WHERE a.distributor_id = %s
        ORDER BY a.created_at DESC
    """

    try:
        with connection.cursor() as cursor:
            # Fetch distributor
            cursor.execute(query_distributor, [distributor_id])
            row = cursor.fetchone()
            if not row:
                from django.http import Http404
                raise Http404("Distributor not found")
            
            columns = [col[0] for col in cursor.description]
            distributor = dict(zip(columns, row))
            
            # Fetch referral code
            cursor.execute(query_referral, [distributor_id])
            ref_row = cursor.fetchone()
            if ref_row:
                referral_code = ref_row[0]
                
            # Fetch agents
            cursor.execute(query_agents, [distributor_id])
            agent_columns = [col[0] for col in cursor.description]
            agents = [dict(zip(agent_columns, r)) for r in cursor.fetchall()]
            
    except Exception as e:
        logger.error(f"Error fetching distributor details: {e}")
        from django.http import Http404
        raise Http404("Database error")

    # Pagination
    paginator = Paginator(agents, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Generate registration link
    registration_link = ""
    if referral_code:
        base_url = f"{request.scheme}://{request.get_host()}"
        registration_link = f"{base_url}/register?refCode={referral_code}"

    context = {
        'distributor': distributor,
        'referral_code': referral_code,
        'registration_link': registration_link,
        'page_obj': page_obj,
    }
    
    return render(request, 'admin/distributors/show.html', context)


def toggle_distributor_status(request):
    """
    Phase 6B.4: Toggle Distributor Status
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request method.'}, status=405)
        
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return JsonResponse({'success': False, 'message': 'Unauthorized.'}, status=401)
        
    try:
        data = json.loads(request.body)
        distributor_id = data.get('id')
        target_status = data.get('status')
        
        if not distributor_id or target_status not in ['active', 'suspended']:
            return JsonResponse({'success': False, 'message': 'Invalid input data.'}, status=400)
            
        with connection.cursor() as cursor:
            # Check if user exists and is a distributor
            cursor.execute("SELECT id FROM users WHERE id = %s AND role = 'distributor'", [distributor_id])
            if not cursor.fetchone():
                return JsonResponse({'success': False, 'message': 'Distributor not found.'}, status=404)
                
            # Update status
            cursor.execute("UPDATE users SET status = %s WHERE id = %s AND role = 'distributor'", [target_status, distributor_id])
            
        return JsonResponse({
            'success': True,
            'message': 'Distributor status updated successfully',
            'status': target_status
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': 'Invalid JSON data.'}, status=400)
    except Exception as e:
        logger.error(f"Error toggling distributor status: {e}")
        return JsonResponse({'success': False, 'message': 'Database error occurred.'}, status=500)

