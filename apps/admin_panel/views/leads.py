from django.shortcuts import render, redirect
from django.db import connection
from django.http import JsonResponse
import math
from .dashboard import _get_admin_from_session

def lead_list(request):
    admin = _get_admin_from_session(request)
    if not admin:
        return redirect('admin_login')

    search = request.GET.get('search', '')
    type_filter = request.GET.get('type', 'all')
    status_filter = request.GET.get('status', 'all')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    
    try:
        page = int(request.GET.get('page', 1))
    except ValueError:
        page = 1
    
    where_clauses = []
    params = []

    if search:
        where_clauses.append("(l.customer_name LIKE %s OR l.customer_email LIKE %s OR l.customer_mobile LIKE %s OR a.fullname LIKE %s)")
        search_term = f"%{search}%"
        params.extend([search_term, search_term, search_term, search_term])
        
    if type_filter != 'all':
        where_clauses.append("l.interaction_type = %s")
        params.append(type_filter)
        
    if status_filter != 'all':
        where_clauses.append("l.lead_status = %s")
        params.append(status_filter)
        
    if date_from:
        where_clauses.append("DATE(l.created_at) >= %s")
        params.append(date_from)
        
    if date_to:
        where_clauses.append("DATE(l.created_at) <= %s")
        params.append(date_to)

    where_sql = ""
    if where_clauses:
        where_sql = "WHERE " + " AND ".join(where_clauses)
        
    with connection.cursor() as cursor:
        # Get Stats
        cursor.execute("SELECT COUNT(*) FROM agent_leads")
        total = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM agent_leads WHERE DATE(created_at) = CURDATE()")
        today = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM agent_leads WHERE interaction_type = 'whatsapp'")
        whatsapp = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM agent_leads WHERE interaction_type = 'call'")
        call_leads = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM agent_leads WHERE lead_status = 'new'")
        new_leads = cursor.fetchone()[0]
        
        stats = {
            'total': total,
            'today': today,
            'whatsapp': whatsapp,
            'call': call_leads,
            'new': new_leads,
        }
        
        # Count total rows for pagination
        count_query = f"""
            SELECT COUNT(*) 
            FROM agent_leads l
            LEFT JOIN agents a ON l.agent_id = a.id
            LEFT JOIN agent_profiles ap ON a.id = ap.agent_id
            {where_sql}
        """
        cursor.execute(count_query, params)
        total_rows = cursor.fetchone()[0]
        
        # Pagination calculations
        per_page = 20
        total_pages = max(1, math.ceil(total_rows / per_page))
        if page < 1:
            page = 1
        elif page > total_pages:
            page = total_pages
            
        offset = (page - 1) * per_page
        
        # Calculate pagination range (start_row to end_row)
        start_row = offset + 1 if total_rows > 0 else 0
        end_row = min(offset + per_page, total_rows)
        
        # Calculate visible pages (similar to Laravel's paginator)
        window = 2
        visible_pages = []
        for i in range(1, total_pages + 1):
            if i == 1 or i == total_pages or abs(page - i) <= window:
                visible_pages.append(i)
        
        # Add ellipses
        final_pages = []
        last_page = 0
        for p in visible_pages:
            if last_page and p - last_page > 1:
                final_pages.append('...')
            final_pages.append(p)
            last_page = p
            
        # Get rows
        query = f"""
            SELECT 
                l.*,
                a.fullname as agent_name,
                a.mobile as agent_mobile,
                ap.display_name as agent_display_name
            FROM agent_leads l
            LEFT JOIN agents a ON l.agent_id = a.id
            LEFT JOIN agent_profiles ap ON a.id = ap.agent_id
            {where_sql}
            ORDER BY l.created_at DESC
            LIMIT %s OFFSET %s
        """
        cursor.execute(query, params + [per_page, offset])
        columns = [col[0] for col in cursor.description]
        leads = [dict(zip(columns, row)) for row in cursor.fetchall()]
        
    context = {
        'admin': admin,
        'leads': leads,
        'stats': stats,
        'search': search,
        'typeFilter': type_filter,
        'statusFilter': status_filter,
        'dateFrom': date_from,
        'dateTo': date_to,
        
        'page': page,
        'total_pages': total_pages,
        'total_rows': total_rows,
        'start_row': start_row,
        'end_row': end_row,
        'has_previous': page > 1,
        'has_next': page < total_pages,
        'previous_page': page - 1,
        'next_page': page + 1,
        'visible_pages': final_pages,
    }
    
    return render(request, 'admin/leads/list.html', context)


def update_lead_status(request):
    if request.method != 'POST':
        return JsonResponse({'success': False}, status=400)
        
    admin = _get_admin_from_session(request)
    if not admin:
        return JsonResponse({'success': False, 'message': 'Unauthorized'}, status=401)
        
    lead_id = request.POST.get('id')
    status = request.POST.get('status')
    
    if status not in ['new', 'contacted', 'converted', 'closed']:
        return JsonResponse({'success': False, 'message': 'Invalid status'}, status=400)
        
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE agent_leads SET lead_status = %s, updated_at = NOW() WHERE id = %s",
                [status, lead_id]
            )
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)
