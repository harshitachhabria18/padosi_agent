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
import logging
import requests
from datetime import datetime
from django.conf import settings
from django.template.loader import render_to_string
from xhtml2pdf import pisa

from apps.agents.models import Agent, AgentSubscription, Invoice
from apps.home.models import SiteSetting

logger = logging.getLogger(__name__)


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

    def generate_from_subscription(self, agent: Agent, subscription: AgentSubscription) -> Invoice:
        """
        Generate, compile, save, and sync invoice for a completed payment.
        Matches Laravel's InvoiceService::generateFromSubscription.
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

            # 4. Generate unique invoice number: INV-YYYY-XXXXX
            invoice_number = self.generate_invoice_number()

            profile = getattr(agent, 'profile', None)

            # 5. Create Invoice Database record
            invoice = Invoice.objects.create(
                invoice_number=invoice_number,
                agent=agent,
                agent_name=agent.fullname,
                agent_email=agent.email,
                agent_mobile=agent.mobile,
                agent_address=profile.address if profile else '',
                agent_state=profile.state if profile else '',
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

            # 6. Render and generate PDF
            pdf_path = self.generate_pdf(invoice)
            if pdf_path:
                invoice.pdf_path = pdf_path
                invoice.save(update_fields=['pdf_path'])

            # 7. Sync to Google Sheets asynchronously/non-blocking
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
        Generate unique invoice number like INV-2026-00042.
        Uses select_for_update to lock rows and prevent duplicate generation.
        """
        year = datetime.now().year
        # Acquire a row lock on all invoices of this year to serialize count calculation
        invoices = Invoice.objects.filter(created_at__year=year).select_for_update()
        count = invoices.count() + 1
        
        while True:
            number = f"INV-{year}-{str(count).zfill(5)}"
            if not Invoice.objects.filter(invoice_number=number).exists():
                return number
            count += 1

    def calculate_discount_percent(self, agent: Agent, subscription: AgentSubscription, paid_amount: float) -> float:
        """
        Calculate discount % compared to the full plan price.
        Prices must come from DB only — no hardcoded fallbacks.
        """
        if paid_amount <= 1.00:
            return 99.9

        from apps.home.models import SiteSetting
        SiteSetting.flush_cache()
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
            # Prepare context for the template
            half_gst = round(float(invoice.gst_amount) / 2, 2)
            
            if invoice.plan_type == 'free_trial':
                plan_desc = "Trial listing on PadosiAgent platform"
            else:
                plan_desc = "Annual listing on PadosiAgent platform"

            item_name = invoice.plan_name
            if item_name and not item_name.startswith("Agent Subscription Fee"):
                item_name = f"Agent Subscription Fee ({item_name})"

            context = {
                'invoice': invoice,
                'items': [
                    {
                        'name': item_name,
                        'description': plan_desc,
                        'amount': invoice.base_amount,
                    }
                ],
                'is_gujarat': str(invoice.agent_state or '').strip().lower() == 'gujarat',
                'half_gst': half_gst,
            }

            # Render HTML to string
            html_string = render_to_string('pdf/invoice.html', context)

            # Define output path
            sub_folder = 'discount' if invoice.promo_code else 'no_discount'
            relative_dir = os.path.join('app', 'private', 'invoices', sub_folder)
            target_dir = os.path.join(settings.MEDIA_ROOT, relative_dir)
            os.makedirs(target_dir, exist_ok=True)

            filename = f"{invoice.invoice_number}.pdf"
            full_path = os.path.join(target_dir, filename)
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
                # Convert HTML to PDF using Pisa (xhtml2pdf)
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

    def sync_to_google_sheet(self, invoice: Invoice) -> None:
        """
        Synchronize invoice details to Google Sheet using Web App Script URL.
        Non-blocking operation.
        """
        try:
            sheet_url = SiteSetting.get_value('invoice_google_sheet_url')
            if not sheet_url:
                return

            payload = {
                'invoice_number': invoice.invoice_number,
                'date': invoice.created_at.strftime('%d/%m/%Y %H:%M') if invoice.created_at else datetime.now().strftime('%d/%m/%Y %H:%M'),
                'agent_id': invoice.agent.id,
                'agent_name': invoice.agent_name,
                'agent_email': invoice.agent_email,
                'agent_mobile': invoice.agent_mobile,
                'plan_name': invoice.plan_name,
                'base_amount': float(invoice.base_amount),
                'gst_amount': float(invoice.gst_amount),
                'total_amount': float(invoice.total_amount),
                'discount_percent': float(invoice.discount_percent),
                'discount_folder': Invoice.folder_label(invoice.discount_folder),
                'payment_id': invoice.razorpay_payment_id or 'N/A',
                'payment_status': invoice.payment_status,
                'promo_code': invoice.promo_code or '',
                'pdf_url': f"{settings.MEDIA_URL}app/private/{invoice.pdf_path}" if invoice.pdf_path else '',
            }

            # Call script endpoint with 10s timeout
            response = requests.post(sheet_url, json=payload, timeout=10)

            if response.status_code == 200:
                invoice.synced_to_sheet = True
                invoice.synced_at = datetime.now()
                invoice.save(update_fields=['synced_to_sheet', 'synced_at'])
                logger.info(f"[InvoiceService] Synced invoice {invoice.invoice_number} to Google Sheet successfully.")
            else:
                logger.warning(
                    f"[InvoiceService] Google Sheet sync failed for {invoice.invoice_number}. "
                    f"Status code: {response.status_code}"
                )

        except Exception as e:
            logger.warning(f"[InvoiceService] Google Sheet sync exception: {e}")


# Singleton instance
invoice_service = InvoiceService()
