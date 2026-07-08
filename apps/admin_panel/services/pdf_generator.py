import os
import datetime
import pdfkit
from django.conf import settings
from django.db import connection
from django.template.loader import render_to_string
from .invoice_storage import get_invoice_root, get_folder_path, ensure_invoice_directories

def resolve_discount_folder(discount_percent, total_amount):
    """
    Match Laravel exactly:
    total_amount <= 1.00 -> 1re
    0 -> no_discount
    10 -> 10_percent
    25 -> 25_percent
    50 -> 50_percent
    everything else -> others
    """
    try:
        total_amount = float(total_amount)
    except (TypeError, ValueError):
        total_amount = 0.0

    try:
        discount_percent = float(discount_percent)
    except (TypeError, ValueError):
        discount_percent = 0.0

    if total_amount <= 1.00:
        return '1re'
    
    if discount_percent == 0:
        return 'no_discount'
    elif discount_percent == 10:
        return '10_percent'
    elif discount_percent == 25:
        return '25_percent'
    elif discount_percent == 50:
        return '50_percent'
    else:
        return 'others'

def generate_invoice_number():
    """
    Match Laravel: INV-YYYY-XXXXX
    Use current year. Check collisions via Raw SQL.
    """
    year = datetime.datetime.now().year
    
    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM invoices WHERE YEAR(created_at) = %s", [year])
        row = cursor.fetchone()
        count = (row[0] if row else 0) + 1
        
        while True:
            number = f"INV-{year}-{count:05d}"
            cursor.execute("SELECT 1 FROM invoices WHERE invoice_number = %s", [number])
            if not cursor.fetchone():
                return number
            count += 1

def generate_invoice_pdf(invoice_id):
    """
    Fetch invoice via raw SQL, render pdf.html and generate PDF using pdfkit + wkhtmltopdf.
    Reuses existing PDF if present.
    Returns dictionary with success status and details.
    """
    ensure_invoice_directories()
    
    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM invoices WHERE id = %s", [invoice_id])
        columns = [col[0] for col in cursor.description]
        row = cursor.fetchone()
        
        if not row:
            return {"success": False, "error": "Invoice not found"}
            
        invoice_data = dict(zip(columns, row))
        
    # Build invoice context (GST logic for template)
    agent_state = invoice_data.get('agent_state') or ''
    is_igst = 'gujarat' not in agent_state.lower()
    invoice_data['is_igst'] = is_igst
    
    gst_amount = float(invoice_data.get('gst_amount') or 0)
    if is_igst:
        invoice_data['gst_amount_igst'] = gst_amount
    else:
        invoice_data['gst_amount_cgst'] = gst_amount / 2
        invoice_data['gst_amount_sgst'] = gst_amount / 2

    invoice_number = invoice_data.get('invoice_number')
    if not invoice_number:
        invoice_number = generate_invoice_number()
        invoice_data['invoice_number'] = invoice_number
        with connection.cursor() as cursor:
            cursor.execute("UPDATE invoices SET invoice_number = %s WHERE id = %s", [invoice_number, invoice_id])
    
    total_amount = invoice_data.get('total_amount', 0)
    discount_percent = invoice_data.get('discount_percent', 0)
    
    folder = invoice_data.get('discount_folder')
    if not folder:
        folder = resolve_discount_folder(discount_percent, total_amount)
        invoice_data['discount_folder'] = folder
    
    pdf_path = f"invoices/{folder}/{invoice_number}.pdf"
    
    # Store relative path in database if empty or changed
    if invoice_data.get('pdf_path') != pdf_path:
        with connection.cursor() as cursor:
            cursor.execute("UPDATE invoices SET pdf_path = %s, discount_folder = %s WHERE id = %s", [pdf_path, folder, invoice_id])
    
    folder_abs_path = get_folder_path(folder)
    absolute_path = os.path.join(str(folder_abs_path), f"{invoice_number}.pdf")
    
    # Check if PDF already exists (Laravel behavior: do not regenerate if present)
    if os.path.exists(absolute_path):
        return {
            "success": True,
            "invoice_number": invoice_number,
            "folder": folder,
            "pdf_path": pdf_path,
            "absolute_path": absolute_path,
            "status": "reused"
        }
    
    # Render HTML template natively
    html_string = render_to_string('admin/invoices/pdf.html', {'invoice': invoice_data})
    
    # Generate PDF via pdfkit
    resolved_path = settings.WKHTMLTOPDF_PATH
    print(f"[DEBUG PDFKIT] Resolved WKHTMLTOPDF_PATH from settings: {resolved_path}")
    
    if not resolved_path:
        raise RuntimeError(
            "wkhtmltopdf executable not found in PATH. "
            "Please ensure wkhtmltopdf is installed and its bin directory is added to your system PATH."
        )
        
    try:
        config = pdfkit.configuration(wkhtmltopdf=resolved_path)
        print(f"[DEBUG PDFKIT] Successfully created pdfkit configuration using: {resolved_path}")
    except Exception as e:
        print(f"[DEBUG PDFKIT] Failed to create pdfkit configuration: {e}")
        raise
        
    options = {
        'page-size': 'A4',
        'margin-top': '0.5cm',
        'margin-right': '0.5cm',
        'margin-bottom': '0.5cm',
        'margin-left': '0.5cm',
        'encoding': "UTF-8",
        'enable-local-file-access': None
    }
    
    pdfkit.from_string(html_string, absolute_path, configuration=config, options=options)
    
    return {
        "success": True,
        "invoice_number": invoice_number,
        "folder": folder,
        "pdf_path": pdf_path,
        "absolute_path": absolute_path,
        "status": "generated"
    }

def get_pdf_absolute_path(pdf_path):
    """
    Helper to resolve the database pdf_path string to the physical file system absolute path.
    """
    if not pdf_path:
        return None
        
    parts = pdf_path.replace("\\", "/").split('/')
    if len(parts) >= 2:
        filename = parts[-1]
        folder = parts[-2]
        return str(get_folder_path(folder) / filename)
        
    return None

def pdf_exists(pdf_path):
    """
    Return True if PDF exists on the disk.
    """
    abs_path = get_pdf_absolute_path(pdf_path)
    if not abs_path:
        return False
    return os.path.exists(abs_path)
