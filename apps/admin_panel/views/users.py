import math
from django.shortcuts import render
from django.db import connection
from .dashboard import _get_admin_from_session

def _build_user_list_query(request):
    """
    Builds the base query, arguments, and total count for users list.
    """
    search = request.GET.get('search', '').strip()
    role = request.GET.get('role', '').strip()
    status = request.GET.get('status', '').strip()
    
    # Base query matches Laravel User::query() which does SELECT * FROM users
    base_query = "FROM users WHERE 1=1"
    args = []
    
    if search:
        # Match Laravel: where(function($q) use ($search) { $q->where('fullname', 'LIKE', "%{$search}%")->orWhere('email', 'LIKE', "%{$search}%"); })
        base_query += " AND (fullname LIKE %s OR email LIKE %s)"
        search_term = f"%{search}%"
        args.extend([search_term, search_term])
        
    if role and role != 'all':
        base_query += " AND role = %s"
        args.append(role)
        
    if status and status != 'all':
        base_query += " AND status = %s"
        args.append(status)
        
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT COUNT(id) {base_query}", args)
        total_row = cursor.fetchone()
        total = total_row[0] if total_row else 0
        
    return base_query, args, total

def user_list(request):
    """
    Phase 6C.1: Users / Clients list page.
    """
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return render(request, 'admin/login.html', {'error': 'Please login first'})
        
    base_query, args, total = _build_user_list_query(request)
    
    # Pagination
    try:
        page = int(request.GET.get('page', 1))
        if page < 1:
            page = 1
    except ValueError:
        page = 1
        
    per_page = 15
    total_pages = math.ceil(total / per_page) if total > 0 else 1
    if page > total_pages:
        page = total_pages
        
    offset = (page - 1) * per_page
    
    # Ordering matching Laravel: orderBy('created_at', 'desc')
    query = f"SELECT * {base_query} ORDER BY created_at DESC LIMIT %s OFFSET %s"
    
    with connection.cursor() as cursor:
        cursor.execute(query, args + [per_page, offset])
        columns = [col[0] for col in cursor.description]
        users = [dict(zip(columns, row)) for row in cursor.fetchall()]
        
    context = {
        'users': users,
        'search': request.GET.get('search', ''),
        'page': page,
        'total_pages': total_pages,
        'total_users': total,
        'page_range': range(1, total_pages + 1)
    }
    
    return render(request, 'admin/users/list.html', context)

def user_edit(request, user_id):
    """
    Phase 6C.2: User edit page
    """
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return redirect('admin_login')
        
    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM users WHERE id = %s", [user_id])
        row = cursor.fetchone()
        if not row:
            messages.error(request, 'User not found')
            return redirect('admin_users')
            
        columns = [col[0] for col in cursor.description]
        user = dict(zip(columns, row))
        
        agent_id = 0
        if user['role'] == 'agent':
            cursor.execute("SELECT id FROM agents WHERE user_id = %s", [user_id])
            agent_row = cursor.fetchone()
            if agent_row:
                agent_id = agent_row[0]
                
    errors = request.session.pop('form_errors', {})
    old = request.session.pop('form_old', {})
    
    context = {
        'user': user,
        'agent_id': agent_id,
        'errors': errors,
        'old': old
    }
    
    return render(request, 'admin/users/edit.html', context)

import re
from django.contrib import messages
from django.contrib.auth.hashers import make_password
from django.shortcuts import redirect

def user_update(request, user_id):
    """
    Phase 6C.2: User update logic
    """
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return redirect('admin_login')
        
    if request.method != 'POST':
        return redirect('admin_users_edit', user_id=user_id)
        
    with connection.cursor() as cursor:
        cursor.execute("SELECT id, email FROM users WHERE id = %s", [user_id])
        user_row = cursor.fetchone()
        
    if not user_row:
        messages.error(request, 'User not found')
        return redirect('admin_users')
        
    fullname = request.POST.get('fullname', '').strip()
    email = request.POST.get('email', '').strip()
    role = request.POST.get('role', '').strip()
    status = request.POST.get('status', '').strip()
    password = request.POST.get('password', '')
    password_confirmation = request.POST.get('password_confirmation', '')
    
    errors = {}
    
    if not fullname:
        errors['fullname'] = "The fullname field is required."
    elif len(fullname) > 255:
        errors['fullname'] = "The fullname must not be greater than 255 characters."
        
    if not email:
        errors['email'] = "The email field is required."
    elif not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        errors['email'] = "The email must be a valid email address."
    else:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM users WHERE email = %s AND id != %s", [email, user_id])
            if cursor.fetchone():
                errors['email'] = "The email has already been taken."
                
    if not role:
        errors['role'] = "The role field is required."
    elif role not in ['admin', 'agent', 'client']:
        errors['role'] = "The selected role is invalid."
        
    if not status:
        errors['status'] = "The status field is required."
    elif status not in ['active', 'inactive', 'suspended']:
        errors['status'] = "The selected status is invalid."
        
    if password:
        if len(password) < 8:
            errors['password'] = "The password must be at least 8 characters."
        elif password != password_confirmation:
            errors['password'] = "The password confirmation does not match."
            
    if errors:
        request.session['form_errors'] = errors
        request.session['form_old'] = request.POST.dict()
        return redirect('admin_users_edit', user_id=user_id)
        
    update_fields = ['fullname = %s', 'email = %s', 'role = %s', 'status = %s']
    update_args = [fullname, email, role, status]
    
    if password:
        update_fields.append('password = %s')
        update_args.append(make_password(password))
        
    update_args.append(user_id)
    query = f"UPDATE users SET {', '.join(update_fields)} WHERE id = %s"
    
    with connection.cursor() as cursor:
        cursor.execute(query, update_args)
        
    messages.success(request, 'User updated successfully')
    return redirect('admin_users')
