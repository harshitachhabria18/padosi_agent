from django.shortcuts import render, redirect
from django.db import connection
from django.http import HttpResponse
import csv
from datetime import datetime
from .dashboard import _get_admin_from_session

def event_list(request):
    admin = _get_admin_from_session(request)
    if not admin:
        return redirect('admin_login')

    events = []
    
    query = """
    SELECT
        e.id,
        e.name,
        e.description,
        e.event_date,
        COUNT(a.id) as total_count,
        SUM(
            CASE
                WHEN a.registration_step = 1
                THEN 1
                ELSE 0
            END
        ) as step1_count,
        SUM(
            CASE
                WHEN a.registration_step = 2
                THEN 1
                ELSE 0
            END
        ) as step2_count,
        SUM(
            CASE
                WHEN a.registration_step = 3
                THEN 1
                ELSE 0
            END
        ) as step3_count
    FROM events e
    LEFT JOIN agents a
        ON e.id = a.event_id
    GROUP BY e.id
    ORDER BY e.event_date DESC
    """
    
    with connection.cursor() as cursor:
        cursor.execute(query)
        columns = [col[0] for col in cursor.description]
        for row in cursor.fetchall():
            events.append(dict(zip(columns, row)))

    context = {
        'admin': admin,
        'events': events,
    }
    return render(request, 'admin/events/list.html', context)


def event_show(request, event_id):
    admin = _get_admin_from_session(request)
    if not admin:
        return redirect('admin_login')

    event = None
    registrants = []
    
    # KPI counters
    total_entries = 0
    step1_drop = 0
    step2_drop = 0
    fully_completed = 0

    with connection.cursor() as cursor:
        # 1. Fetch Event Header
        cursor.execute("SELECT * FROM events WHERE id = %s LIMIT 1", [event_id])
        event_columns = [col[0] for col in cursor.description]
        event_row = cursor.fetchone()
        if not event_row:
            return redirect('admin_events_index')
        event = dict(zip(event_columns, event_row))

        # 2. Fetch Registrants
        registrants_query = """
        SELECT
            a.id,
            a.fullname,
            a.email,
            a.mobile,
            a.agent_pincode AS pincode,
            a.referred_by_code AS promocode,
            a.registration_step AS current_step,
            a.created_at,
            a.status,

            s.selected_plan,
            s.payment_status,
            s.razorpay_order_id,
            s.razorpay_payment_id,

            GROUP_CONCAT(
                DISTINCT iseg.segment_type
            ) AS insurance_segments

        FROM agents a

        LEFT JOIN agent_subscriptions s
            ON a.id = s.agent_id
            AND s.id = (
                SELECT MAX(id)
                FROM agent_subscriptions
                WHERE agent_id = a.id
            )

        LEFT JOIN agent_insurance_segments iseg
            ON a.id = iseg.agent_id

        WHERE a.event_id = %s

        GROUP BY
            a.id,
            s.selected_plan,
            s.payment_status,
            s.razorpay_order_id,
            s.razorpay_payment_id

        ORDER BY a.created_at DESC
        """
        cursor.execute(registrants_query, [event_id])
        reg_columns = [col[0] for col in cursor.description]
        
        for row in cursor.fetchall():
            reg = dict(zip(reg_columns, row))
            
            # Format insurance segments
            if reg['insurance_segments']:
                reg['insurance_segments'] = reg['insurance_segments'].split(',')
            else:
                reg['insurance_segments'] = []
                
            registrants.append(reg)
            
            # Update KPI counters
            total_entries += 1
            step = reg['current_step']
            if step == 1:
                step1_drop += 1
            elif step == 2:
                step2_drop += 1
            elif step == 3:
                fully_completed += 1

    context = {
        'admin': admin,
        'event': event,
        'registrants': registrants,
        'total_entries': total_entries,
        'step1_drop': step1_drop,
        'step2_drop': step2_drop,
        'fully_completed': fully_completed,
    }
    return render(request, 'admin/events/show.html', context)


def get_step_name(step):
    """Helper matching Laravel's getStepName() exactly."""
    if step == 1:
        return 'Form Filled - Dropped at Plan selection'
    elif step == 2:
        return 'Plan Selected - Dropped at Checkout'
    elif step == 3:
        return 'Completed - Registered & Paid'
    return 'Unknown'


def event_export(request, event_id):
    admin = _get_admin_from_session(request)
    if not admin:
        return redirect('admin_login')

    with connection.cursor() as cursor:
        # Fetch event
        cursor.execute("SELECT * FROM events WHERE id = %s LIMIT 1", [event_id])
        event_row = cursor.fetchone()
        if not event_row:
            return redirect('admin_events_index')
            
        event_columns = [col[0] for col in cursor.description]
        event = dict(zip(event_columns, event_row))

        # Fetch registrants (exact same query as show)
        registrants_query = """
        SELECT
            a.id,
            a.fullname,
            a.email,
            a.mobile,
            a.agent_pincode AS pincode,
            a.referred_by_code AS promocode,
            a.registration_step AS current_step,
            a.created_at,
            a.status,

            s.selected_plan,
            s.payment_status,
            s.razorpay_order_id,
            s.razorpay_payment_id,

            GROUP_CONCAT(
                DISTINCT iseg.segment_type
            ) AS insurance_segments

        FROM agents a

        LEFT JOIN agent_subscriptions s
            ON a.id = s.agent_id
            AND s.id = (
                SELECT MAX(id)
                FROM agent_subscriptions
                WHERE agent_id = a.id
            )

        LEFT JOIN agent_insurance_segments iseg
            ON a.id = iseg.agent_id

        WHERE a.event_id = %s

        GROUP BY
            a.id,
            s.selected_plan,
            s.payment_status,
            s.razorpay_order_id,
            s.razorpay_payment_id

        ORDER BY a.created_at DESC
        """
        cursor.execute(registrants_query, [event_id])
        reg_columns = [col[0] for col in cursor.description]
        registrants = [dict(zip(reg_columns, row)) for row in cursor.fetchall()]

    # Generate CSV response
    event_name_clean = str(event['name']).lower().replace(' ', '_')
    date_str = datetime.now().strftime('%Y-%m-%d')
    filename = f"event_{event_name_clean}_registrations_{date_str}.csv"

    response = HttpResponse(content_type='text/csv; charset=UTF-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    response['Pragma'] = 'no-cache'
    response['Cache-Control'] = 'must-revalidate, post-check=0, pre-check=0'
    response['Expires'] = '0'

    # Write UTF-8 BOM
    response.write(b'\xEF\xBB\xBF')

    writer = csv.writer(response)
    
    # Exact Laravel headers
    writer.writerow([
        'Registration ID', 'Full Name', 'Email Address', 'Mobile Number', 
        'Insurance Segments', 'Pin Code', 'Promo Code', 'Current Step', 
        'Selected Plan', 'Registration Status', 'Payment Status', 
        'Razorpay Order ID', 'Razorpay Payment ID', 'Date Registered'
    ])

    for r in registrants:
        segments = r['insurance_segments'].replace(',', ', ') if r['insurance_segments'] else ''
        pincode = r['pincode'] if r['pincode'] else 'N/A'
        promo = r['promocode'] if r['promocode'] else 'N/A'
        
        step_val = r['current_step']
        step_str = f"{step_val}/3 ({get_step_name(step_val)})"
        
        plan = str(r['selected_plan']).capitalize() if r['selected_plan'] else 'None'
        reg_status = str(r['status']).capitalize() if r['status'] else ''
        pay_status = str(r['payment_status']).capitalize() if r['payment_status'] else 'Pending'
        
        razor_order = r['razorpay_order_id'] if r['razorpay_order_id'] else 'N/A'
        razor_pay = r['razorpay_payment_id'] if r['razorpay_payment_id'] else 'N/A'
        
        # Django created_at format
        date_reg = r['created_at'].strftime('%Y-%m-%d %H:%M:%S') if r['created_at'] else ''

        writer.writerow([
            r['id'],
            r['fullname'],
            r['email'],
            r['mobile'],
            segments,
            pincode,
            promo,
            step_str,
            plan,
            reg_status,
            pay_status,
            razor_order,
            razor_pay,
            date_reg
        ])

    return response

