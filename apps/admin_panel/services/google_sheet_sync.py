import os
import base64
import requests
import time
import logging
from datetime import datetime
from django.db import connection
from .invoice_storage import get_invoice_root, get_folder_path
from apps.agents.services.invoice import get_pdf_absolute_path

logger = logging.getLogger(__name__)

def sync_invoice_to_sheet(invoice_id):
    """
    Sync a single invoice to the Google Sheet using the exact 16-column mapping.
    Non-blocking: catches all exceptions and logs instead of failing.
    """
    try:
        from apps.agents.models import Invoice
        from apps.agents.services.invoice import invoice_service

        if isinstance(invoice_id, Invoice):
            return invoice_service.sync_to_google_sheet(invoice_id)

        invoice = Invoice.objects.filter(id=invoice_id).first()
        if invoice:
            return invoice_service.sync_to_google_sheet(invoice)

        # Fallback to direct raw query if ORM record not found
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM invoices WHERE id = %s", [invoice_id])
            columns = [col[0] for col in cursor.description] if cursor.description else []
            row = cursor.fetchone()
            if not row:
                return False
            invoice_dict = dict(zip(columns, row))

        return invoice_service.sync_to_google_sheet(invoice_dict)

    except Exception as e:
        logger.exception(f"[GOOGLE SHEET SYNC] Exception: {str(e)}")
        # Non-blocking - do NOT rethrow
        return False


def sync_all_pending(limit=50):
    """
    Re-sync unsynced invoices in safe batches to avoid web request timeouts.
    """
    with connection.cursor() as cursor:
        cursor.execute("SELECT value FROM site_settings WHERE `key` = 'invoice_google_sheet_url'")
        row = cursor.fetchone()
        sheet_url = row[0] if row else None

    if not sheet_url:
        return 0

    with connection.cursor() as cursor:
        cursor.execute("SELECT id FROM invoices WHERE synced_to_sheet = 0 ORDER BY id DESC LIMIT %s", [limit])
        rows = cursor.fetchall()
        
    count = 0
    for row in rows:
        invoice_id = row[0]
        if sync_invoice_to_sheet(invoice_id):
            count += 1
        # 100ms delay to avoid rate limiting
        time.sleep(0.1)
        
    return count

