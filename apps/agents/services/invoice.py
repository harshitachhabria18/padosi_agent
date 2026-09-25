"""
Invoice Generation Service — PadosiAgent
=========================================

Handles:
  1. Creation of Invoice database record.
  2. Generation of HTML-to-PDF invoice using xhtml2pdf.
  3. Storing PDFs under media/invoices/{discount_folder}/.
  4. Syncing invoice rows to Google Sheet via site setting Web App URL.
"""

import os
import base64
import logging
import requests
from datetime import datetime
from django.conf import settings
from django.template.loader import render_to_string

from apps.agents.models import Agent, AgentSubscription, Invoice
from apps.home.models import SiteSetting

logger = logging.getLogger(__name__)

def get_logo_data_uri():
    """Embed the PadosiAgent logo as a base64 data URI."""
    try:
        from django.contrib.staticfiles import finders
    except Exception:
        finders = None
    for name in ('img/logo.webp', 'img/logo.png'):
        path = finders.find(name) if finders else None
        if path and os.path.exists(path):
            ext = 'png' if name.endswith('.png') else 'webp'
            with open(path, 'rb') as f:
                return f"data:image/{ext};base64,{base64.b64encode(f.read()).decode()}"
    return ''

def get_pdf_absolute_path(pdf_path):
    if not pdf_path:
        return None
    if os.path.isabs(pdf_path):
        return pdf_path
    clean_path = str(pdf_path).replace('\\', '/').lstrip('/')
    if clean_path.startswith('media/'):
        clean_path = clean_path[len('media/'):]
    if clean_path.startswith('app/private/'):
        return os.path.join(settings.MEDIA_ROOT, clean_path)
    return os.path.join(settings.MEDIA_ROOT, 'app', 'private', clean_path)

def calculate_tax_breakdown(gst_amount: float, state: str) -> dict:
    """
    Calculate CGST, SGST, IGST and place of supply.
    Gujarat -> Intra-state: CGST 9% + SGST 9%, IGST 0.
    Other Indian States -> Inter-state: CGST 0, SGST 0, IGST 18%.
    Supports full state names and 'gj' state code.
    """
    state_str = str(state or '').strip()
    place_of_supply = state_str if state_str else 'Gujarat'
    clean_lower = place_of_supply.lower()
    is_gujarat = 'gujarat' in clean_lower or clean_lower == 'gj'
    is_igst = not is_gujarat
    if clean_lower == 'gj':
        place_of_supply = 'Gujarat'
    gst_val = round(float(gst_amount or 0), 2)

    if is_igst:
        cgst = 0.0
        sgst = 0.0
        igst = gst_val
    else:
        cgst = round(gst_val / 2, 2)
        sgst = round(gst_val - cgst, 2)
        igst = 0.0

    return {
        'place_of_supply': place_of_supply,
        'is_igst': is_igst,
        'cgst': cgst,
        'sgst': sgst,
        'igst': igst,
    }

def generate_invoice_number() -> str:
    """
    Generate a unique invoice number matching Laravel's InvoiceService::generateInvoiceNumber().

    Format: PA/{yy}-{yy}/{seq:05d}  (e.g. PA/26-27/00042)

    - Financial-year prefix: resets on April 1st.
    - Next sequence = MAX(numeric tail) + 1 across rows with the current prefix.
    - Falls back to 42 when no PA/... row exists (byte-for-byte Laravel parity).
    - Collision-safety loop skips any number that already exists.
    """
    now = datetime.now()
    start_year = now.year if now.month >= 4 else now.year - 1
    end_year = start_year + 1
    prefix = f"PA/{str(start_year)[-2:]}-{str(end_year)[-2:]}/"

    from django.db import connection
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT invoice_number FROM invoices WHERE invoice_number LIKE %s "
            "ORDER BY CAST(SUBSTRING(invoice_number, %s) AS UNSIGNED) DESC LIMIT 1",
            [prefix + '%', len(prefix) + 1],
        )
        row = cursor.fetchone()

    next_num = 42
    if row:
        try:
            next_num = int(row[0][len(prefix):]) + 1
        except ValueError:
            next_num = 42

    while True:
        number = f"{prefix}{next_num:05d}"
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM invoices WHERE invoice_number = %s", [number])
            if not cursor.fetchone():
                return number
        next_num += 1


def link_callback(uri, rel):
    """
    Convert HTML URIs to absolute system paths so xhtml2pdf can access those resources.
    """
    static_url = settings.STATIC_URL.strip("/")
    media_url = settings.MEDIA_URL.strip("/")
    clean_uri = uri.lstrip("/")

    if clean_uri.startswith(media_url):
        relative_path = clean_uri.replace(media_url, "").lstrip("/")
        path = os.path.join(settings.MEDIA_ROOT, relative_path)
    elif clean_uri.startswith(static_url):
        relative_path = clean_uri.replace(static_url, "").lstrip("/")
        static_dir = settings.STATIC_ROOT or (settings.BASE_DIR / "static")
        path = os.path.join(static_dir, relative_path)
    else:
        path = uri

    # Make sure that path exists
    if not os.path.isfile(path):
        # Fallback search under STATICFILES_DIRS
        for static_dir in getattr(settings, "STATICFILES_DIRS", []):
            relative_path = clean_uri
            if clean_uri.startswith(static_url):
                relative_path = clean_uri.replace(static_url, "").lstrip("/")
            candidate = os.path.join(static_dir, relative_path)
            if os.path.isfile(candidate):
                return candidate
        return uri
    return path


class InvoiceService:
    """
    Service for managing agent payment invoices, PDF creation, and syncing.
    """

    def generate_from_subscription(self, agent: Agent, subscription: AgentSubscription, sync_sheet: bool = True) -> Invoice:
        """
        Generate, compile, save, and optionally sync invoice for a completed payment.
        Matches Laravel's InvoiceService::generateFromSubscription.

        Pass sync_sheet=False when the caller will sync (or skip) later so PDF
        generation is not blocked on the Google Sheet webhook.
        """
        try:
            # 1. Avoid duplicates
            if subscription.razorpay_payment_id:
                existing = Invoice.objects.filter(razorpay_payment_id=subscription.razorpay_payment_id).first()
                if existing:
                    logger.info(f"[InvoiceService] Invoice already exists for payment: {subscription.razorpay_payment_id}")
                    return existing

            total_amount = float(subscription.registration_amount or 0)
            base_amount = round(total_amount / 1.18, 2)
            gst_amount = round(total_amount - base_amount, 2)

            # 2. Calculate discount percent
            discount_percent = self.calculate_discount_percent(agent, subscription, total_amount)

            # 3. Resolve discount folder name
            folder = Invoice.resolve_discount_folder(discount_percent, total_amount)

            profile = agent.get_primary_profile()
            agent_address = profile.address if (profile and profile.address) else ''
            agent_state = profile.state if (profile and profile.state) else ''
            if not agent_state and agent.registration_draft and isinstance(agent.registration_draft, dict):
                agent_state = agent.registration_draft.get('state', '')
                if not agent_address and agent.registration_draft.get('address'):
                    agent_address = agent.registration_draft.get('address', '')
            if not agent_state:
                try:
                    from apps.agents.models import AgentDraft
                    draft = AgentDraft.objects.filter(email=agent.email).first()
                    if draft and draft.state:
                        agent_state = draft.state
                        if not agent_address and draft.address:
                            agent_address = draft.address
                except Exception:
                    pass
            if not agent_state:
                agent_state = 'Gujarat'

            # 5. Create Invoice Database record with retry on sequence collision
            from django.db import IntegrityError
            invoice = None
            for attempt in range(5):
                invoice_number = self.generate_invoice_number()
                try:
                    invoice = Invoice.objects.create(
                        invoice_number=invoice_number,
                        agent=agent,
                        agent_name=agent.fullname,
                        agent_email=agent.email,
                        agent_mobile=agent.mobile,
                        agent_address=agent_address,
                        agent_state=agent_state,
                        plan_name=subscription.selected_plan,
                        plan_type=agent.plan_type or 'professional',
                        base_amount=base_amount,
                        gst_amount=gst_amount,
                        total_amount=total_amount,
                        discount_percent=discount_percent,
                        discount_folder=folder,
                        promo_code=subscription.promo_code,
                        razorpay_payment_id=subscription.razorpay_payment_id,
                        razorpay_order_id=subscription.razorpay_order_id,
                        payment_status='paid',
                    )
                    break
                except IntegrityError as ie:
                    if 'invoice_number' in str(ie) and attempt < 4:
                        logger.warning(
                            f"[InvoiceService] Invoice number collision on {invoice_number}, "
                            f"retrying attempt {attempt + 1}"
                        )
                        continue
                    raise

            # 6. Render and generate PDF
            pdf_path = self.generate_pdf(invoice)
            if pdf_path:
                invoice.pdf_path = pdf_path
                invoice.save(update_fields=['pdf_path'])

            if sync_sheet:
                self.sync_to_google_sheet(invoice)

            logger.info(
                f"[InvoiceService] Invoice generated successfully: {invoice_number} "
                f"for agent={agent.id} (total={total_amount})"
            )
            return invoice

        except Exception as e:
            logger.error(f"[InvoiceService] Invoice generation failed for agent={agent.id}: {e}", exc_info=True)
            return None

    def generate_invoice_number(self) -> str:
        """
        Generate unique invoice number like PA/26-27/00042.
        Matches Laravel's generateInvoiceNumber (financial-year prefix, MAX-based sequence).
        """
        return generate_invoice_number()

    def calculate_discount_percent(self, agent: Agent, subscription: AgentSubscription, paid_amount: float) -> float:
        """
        Calculate discount % compared to the full plan price.
        Prices must come from DB only — no hardcoded fallbacks.
        """
        if paid_amount <= 1.00:
            return 99.9

        from apps.home.models import SiteSetting
        pricing_config = SiteSetting.get_value('pricing_config')
        if not pricing_config:
            raise ValueError('pricing_config not found in site_settings')

        plan_name = str(subscription.selected_plan or '').lower()

        if 'trial' in plan_name:
            return 0.0

        starter_cfg = pricing_config.get('starter', {})
        prof_cfg = pricing_config.get('professional', {})

        full_price = float(starter_cfg.get('full_price', 0))
        if 'professional' in plan_name or 'pro' in plan_name:
            full_price = float(prof_cfg.get('full_price', 0))

        if full_price <= 0:
            return 0.0

        discount = round(((full_price - paid_amount) / full_price) * 100, 1)
        return max(0.0, discount)

    def generate_pdf(self, invoice: Invoice) -> str:
        """
        Render templates/pdf/invoice.html to PDF using xhtml2pdf.
        Saves file to media/invoices/{discount_folder}/{invoice_number}.pdf.
        """
        try:
            # Calculate tax breakdown
            tax_info = calculate_tax_breakdown(invoice.gst_amount, invoice.agent_state)
            half_gst = tax_info['cgst']
            
            item_name = invoice.plan_name
            
            if invoice.plan_type == 'free_trial':
                plan_desc = "PadosiAgent Subscription – 30 Day Trial"
            elif invoice.plan_type in ('basic', 'starter'):
                plan_desc = "PadosiAgent Subscription – 1 Year Starter"
            elif invoice.plan_type == 'exclusive':
                plan_desc = "PadosiAgent Subscription – Exclusive Plan"
            else:
                plan_desc = "PadosiAgent Subscription – 1 Year Professional"

            # Attach GST template variables dynamically to the ORM object
            invoice.is_igst = tax_info['is_igst']
            invoice.gst_amount_igst = tax_info['igst']
            invoice.gst_amount_cgst = tax_info['cgst']
            invoice.gst_amount_sgst = tax_info['sgst']

            font_path = (settings.BASE_DIR / 'static' / 'fonts' / 'DejaVuSans.ttf').as_posix()
            font_path_bold = (settings.BASE_DIR / 'static' / 'fonts' / 'DejaVuSans-Bold.ttf').as_posix()
            
            context = {
                'invoice': invoice,
                'items': [
                    {
                        'name': item_name,
                        'description': plan_desc,
                        'amount': invoice.base_amount,
                    }
                ],
                'is_gujarat': not tax_info['is_igst'],
                'half_gst': half_gst,
                'logo_src': get_logo_data_uri(),
                'font_path': font_path,
                'font_path_bold': font_path_bold,
            }

            # Render HTML to string
            html_string = render_to_string('pdf/invoice.html', context)

            # Define output path (match Laravel: invoices/{discount_folder}/{invoice_number}.pdf)
            sub_folder = invoice.discount_folder or ('discount' if invoice.promo_code else 'no_discount')
            relative_dir = os.path.join('app', 'private', 'invoices', sub_folder)
            target_dir = os.path.join(settings.MEDIA_ROOT, relative_dir)
            os.makedirs(target_dir, exist_ok=True)

            filename = f"{invoice.invoice_number}.pdf"
            full_path = os.path.join(target_dir, filename)
            # Invoice numbers contain slashes (PA/26-27/XXXXX) -> create nested dirs
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            relative_path = os.path.join('invoices', sub_folder, filename).replace('\\', '/')

            # Temporary monkey-patch for xhtml2pdf Windows file-lock bug on NamedTemporaryFile
            import tempfile
            original_named_temp_file = tempfile.NamedTemporaryFile

            class ClosedNamedTemporaryFile:
                def __init__(self, *args, **kwargs):
                    kwargs['delete'] = False
                    self._file = original_named_temp_file(*args, **kwargs)
                    self.name = self._file.name
                    self._closed = False

                def write(self, data):
                    if not self._closed:
                        self._file.write(data)

                def flush(self):
                    if not self._closed:
                        self._file.flush()
                        self._file.close()
                        self._closed = True

                def close(self):
                    pass

                def __del__(self):
                    try:
                        if os.path.exists(self.name):
                            os.remove(self.name)
                    except Exception:
                        pass

            tempfile.NamedTemporaryFile = ClosedNamedTemporaryFile

            try:
                # Imported here, not at module load: xhtml2pdf/reportlab add
                # ~55 MB to every Passenger process, and only invoices use it.
                from xhtml2pdf import pisa
                with open(full_path, "w+b") as result_file:
                    pisa_status = pisa.CreatePDF(html_string, dest=result_file, link_callback=link_callback, encoding='utf-8')
            finally:
                # Restore original tempfile behavior
                tempfile.NamedTemporaryFile = original_named_temp_file

            if pisa_status.err:
                logger.error(f"[InvoiceService] PDF rendering failed for {invoice.invoice_number}")
                return None

            logger.info(f"[InvoiceService] PDF generated successfully: {full_path}")
            return relative_path

        except Exception as e:
            logger.error(f"[InvoiceService] generate_pdf exception: {e}", exc_info=True)
            return None

    def sync_to_google_sheet(self, invoice: Invoice) -> bool:
        """
        Synchronize invoice details to Google Sheet using Web App Script URL.
        Non-blocking operation. Sends all 16 columns matching Google Sheet headers:
        Invoice #, Date, Agent, Email, Mobile, Plan Name, Place of Supply, Base Amount,
        CGST, SGST, IGST, Total Amount, Payment ID, Promo Code, Discount Folder, PDF Link
        along with base64-encoded PDF binary to upload into Google Drive.
        """
        try:
            sheet_url = SiteSetting.get_value('invoice_google_sheet_url')
            if not sheet_url or not isinstance(sheet_url, str):
                return False

            sheet_url = sheet_url.strip()
            # SSRF protection: require HTTPS and block private / metadata IPs
            from urllib.parse import urlparse
            parsed = urlparse(sheet_url)
            if parsed.scheme != 'https' or not parsed.netloc:
                logger.warning(f"[InvoiceService] Rejected insecure non-HTTPS sheet URL: {sheet_url}")
                return False

            blocked_hosts = ('169.254.169.254', 'metadata.google.internal', 'localhost', '127.0.0.1', '0.0.0.0')
            if any(bh in parsed.netloc.lower() for bh in blocked_hosts):
                logger.warning(f"[InvoiceService] Blocked metadata/internal host in sheet sync: {parsed.netloc}")
                return False

            # Extract base64 PDF content if file exists on disk
            pdf_base64 = None
            pdf_path = getattr(invoice, 'pdf_path', None) if not isinstance(invoice, dict) else invoice.get('pdf_path')
            if pdf_path:
                abs_path = get_pdf_absolute_path(pdf_path)
                if abs_path and os.path.exists(abs_path):
                    try:
                        with open(abs_path, 'rb') as f:
                            pdf_base64 = base64.b64encode(f.read()).decode('utf-8')
                    except Exception as fe:
                        logger.warning(f"[InvoiceService] Could not read PDF for base64: {fe}")

            invoice_number = getattr(invoice, 'invoice_number', '') if not isinstance(invoice, dict) else invoice.get('invoice_number', '')
            created_at = getattr(invoice, 'created_at', None) if not isinstance(invoice, dict) else invoice.get('created_at')
            if created_at:
                if isinstance(created_at, str):
                    try:
                        dt = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
                        formatted_date = dt.strftime("%d/%m/%Y %H:%M")
                    except ValueError:
                        formatted_date = created_at
                else:
                    formatted_date = created_at.strftime("%d/%m/%Y %H:%M")
            else:
                formatted_date = datetime.now().strftime("%d/%m/%Y %H:%M")

            agent_name = getattr(invoice, 'agent_name', '') if not isinstance(invoice, dict) else invoice.get('agent_name', '')
            agent_email = getattr(invoice, 'agent_email', '') if not isinstance(invoice, dict) else invoice.get('agent_email', '')
            agent_mobile = getattr(invoice, 'agent_mobile', '') if not isinstance(invoice, dict) else invoice.get('agent_mobile', '')
            plan_name = getattr(invoice, 'plan_name', '') if not isinstance(invoice, dict) else invoice.get('plan_name', '')
            agent_state = getattr(invoice, 'agent_state', '') if not isinstance(invoice, dict) else invoice.get('agent_state', '')

            base_amount = float(getattr(invoice, 'base_amount', 0) if not isinstance(invoice, dict) else invoice.get('base_amount', 0) or 0)
            gst_amount = float(getattr(invoice, 'gst_amount', 0) if not isinstance(invoice, dict) else invoice.get('gst_amount', 0) or 0)
            total_amount = float(getattr(invoice, 'total_amount', 0) if not isinstance(invoice, dict) else invoice.get('total_amount', 0) or 0)
            discount_percent = float(getattr(invoice, 'discount_percent', 0) if not isinstance(invoice, dict) else invoice.get('discount_percent', 0) or 0)

            folder_raw = getattr(invoice, 'discount_folder', 'others') if not isinstance(invoice, dict) else invoice.get('discount_folder', 'others')
            folder_label = Invoice.folder_label(folder_raw) if hasattr(Invoice, 'folder_label') else str(folder_raw)

            payment_id = getattr(invoice, 'razorpay_payment_id', '') if not isinstance(invoice, dict) else invoice.get('razorpay_payment_id', '')
            payment_status = getattr(invoice, 'payment_status', 'paid') if not isinstance(invoice, dict) else invoice.get('payment_status', 'paid')
            promo_code = getattr(invoice, 'promo_code', '') if not isinstance(invoice, dict) else invoice.get('promo_code', '')

            tax_info = calculate_tax_breakdown(gst_amount, agent_state)

            pdf_url = f"{settings.MEDIA_URL}app/private/{pdf_path}" if pdf_path else ''

            payload = {
                # Snake-case keys
                'invoice_number': invoice_number,
                'date': formatted_date,
                'agent_name': agent_name,
                'agent_email': agent_email,
                'agent_mobile': agent_mobile or '',
                'plan_name': plan_name,
                'place_of_supply': tax_info['place_of_supply'],
                'base_amount': base_amount,
                'cgst': tax_info['cgst'],
                'sgst': tax_info['sgst'],
                'igst': tax_info['igst'],
                'gst_amount': gst_amount,
                'total_amount': total_amount,
                'discount_percent': discount_percent,
                'discount_folder': folder_label,
                'payment_id': payment_id or 'N/A',
                'payment_status': payment_status,
                'promo_code': promo_code or '',
                'pdf_url': pdf_url,
                'pdf_base64': pdf_base64,
                # Exact 16 Google Sheet Column Aliases matching user header format
                'Invoice #': invoice_number,
                'Date': formatted_date,
                'Agent': agent_name,
                'Email': agent_email,
                'Mobile': agent_mobile or '',
                'Plan Name': plan_name,
                'Place of Supply': tax_info['place_of_supply'],
                'Base Amount': base_amount,
                'CGST': tax_info['cgst'],
                'SGST': tax_info['sgst'],
                'IGST': tax_info['igst'],
                'Total Amount': total_amount,
                'Payment ID': payment_id or 'N/A',
                'Promo Code': promo_code or '',
                'Discount Folder': folder_label,
            }

            response = requests.post(sheet_url, json=payload, timeout=30, allow_redirects=True)

            if response.status_code in (200, 302):
                if hasattr(invoice, 'save') and hasattr(invoice, 'synced_to_sheet'):
                    invoice.synced_to_sheet = True
                    invoice.synced_at = datetime.now()
                    invoice.save(update_fields=['synced_to_sheet', 'synced_at'])
                else:
                    inv_id = invoice.get('id') if isinstance(invoice, dict) else getattr(invoice, 'id', None)
                    if inv_id:
                        from django.db import connection
                        with connection.cursor() as cursor:
                            cursor.execute(
                                "UPDATE invoices SET synced_to_sheet = 1, synced_at = NOW() WHERE id = %s",
                                [inv_id]
                            )
                logger.info(f"[InvoiceService] Synced invoice {invoice_number} to Google Sheet successfully.")
                return True
            else:
                logger.warning(
                    f"[InvoiceService] Google Sheet sync failed for {invoice_number}. "
                    f"Status code: {response.status_code}, response: {response.text[:200]}"
                )
                return False

        except Exception as e:
            logger.warning(f"[InvoiceService] Google Sheet sync exception: {e}")
            return False



# Singleton instance
invoice_service = InvoiceService()
