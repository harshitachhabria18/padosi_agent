"""
apps/admin_panel/views/export.py

Export Center — PHASE EXPORT_CENTER.MERGE
Source: django/padosi_agent/apps/admin_panel/views/export.py

Adaptations from source:
  - Removed @admin_login_required decorator (absent in target); replaced with
    manual _get_admin_from_session() guard matching target project pattern.
  - Replaced source model imports (apps.agents.models) with target equivalents
    (apps.admin_panel.models) which expose the same managed=False tables.
  - All SQL queries, CSV structure, and business logic are preserved identically.
"""

import csv

from django.db import connection
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils.timezone import now

from apps.admin_panel.views.dashboard import _get_admin_from_session
from apps.admin_panel.models import Agent, AgentSubscription, AgentReview
from apps.admin_panel.models.contact_submission import ContactSubmission


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _csv_response(filename: str, header: list, rows: list) -> HttpResponse:
    """
    Build a CSV download response.
    Uses HttpResponse directly as the file-like object for csv.writer,
    mirroring PHP's fopen('php://output','w') + fputcsv() pattern.
    """
    response = HttpResponse(content_type='text/csv; charset=UTF-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    response['Pragma'] = 'no-cache'
    response['Cache-Control'] = 'must-revalidate, post-check=0, pre-check=0'
    response['Expires'] = '0'
    # Write UTF-8 BOM so Excel opens without encoding issues
    response.write(b'\xef\xbb\xbf')
    writer = csv.writer(response)
    writer.writerow(header)   # header row
    writer.writerows(rows)    # all data rows
    return response


def _today() -> str:
    return now().strftime('%Y-%m-%d')


# ─── Index ───────────────────────────────────────────────────────────────────

def index(request):
    """Export Center landing page – mirrors AdminExportController::index."""
    admin = _get_admin_from_session(request)
    if not admin:
        return redirect('admin_login_page')

    counts = {
        'agents':        Agent.objects.count(),
        'leads':         _count_table('agent_leads'),
        'contacts':      ContactSubmission.objects.count(),
        'subscriptions': AgentSubscription.objects.count(),
        'reviews':       AgentReview.objects.count(),
    }
    return render(request, 'admin/export_center.html', {'counts': counts})


def _count_table(table: str) -> int:
    """Count rows in a raw table that may not have a Django model."""
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        return cursor.fetchone()[0]


# ─── Agents CSV ──────────────────────────────────────────────────────────────

def export_agents(request):
    """Export agents with profile + subscription info as CSV."""
    admin = _get_admin_from_session(request)
    if not admin:
        return redirect('admin_login_page')

    status_filter = request.GET.get('status', 'all')
    if status_filter == 'All Status':
        status_filter = 'all'

    with connection.cursor() as cursor:
        base_sql = """
            SELECT
                a.id, a.fullname, ap.display_name, a.email, a.mobile, a.status,
                ap.agency_name, ap.address, a.user_types, a.experience_range,
                s.selected_plan, s.expires_at, a.created_at
            FROM agents a
            LEFT JOIN agent_profiles ap ON a.id = ap.agent_id
            LEFT JOIN agent_subscriptions s ON a.id = s.agent_id
        """
        params = []
        if status_filter != 'all':
            base_sql += ' WHERE a.status = %s'
            params.append(status_filter)
        base_sql += ' ORDER BY a.created_at DESC'
        cursor.execute(base_sql, params)
        rows_raw = cursor.fetchall()

    header = [
        'ID', 'Full Name', 'Display Name', 'Email', 'Mobile', 'Status',
        'Agency', 'Address', 'User Types', 'Experience', 'Plan', 'Plan Expires', 'Joined',
    ]
    rows = [
        [
            r[0], r[1] or '', r[2] or '', r[3] or '', r[4] or '',
            r[5] or '', r[6] or '', r[7] or '', r[8] or '', r[9] or '',
            r[10] or '', str(r[11]) if r[11] else '', str(r[12]) if r[12] else '',
        ]
        for r in rows_raw
    ]
    return _csv_response(f'agents_{status_filter}_{_today()}.csv', header, rows)


# ─── Leads CSV ───────────────────────────────────────────────────────────────

def export_leads(request):
    """Export agent leads as CSV.
    Real agent_leads columns: customer_name, customer_email, customer_mobile,
    customer_pincode, interaction_type, lead_status, service_type,
    insurance_type, insurance_company, enquiry_requirements, source_page.
    """
    admin = _get_admin_from_session(request)
    if not admin:
        return redirect('admin_login_page')

    type_filter = request.GET.get('type', 'all')

    with connection.cursor() as cursor:
        base_sql = """
            SELECT
                l.id, a.fullname, a.email,
                l.interaction_type,
                l.customer_name, l.customer_mobile,
                l.customer_email, l.customer_pincode,
                l.service_type, l.insurance_type,
                l.lead_status, l.created_at
            FROM agent_leads l
            LEFT JOIN agents a ON l.agent_id = a.id
        """
        params = []
        if type_filter != 'all':
            base_sql += ' WHERE l.interaction_type = %s'
            params.append(type_filter)
        base_sql += ' ORDER BY l.created_at DESC'
        cursor.execute(base_sql, params)
        rows_raw = cursor.fetchall()

    header = [
        'ID', 'Agent Name', 'Agent Email',
        'Lead Type',
        'Customer Name', 'Customer Mobile',
        'Customer Email', 'Customer Pincode',
        'Service Type', 'Insurance Type',
        'Status', 'Date',
    ]
    rows = [
        [
            r[0], r[1] or '', r[2] or '',
            r[3] or '',
            r[4] or '', r[5] or '',
            r[6] or '', r[7] or '',
            r[8] or '', r[9] or '',
            r[10] or '', str(r[11]) if r[11] else '',
        ]
        for r in rows_raw
    ]
    return _csv_response(f'leads_{type_filter}_{_today()}.csv', header, rows)


# ─── Contacts CSV ────────────────────────────────────────────────────────────

def export_contacts(request):
    """Export contact submissions as CSV."""
    admin = _get_admin_from_session(request)
    if not admin:
        return redirect('admin_login_page')

    qs = ContactSubmission.objects.order_by('-created_at')
    header = ['ID', 'Name', 'Email', 'Phone', 'Subject', 'Message', 'Status', 'Date']
    rows = [
        [
            r.id, r.name or '', r.email or '',
            r.mobile or '',
            r.subject or '', r.message or '', r.status or '',
            str(r.created_at) if r.created_at else '',
        ]
        for r in qs
    ]
    return _csv_response(f'contacts_{_today()}.csv', header, rows)


# ─── Subscriptions CSV ───────────────────────────────────────────────────────

def export_subscriptions(request):
    """Export subscription history as CSV."""
    admin = _get_admin_from_session(request)
    if not admin:
        return redirect('admin_login_page')

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT
                s.id, a.fullname, a.email,
                s.selected_plan, s.registration_amount, s.payment_status,
                s.starts_at, s.expires_at, s.created_at
            FROM agent_subscriptions s
            JOIN agents a ON s.agent_id = a.id
            ORDER BY s.created_at DESC
        """)
        rows_raw = cursor.fetchall()

    header = [
        'ID', 'Agent Name', 'Agent Email', 'Plan',
        'Amount (Rs.)', 'Payment Status', 'Starts At', 'Expires At', 'Created At',
    ]
    rows = [
        [
            r[0], r[1] or '', r[2] or '',
            r[3] or '', r[4] or '', r[5] or '',
            str(r[6]) if r[6] else '', str(r[7]) if r[7] else '', str(r[8]) if r[8] else '',
        ]
        for r in rows_raw
    ]
    return _csv_response(f'subscriptions_{_today()}.csv', header, rows)


# ─── Reviews CSV ─────────────────────────────────────────────────────────────

def export_reviews(request):
    """Export agent reviews as CSV."""
    admin = _get_admin_from_session(request)
    if not admin:
        return redirect('admin_login_page')

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT
                r.id, a.fullname AS agent_name,
                r.reviewer_name, r.rating, r.review,
                r.is_approved, r.created_at
            FROM agent_reviews r
            LEFT JOIN agents a ON r.agent_id = a.id
            ORDER BY r.created_at DESC
        """)
        rows_raw = cursor.fetchall()

    header = ['ID', 'Agent', 'Reviewer Name', 'Rating', 'Review', 'Approved', 'Date']
    rows = [
        [
            r[0], r[1] or '', r[2] or '',
            r[3] or '', r[4] or '',
            'Yes' if r[5] else 'No',
            str(r[6]) if r[6] else '',
        ]
        for r in rows_raw
    ]
    return _csv_response(f'reviews_{_today()}.csv', header, rows)


# ─── Pending Registrations CSV ───────────────────────────────────────────────

def export_pending(request):
    """Export incomplete/pending agents as CSV."""
    admin = _get_admin_from_session(request)
    if not admin:
        return redirect('admin_login_page')

    search = request.GET.get('search', '')
    event_filter = request.GET.get('event_id', 'All Events')

    with connection.cursor() as cursor:
        base_sql = """
            SELECT
                a.id, a.fullname, ap.display_name, a.email, a.mobile,
                a.status, a.registration_step,
                s.selected_plan, s.registration_amount, s.payment_status,
                ap.address,
                TIMESTAMPDIFF(HOUR, a.created_at, UTC_TIMESTAMP()) AS hours_waiting,
                a.created_at
            FROM agents a
            LEFT JOIN agent_profiles ap ON a.id = ap.agent_id
            LEFT JOIN agent_subscriptions s ON a.id = s.agent_id
                AND s.id = (SELECT MAX(id) FROM agent_subscriptions WHERE agent_id = a.id)
            WHERE a.status IN ('incomplete', 'pending_payment')
        """
        params = []
        
        if search:
            base_sql += " AND (a.fullname LIKE %s OR a.email LIKE %s OR ap.display_name LIKE %s)"
            search_param = f"%{search}%"
            params.extend([search_param, search_param, search_param])
            
        if event_filter and event_filter != 'All Events':
            base_sql += " AND a.event_id = %s"
            params.append(event_filter)

        base_sql += " ORDER BY TIMESTAMPDIFF(HOUR, a.created_at, UTC_TIMESTAMP()) DESC"

        cursor.execute(base_sql, params)
        rows_raw = cursor.fetchall()

    header = [
        'ID', 'Full Name', 'Display Name', 'Email', 'Mobile', 'Status', 'Reg. Step',
        'Selected Plan', 'Amount (Rs.)', 'Payment Status', 'Location', 'Waiting (Hours)', 'Registered At',
    ]
    rows = [
        [
            r[0], r[1] or '', r[2] or '', r[3] or '', r[4] or '',
            r[5] or '', r[6] or '',
            r[7] or 'Not Selected', r[8] or '0', r[9] or '',
            r[10] or '', r[11] or 0,
            str(r[12]) if r[12] else '',
        ]
        for r in rows_raw
    ]
    return _csv_response(f'pending_registrations_{_today()}.csv', header, rows)
