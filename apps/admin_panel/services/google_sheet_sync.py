import os
import base64
import requests
import time
from datetime import datetime
from django.db import connection
from .invoice_storage import get_invoice_root, get_folder_path
from .pdf_generator import get_pdf_absolute_path

def sync_invoice_to_sheet(invoice_id):
    """
    Sync a single invoice to the Google Sheet using the exact mapping.
    Non-blocking: catches all exceptions and logs/prints instead of failing.
    """
    try:
        # Fetch Web App URL
        with connection.cursor() as cursor:
            cursor.execute("SELECT value FROM site_settings WHERE `key` = 'invoice_google_sheet_url'")
            row = cursor.fetchone()
            sheet_url = row[0] if row else None

        if not sheet_url:
            return False  # Not configured, skip silently

        # Fetch Invoice
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM invoices WHERE id = %s", [invoice_id])
            columns = [col[0] for col in cursor.description] if cursor.description else []
            row = cursor.fetchone()
            if not row:
                return False
            invoice = dict(zip(columns, row))

        # Extract base64 PDF content if it exists
        pdf_base64 = None
        abs_path = get_pdf_absolute_path(invoice.get('pdf_path'))
        if abs_path and os.path.exists(abs_path):
            with open(abs_path, 'rb') as f:
                pdf_base64 = base64.b64encode(f.read()).decode('utf-8')

        # Folder logic
        folder_raw = invoice.get('discount_folder', 'others')
        labels = {
            'no_discount': 'No Discount',
            '10_percent': '10%',
            '25_percent': '25%',
            '50_percent': '50%',
            '1re': '₹1 (Special)'
        }
        discount_folder = labels.get(folder_raw, 'Others')

        # Format date as 'd/m/Y H:i'
        created_at = invoice.get('created_at')
        if created_at:
            # handle both string and datetime
            if isinstance(created_at, str):
                try:
                    dt = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
                    formatted_date = dt.strftime("%d/%m/%Y %H:%M")
                except ValueError:
                    formatted_date = created_at
            else:
                formatted_date = created_at.strftime("%d/%m/%Y %H:%M")
        else:
            formatted_date = ''

        # For preview URL, Django request is not easily available here, so construct manually
        pdf_url = f"/admin/invoices/{invoice_id}/preview"

        payload = {
            'invoice_number': invoice.get('invoice_number'),
            'date': formatted_date,
            'agent_id': invoice.get('agent_id'),
            'agent_name': invoice.get('agent_name'),
            'agent_email': invoice.get('agent_email'),
            'agent_mobile': invoice.get('agent_mobile'),
            'plan_name': invoice.get('plan_name'),
            'base_amount': float(invoice.get('base_amount') or 0),
            'gst_amount': float(invoice.get('gst_amount') or 0),
            'total_amount': float(invoice.get('total_amount') or 0),
            'discount_percent': float(invoice.get('discount_percent') or 0),
            'discount_folder': discount_folder,
            'payment_id': invoice.get('razorpay_payment_id'),
            'payment_status': invoice.get('payment_status'),
            'promo_code': invoice.get('promo_code'),
            'pdf_url': pdf_url,
            'pdf_base64': pdf_base64,
        }

        response = requests.post(sheet_url, json=payload, timeout=10)

        if response.status_code == 200:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE invoices SET synced_to_sheet = 1, synced_at = NOW() WHERE id = %s",
                    [invoice_id]
                )
            print(f"[GOOGLE SHEET SYNC] Success: {invoice.get('invoice_number')}")
            return True
        else:
            print(f"[GOOGLE SHEET SYNC] Failed: {invoice.get('invoice_number')} Status: {response.status_code} Body: {response.text}")
            return False

    except Exception as e:
        print(f"[GOOGLE SHEET SYNC] Exception: {str(e)}")
        # Non-blocking - do NOT rethrow
        return False


def sync_all_pending():
    """
    Re-sync all unsynced invoices synchronously.
    """
    with connection.cursor() as cursor:
        cursor.execute("SELECT value FROM site_settings WHERE `key` = 'invoice_google_sheet_url'")
        row = cursor.fetchone()
        sheet_url = row[0] if row else None

    if not sheet_url:
        return 0

    with connection.cursor() as cursor:
        cursor.execute("SELECT id FROM invoices WHERE synced_to_sheet = 0")
        rows = cursor.fetchall()
        
    count = 0
    for row in rows:
        invoice_id = row[0]
        if sync_invoice_to_sheet(invoice_id):
            count += 1
        # 200ms delay to avoid rate limiting
        time.sleep(0.2)
        
    return count
