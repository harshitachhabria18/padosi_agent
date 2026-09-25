from django.core.paginator import Paginator
from django.shortcuts import render, redirect
from django.http import HttpResponse, Http404, FileResponse, JsonResponse
from django.db import connection
from django.views.decorators.http import require_http_methods
from django.contrib import messages
import os
from django.core.mail import EmailMessage
from django.conf import settings
from apps.agents.models import Agent, Invoice, PromoCode
from apps.agents.services.invoice import generate_invoice_number, get_pdf_absolute_path, get_logo_data_uri, InvoiceService

from .dashboard import _get_admin_from_session
from ..services.google_sheet_sync import sync_all_pending

def get_folder_label(folder):
    labels = {
        'no_discount': 'No Discount',
        '10_percent': '10%',
        '25_percent': '25%',
        '50_percent': '50%',
        '1re': '₹1 (Special)',
    }
    return labels.get(folder, 'Others')

@require_http_methods(["GET"])
def invoice_list(request):
    admin = _get_admin_from_session(request)
    if not admin:
        return redirect("admin_login_page")

    folder = request.GET.get("folder", "all")
    search = request.GET.get("search", "")
    page = int(request.GET.get("page", 1))
    per_page = 25

    with connection.cursor() as cursor:
        # 1. Total KPIs
        cursor.execute("SELECT COUNT(*), COALESCE(SUM(total_amount), 0) FROM invoices")
        row = cursor.fetchone()
        total_count = row[0] if row else 0
        total_revenue = row[1] if row else 0

        # 2. Folder Aggregations
        cursor.execute("""
            SELECT discount_folder, COUNT(*), COALESCE(SUM(total_amount), 0)
            FROM invoices
            GROUP BY discount_folder
        """)
        folder_rows = cursor.fetchall()
        
        # Initialize default counts
        folder_counts = {
            'all': {'total': total_count, 'revenue': total_revenue},
            'no_discount': {'total': 0, 'revenue': 0},
            '10_percent': {'total': 0, 'revenue': 0},
            '25_percent': {'total': 0, 'revenue': 0},
            '50_percent': {'total': 0, 'revenue': 0},
            '1re': {'total': 0, 'revenue': 0},
            'others': {'total': 0, 'revenue': 0},
        }
        
        for f_row in folder_rows:
            f_name, f_count, f_rev = f_row[0], f_row[1], f_row[2]
            if f_name in folder_counts:
                folder_counts[f_name] = {'total': f_count, 'revenue': f_rev}
            else:
                folder_counts['others']['total'] += f_count
                folder_counts['others']['revenue'] += f_rev

        # 3. List Query
        where_clauses = []
        params = []

        valid_folders = ["no_discount", "10_percent", "25_percent", "50_percent", "1re", "others"]
        if folder != "all" and folder in valid_folders:
            where_clauses.append("discount_folder = %s")
            params.append(folder)

        if search:
            search_term = f"%{search}%"
            where_clauses.append("(invoice_number LIKE %s OR agent_name LIKE %s OR agent_email LIKE %s OR razorpay_payment_id LIKE %s)")
            params.extend([search_term, search_term, search_term, search_term])

        where_sql = ""
        if where_clauses:
            where_sql = "WHERE " + " AND ".join(where_clauses)

        # Pagination logic
        count_query = f"SELECT COUNT(*) FROM invoices {where_sql}"
        cursor.execute(count_query, params)
        total_filtered = cursor.fetchone()[0]

        paginator = Paginator(range(total_filtered), per_page)
        page_obj = paginator.get_page(page)
        page_range = paginator.get_elided_page_range(page_obj.number, on_each_side=1, on_ends=1)
        
        offset = (page_obj.number - 1) * per_page

        list_query = f"""
            SELECT id, invoice_number, agent_name, agent_email, plan_name, 
                   total_amount, discount_percent, promo_code, discount_folder, 
                   synced_to_sheet, synced_at, created_at
            FROM invoices
            {where_sql}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """
        list_params = params + [per_page, offset]
        cursor.execute(list_query, list_params)
        
        columns = [col[0] for col in cursor.description]
        invoices = []
        for row in cursor.fetchall():
            inv = dict(zip(columns, row))
            inv['folder_label'] = get_folder_label(inv['discount_folder'])
            invoices.append(inv)
            
        cursor.execute("SELECT value FROM site_settings WHERE `key` = 'invoice_google_sheet_url'")
        row = cursor.fetchone()
        googleSheetUrl = row[0] if row else None

        cursor.execute("SELECT value FROM site_settings WHERE `key` = 'invoice_google_sheet_view_url'")
        row_view = cursor.fetchone()
        googleSheetViewUrl = row_view[0] if row_view else None

        cursor.execute("SELECT COUNT(*) FROM invoices WHERE synced_to_sheet = 0")
        unsynced_invoice_count = cursor.fetchone()[0]

    context = {
        'admin': admin,
        'invoices': invoices,
        'folder': folder,
        'search': search,
        'folder_counts': folder_counts,
        'totalCount': total_count,
        'totalRevenue': total_revenue,
        'total_filtered': total_filtered,
        'googleSheetUrl': googleSheetUrl,
        'googleSheetViewUrl': googleSheetViewUrl,
        'unsynced_invoice_count': unsynced_invoice_count,

        'page_obj': page_obj,
        'page_range': page_range,
        'first_item': page_obj.start_index(),
        'last_item': page_obj.end_index(),
    }

    return render(request, "admin/invoices/index.html", context)


@require_http_methods(["GET"])
def preview_invoice(request, invoice_id):
    admin = _get_admin_from_session(request)
    if not admin:
        return redirect("admin_login_page")
        
    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM invoices WHERE id = %s", [invoice_id])
        if not cursor.description:
            raise Http404("Invoice not found")
        columns = [col[0] for col in cursor.description]
        row = cursor.fetchone()
        
        if not row:
            raise Http404("Invoice not found")
            
        invoice = dict(zip(columns, row))
        
    if not invoice.get('pdf_path'):
        try:
            inv_obj = Invoice.objects.get(id=invoice_id)
            InvoiceService().generate_pdf(inv_obj)
        except Invoice.DoesNotExist:
            pass
        # Re-fetch after generation
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM invoices WHERE id = %s", [invoice_id])
            row = cursor.fetchone()
            invoice = dict(zip(columns, row))

    # Bill-to state fallback to the agent profile state (matches Laravel template)
    if not invoice.get('agent_state') and invoice.get('agent_id'):
        with connection.cursor() as cursor:
            cursor.execute("SELECT state FROM agent_profiles WHERE agent_id = %s LIMIT 1", [invoice['agent_id']])
            prow = cursor.fetchone()
            if prow and prow[0]:
                invoice['agent_state'] = prow[0]

    # GST logic for template preview matching Laravel
    agent_state = invoice.get('agent_state') or ''
    is_igst = 'gujarat' not in agent_state.lower()
    invoice['is_igst'] = is_igst
    
    gst_amount = float(invoice.get('gst_amount') or 0)
    if is_igst:
        invoice['gst_amount_igst'] = gst_amount
    else:
        invoice['gst_amount_cgst'] = gst_amount / 2
        invoice['gst_amount_sgst'] = gst_amount / 2
        
    return render(request, "admin/invoices/preview.html", {
        'invoice': invoice,
        'logo_src': get_logo_data_uri(),
    })


@require_http_methods(["GET"])
def download_invoice(request, invoice_id):
    admin = _get_admin_from_session(request)
    if not admin:
        return redirect("admin_login_page")
        
    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM invoices WHERE id = %s", [invoice_id])
        if not cursor.description:
            raise Http404("Invoice not found")
        columns = [col[0] for col in cursor.description]
        row = cursor.fetchone()
        
        if not row:
            raise Http404("Invoice not found")
            
        invoice = dict(zip(columns, row))
        
    pdf_path = invoice.get('pdf_path')
    abs_path = get_pdf_absolute_path(pdf_path) if pdf_path else None
    
    # Generate if missing or not physically present
    if not pdf_path or not abs_path or not os.path.exists(abs_path):
        try:
            inv_obj = Invoice.objects.get(id=invoice_id)
            pdf_path = InvoiceService().generate_pdf(inv_obj)
            if not pdf_path:
                raise Http404("Could not generate PDF")
            abs_path = get_pdf_absolute_path(pdf_path)
            invoice_number = inv_obj.invoice_number
        except Invoice.DoesNotExist:
            raise Http404("Invoice not found")
    else:
        invoice_number = invoice.get('invoice_number')
        
    if not abs_path or not os.path.exists(abs_path):
        raise Http404("PDF file not found")
        
    # Keep the full invoice number in the download name (Laravel sends
    # "PA/26-27/XXXXX.pdf"); replace "/" so the filename survives browser
    # sanitization.
    filename = f"{invoice_number.replace('/', '-')}.pdf"
    
    return FileResponse(open(abs_path, 'rb'), as_attachment=True, filename=filename)


@require_http_methods(["POST"])
def save_sheet_url(request):
    admin = _get_admin_from_session(request)
    if not admin:
        return redirect("admin_login_page")
        
    sheet_url = request.POST.get('sheet_url', '').strip()
    sheet_view_url = request.POST.get('sheet_view_url', '').strip()

    # Smart auto-detection if user pasted a spreadsheet link into script URL or vice-versa
    if 'docs.google.com/spreadsheets' in sheet_url and not sheet_view_url:
        sheet_view_url = sheet_url
        sheet_url = ''
        messages.warning(request, 'You pasted a Google Sheet spreadsheet link. For auto-syncing, also paste the Apps Script Web App URL.')
    elif 'script.google.com' in sheet_view_url and not sheet_url:
        sheet_url = sheet_view_url
        sheet_view_url = ''
    
    with connection.cursor() as cursor:
        if sheet_url:
            cursor.execute("""
                INSERT INTO site_settings (`key`, `value`, `group`, `created_at`, `updated_at`) 
                VALUES ('invoice_google_sheet_url', %s, 'invoices', NOW(), NOW())
                ON DUPLICATE KEY UPDATE `value` = VALUES(`value`), `updated_at` = NOW()
            """, [sheet_url])
        
        if sheet_view_url:
            cursor.execute("""
                INSERT INTO site_settings (`key`, `value`, `group`, `created_at`, `updated_at`) 
                VALUES ('invoice_google_sheet_view_url', %s, 'invoices', NOW(), NOW())
                ON DUPLICATE KEY UPDATE `value` = VALUES(`value`), `updated_at` = NOW()
            """, [sheet_view_url])
        
    messages.success(request, 'Google Sheet settings saved successfully!')
    return redirect('admin_invoices')


@require_http_methods(["POST"])
def sync_sheet(request):
    admin = _get_admin_from_session(request)
    if not admin:
        return redirect("admin_login_page")

    with connection.cursor() as cursor:
        cursor.execute("SELECT value FROM site_settings WHERE `key` = 'invoice_google_sheet_url'")
        row = cursor.fetchone()
        sheet_url = row[0] if row else None

    if not sheet_url:
        messages.error(request, 'Google Sheet URL is not configured. Please save a URL first.')
        return redirect('admin_invoices')

    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM invoices WHERE synced_to_sheet = 0")
        pending = cursor.fetchone()[0]

    count = sync_all_pending(limit=50)
    if pending > count:
        messages.success(request, f"Synced {count} invoice(s) to Google Sheet ({pending - count} remaining).")
    else:
        messages.success(request, f"Synced {count} invoice(s) to Google Sheet successfully.")
    return redirect('admin_invoices')


@require_http_methods(["POST"])
def sync_single_invoice(request, invoice_id):
    admin = _get_admin_from_session(request)
    if not admin:
        return redirect("admin_login_page")

    from apps.admin_panel.services.google_sheet_sync import sync_invoice_to_sheet
    from apps.agents.models import Invoice

    inv = Invoice.objects.filter(id=invoice_id).first()
    inv_label = inv.invoice_number if inv else f"#{invoice_id}"

    success = sync_invoice_to_sheet(invoice_id)
    if success:
        messages.success(request, f"Invoice {inv_label} synced to Google Sheet successfully!")
    else:
        messages.error(request, f"Failed to sync invoice {inv_label} to Google Sheet. Check the Web App URL.")

    referrer = request.META.get('HTTP_REFERER')
    if referrer and '/admin/invoices' in referrer:
        return redirect(referrer)
    return redirect('admin_invoices')



@require_http_methods(["GET"])
def open_sheet(request):
    admin = _get_admin_from_session(request)
    if not admin:
        return redirect("admin_login_page")
        
    with connection.cursor() as cursor:
        # Prioritize direct spreadsheet URL if saved
        cursor.execute("SELECT value FROM site_settings WHERE `key` = 'invoice_google_sheet_view_url'")
        row_view = cursor.fetchone()
        view_url = row_view[0] if row_view and row_view[0] else None

        if not view_url:
            cursor.execute("SELECT value FROM site_settings WHERE `key` = 'invoice_google_sheet_url'")
            row_script = cursor.fetchone()
            view_url = row_script[0] if row_script and row_script[0] else None
        
    if not view_url:
        messages.warning(request, 'No Google Sheet link has been saved yet.')
        return redirect('admin_invoices')
        
    return redirect(view_url)


@require_http_methods(["GET", "POST"])
def create_manual_invoice(request):
    admin = _get_admin_from_session(request)
    if not admin:
        return redirect("admin_login_page")

    if request.method == "GET":
        from apps.home.models import SiteSetting
        pricing_config = SiteSetting.get_value('pricing_config') or {}
        starter = pricing_config.get('starter', {})
        prof = pricing_config.get('professional', {})
        
        old = request.session.pop('invoice_old', {})
        
        context = {
            'starter': starter,
            'prof': prof,
            'old': old,
        }
        return render(request, "admin/invoices/create.html", context)

    # POST processing
    name = request.POST.get('name', '').strip()
    email = request.POST.get('email', '').strip()
    mobile = request.POST.get('mobile', '').strip()
    address = request.POST.get('address', '').strip()
    state = request.POST.get('state', '').strip()
    
    plan_name = request.POST.get('plan_name', '').strip()
    base_amount_str = request.POST.get('base_amount', '0')
    gst_amount_str = request.POST.get('gst_amount', '0')
    total_amount_str = request.POST.get('total_amount', '0')
    # Uppercase to stay consistent with admin_verify_promo, which looks up
    # codes in upper case. Otherwise a lowercase-typed promo verifies and
    # discounts the amounts client-side but is never found on the server,
    # leaving discount_percent=0 / discount_folder='no_discount'.
    promo_code_str = request.POST.get('promo_code', '').strip().upper()
    custom_invoice_number = request.POST.get('invoice_number', '').strip()
    payment_id = request.POST.get('razorpay_payment_id', '').strip()
    send_email = request.POST.get('send_email') in ('on', '1', 'true')
    
    email_subject = request.POST.get('email_subject', 'Your Invoice from Padosi').strip()
    email_header = request.POST.get('email_header', '').strip()
    email_body = request.POST.get('email_body', '').strip()

    old_values = {
        'name': name, 'email': email, 'mobile': mobile, 'address': address, 'state': state,
        'plan_name': plan_name, 'base_amount': base_amount_str, 'gst_amount': gst_amount_str,
        'total_amount': total_amount_str, 'promo_code': promo_code_str,
        'invoice_number': custom_invoice_number, 'razorpay_payment_id': payment_id,
        'send_email': send_email, 'email_subject': email_subject,
        'email_header': email_header, 'email_body': email_body,
    }

    def back_with_error(message):
        request.session['invoice_old'] = old_values
        messages.error(request, message)
        return redirect('admin_invoices_create')

    try:
        base_amount = float(base_amount_str)
        gst_amount = float(gst_amount_str)
        total_amount = float(total_amount_str)
    except ValueError:
        return back_with_error('Invalid amounts provided.')

    from apps.home.models import SiteSetting
    pricing_config = SiteSetting.get_value('pricing_config') or {}
    
    plan_name_lower = plan_name.lower()
    full_price = 0
    if 'trial' in plan_name_lower:
        full_price = 0
    elif 'starter' in plan_name_lower or 'basic' in plan_name_lower:
        full_price = float(pricing_config.get('starter', {}).get('full_price', 2359))
    elif 'professional' in plan_name_lower:
        full_price = float(pricing_config.get('professional', {}).get('full_price', 8258))

    discount_percent = 0
    if full_price > 0 and total_amount < full_price:
        discount_percent = round(((full_price - total_amount) / full_price) * 100, 1)
        discount_percent = max(0, discount_percent)
    elif promo_code_str:
        try:
            pc = PromoCode.objects.get(code=promo_code_str, is_active=True)
            if pc.is_valid():
                discount_percent = pc.discount_value
        except PromoCode.DoesNotExist:
            pass

    # Invoice number: custom (with duplicate check) or auto-generated PA/YY-YY/XXXXX
    if custom_invoice_number:
        if Invoice.objects.filter(invoice_number=custom_invoice_number).exists():
            return back_with_error(f"Invoice number {custom_invoice_number} already exists. Please use a different number.")
        invoice_number = custom_invoice_number
    else:
        invoice_number = generate_invoice_number()

    # We need a Dummy Agent because Invoice requires agent_id.
    # Let's find or create a dummy agent for manual invoices.
    dummy_email = "manual_invoice_dummy@padosi.local"
    agent, created = Agent.objects.get_or_create(
        email=dummy_email,
        defaults={
            'fullname': "Manual Invoice User",
            'mobile': "0000000000",
            'status': "incomplete"
        }
    )

    folder = Invoice.resolve_discount_folder(discount_percent, total_amount)

    invoice = Invoice.objects.create(
        invoice_number=invoice_number,
        agent=agent,
        agent_name=name,
        agent_email=email,
        agent_mobile=mobile,
        agent_address=address,
        agent_state=state,
        plan_name=plan_name,
        plan_type='manual',
        base_amount=base_amount,
        gst_amount=gst_amount,
        total_amount=total_amount,
        discount_percent=discount_percent,
        discount_folder=folder,
        promo_code=promo_code_str,
        razorpay_payment_id=payment_id or None,
        payment_status='paid'
    )

    # Generate PDF
    pdf_path = InvoiceService().generate_pdf(invoice)
    if not pdf_path:
        # The invoice row was already created; remove it (and any partially
        # written PDF) so a custom invoice number/folder is not consumed by a
        # failed creation. Without this, retrying with the same number fails
        # with "already exists" and an orphan row stays in the DB.
        invoice.delete()
        guess_path = get_pdf_absolute_path(f"invoices/{folder}/{invoice_number}.pdf")
        try:
            if guess_path and os.path.exists(guess_path):
                os.remove(guess_path)
        except OSError:
            pass
        return back_with_error("Failed to generate Invoice PDF.")

    abs_pdf_path = get_pdf_absolute_path(pdf_path)
    if not abs_pdf_path or not os.path.exists(abs_pdf_path):
        invoice.delete()
        return back_with_error("Failed to locate generated PDF.")

    # Send email only when requested
    if send_email:
        try:
            # Use Brevo/SMTP fallback service
            from apps.agents.services.brevo import email_service
            body = f"{email_header}<br><br>{email_body}".replace('\n', '<br>')
            success = email_service.send_generic(
                to_email=email,
                to_name=name,
                subject=email_subject,
                html_content=body,
                attachment_path=abs_pdf_path
            )
            if not success:
                return back_with_error(f"Invoice {invoice_number} created but failed to send email via Brevo or SMTP.")
        except Exception as e:
            return back_with_error(f"Invoice created but failed to send email: {str(e)}")
        
        messages.success(request, f"Invoice {invoice_number} created and emailed to {email} successfully.")
    else:
        messages.success(request, f"Invoice {invoice_number} created successfully.")

    return redirect('admin_invoices_create')

@require_http_methods(["POST"])
def admin_verify_promo(request):
    import json
    admin = _get_admin_from_session(request)
    if not admin:
        return JsonResponse({'success': False, 'message': 'Unauthorized'})

    try:
        data = json.loads(request.body)
        promo_code = data.get('promo_code', '').strip().upper()
    except Exception:
        promo_code = request.POST.get('promo_code', '').strip().upper()

    if not promo_code:
        return JsonResponse({'success': False, 'message': 'Promo code is required.'})

    try:
        promo = PromoCode.objects.get(code=promo_code, is_active=True)
        if promo.is_valid():
            return JsonResponse({
                'success': True,
                'discount_type': promo.discount_type,
                'discount_value': float(promo.discount_value),
                'message': f'Promo code applied successfully!',
            })
    except PromoCode.DoesNotExist:
        pass

    return JsonResponse({
        'success': False,
        'message': 'Invalid or expired promo code.',
    })
