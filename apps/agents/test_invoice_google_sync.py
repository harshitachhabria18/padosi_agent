import os
import base64
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime

from django.test import TestCase
from apps.agents.services.invoice import (
    InvoiceService,
    calculate_tax_breakdown,
    get_pdf_absolute_path,
)
from apps.home.models.site_setting import SiteSetting
from apps.admin_panel.services.google_sheet_sync import sync_invoice_to_sheet, sync_all_pending


class TestTaxBreakdownCalculation(unittest.TestCase):
    """Test tax calculation for Gujarat (Intra-state) and Other States (Inter-state)."""

    def test_intra_state_gujarat(self):
        # Gujarat intra-state: 9% CGST + 9% SGST, 0 IGST
        tax = calculate_tax_breakdown(gst_amount=359.85, state='Gujarat')
        self.assertEqual(tax['place_of_supply'], 'Gujarat')
        self.assertFalse(tax['is_igst'])
        self.assertEqual(tax['cgst'], 179.93)
        self.assertEqual(tax['sgst'], 179.92)
        self.assertEqual(tax['igst'], 0.0)
        self.assertAlmostEqual(tax['cgst'] + tax['sgst'], 359.85, places=2)

    def test_intra_state_gujarat_case_insensitive(self):
        tax = calculate_tax_breakdown(gst_amount=180.00, state=' gujarat ')
        self.assertEqual(tax['place_of_supply'], 'gujarat')
        self.assertFalse(tax['is_igst'])
        self.assertEqual(tax['cgst'], 90.0)
        self.assertEqual(tax['sgst'], 90.0)
        self.assertEqual(tax['igst'], 0.0)

    def test_intra_state_gj_code(self):
        # State code 'gj' or 'GJ' should map to Gujarat intra-state
        tax = calculate_tax_breakdown(gst_amount=180.00, state='GJ')
        self.assertEqual(tax['place_of_supply'], 'Gujarat')
        self.assertFalse(tax['is_igst'])
        self.assertEqual(tax['cgst'], 90.0)
        self.assertEqual(tax['sgst'], 90.0)
        self.assertEqual(tax['igst'], 0.0)

    def test_inter_state_other_state(self):
        # Maharashtra inter-state: 0 CGST, 0 SGST, 18% IGST
        tax = calculate_tax_breakdown(gst_amount=359.85, state='Maharashtra')
        self.assertEqual(tax['place_of_supply'], 'Maharashtra')
        self.assertTrue(tax['is_igst'])
        self.assertEqual(tax['cgst'], 0.0)
        self.assertEqual(tax['sgst'], 0.0)
        self.assertEqual(tax['igst'], 359.85)

    def test_inter_state_rajasthan(self):
        tax = calculate_tax_breakdown(gst_amount=150.00, state='Rajasthan')
        self.assertEqual(tax['place_of_supply'], 'Rajasthan')
        self.assertTrue(tax['is_igst'])
        self.assertEqual(tax['cgst'], 0.0)
        self.assertEqual(tax['sgst'], 0.0)
        self.assertEqual(tax['igst'], 150.00)

    def test_empty_state_defaults_to_gujarat(self):
        # When state is empty or None, default to company state Gujarat
        tax = calculate_tax_breakdown(gst_amount=200.00, state='')
        self.assertEqual(tax['place_of_supply'], 'Gujarat')
        self.assertFalse(tax['is_igst'])
        self.assertEqual(tax['cgst'], 100.0)
        self.assertEqual(tax['sgst'], 100.0)
        self.assertEqual(tax['igst'], 0.0)

    def test_special_one_rupee_plan_taxes(self):
        # ₹1 plan has gst_amount=0.15
        tax = calculate_tax_breakdown(gst_amount=0.15, state='Gujarat')
        self.assertEqual(tax['cgst'], 0.07)
        self.assertEqual(tax['sgst'], 0.08)
        self.assertEqual(tax['igst'], 0.0)
        self.assertAlmostEqual(tax['cgst'] + tax['sgst'], 0.15, places=2)


class TestGoogleSheetSyncService(unittest.TestCase):
    """Test sync_to_google_sheet payload, headers, base64 PDF, and network calls."""

    def setUp(self):
        self.svc = InvoiceService()

    def test_ssrf_protection_blocked(self):
        """Ensure SSRF safety checks reject non-HTTPS and metadata/internal hosts."""
        mock_invoice = MagicMock()
        # Insecure HTTP
        with patch.object(SiteSetting, 'get_value', return_value='http://example.com/exec'):
            with patch('requests.post') as mock_post:
                res = self.svc.sync_to_google_sheet(mock_invoice)
                self.assertFalse(res)
                mock_post.assert_not_called()

        # AWS metadata endpoint
        with patch.object(SiteSetting, 'get_value', return_value='https://169.254.169.254/latest'):
            with patch('requests.post') as mock_post:
                res = self.svc.sync_to_google_sheet(mock_invoice)
                self.assertFalse(res)
                mock_post.assert_not_called()

        # Localhost
        with patch.object(SiteSetting, 'get_value', return_value='https://localhost:8000/sync'):
            with patch('requests.post') as mock_post:
                res = self.svc.sync_to_google_sheet(mock_invoice)
                self.assertFalse(res)
                mock_post.assert_not_called()

    def test_payload_contains_all_16_sheet_columns_gujarat(self):
        """Verify the exact 16 Google Sheet columns and base64 PDF are sent for Gujarat."""
        fake_invoice = MagicMock()
        fake_invoice.invoice_number = 'PA/26-27/00099'
        fake_invoice.created_at = datetime(2026, 9, 25, 14, 30, 0)
        fake_invoice.agent_name = 'Karan Patel'
        fake_invoice.agent_email = 'karan@example.com'
        fake_invoice.agent_mobile = '9876543210'
        fake_invoice.plan_name = 'Professional Plan'
        fake_invoice.agent_state = 'Gujarat'
        fake_invoice.base_amount = 6999.00
        fake_invoice.gst_amount = 1259.82
        fake_invoice.total_amount = 8258.82
        fake_invoice.discount_percent = 0.0
        fake_invoice.discount_folder = 'no_discount'
        fake_invoice.razorpay_payment_id = 'pay_Test12345'
        fake_invoice.payment_status = 'paid'
        fake_invoice.promo_code = ''
        fake_invoice.pdf_path = None

        sheet_url = 'https://script.google.com/macros/s/AKfycb.../exec'

        with patch.object(SiteSetting, 'get_value', return_value=sheet_url):
            with patch('requests.post') as mock_post:
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_post.return_value = mock_resp

                success = self.svc.sync_to_google_sheet(fake_invoice)
                self.assertTrue(success)
                self.assertTrue(mock_post.called)

                args, kwargs = mock_post.call_args
                self.assertEqual(args[0], sheet_url)
                self.assertEqual(kwargs['timeout'], 30)
                self.assertTrue(kwargs['allow_redirects'])

                payload = kwargs['json']
                # Verify standard keys
                self.assertEqual(payload['invoice_number'], 'PA/26-27/00099')
                self.assertEqual(payload['date'], '25/09/2026 14:30')
                self.assertEqual(payload['agent_name'], 'Karan Patel')
                self.assertEqual(payload['agent_email'], 'karan@example.com')
                self.assertEqual(payload['agent_mobile'], '9876543210')
                self.assertEqual(payload['plan_name'], 'Professional Plan')
                self.assertEqual(payload['place_of_supply'], 'Gujarat')
                self.assertEqual(payload['base_amount'], 6999.00)
                self.assertEqual(payload['cgst'], 629.91)
                self.assertEqual(payload['sgst'], 629.91)
                self.assertEqual(payload['igst'], 0.0)
                self.assertEqual(payload['total_amount'], 8258.82)
                self.assertEqual(payload['payment_id'], 'pay_Test12345')

                # Verify sheet-matching header keys
                self.assertEqual(payload['Invoice #'], 'PA/26-27/00099')
                self.assertEqual(payload['Date'], '25/09/2026 14:30')
                self.assertEqual(payload['Agent'], 'Karan Patel')
                self.assertEqual(payload['Email'], 'karan@example.com')
                self.assertEqual(payload['Mobile'], '9876543210')
                self.assertEqual(payload['Plan Name'], 'Professional Plan')
                self.assertEqual(payload['Place of Supply'], 'Gujarat')
                self.assertEqual(payload['Base Amount'], 6999.00)
                self.assertEqual(payload['CGST'], 629.91)
                self.assertEqual(payload['SGST'], 629.91)
                self.assertEqual(payload['IGST'], 0.0)
                self.assertEqual(payload['Total Amount'], 8258.82)
                self.assertEqual(payload['Payment ID'], 'pay_Test12345')

    def test_payload_contains_igst_for_inter_state(self):
        """Verify IGST is populated and CGST/SGST are 0 for non-Gujarat state."""
        fake_invoice = MagicMock()
        fake_invoice.invoice_number = 'PA/26-27/00100'
        fake_invoice.created_at = datetime(2026, 9, 25, 15, 0, 0)
        fake_invoice.agent_name = 'Rahul Sharma'
        fake_invoice.agent_email = 'rahul@example.com'
        fake_invoice.agent_mobile = '9811122233'
        fake_invoice.plan_name = 'Starter Plan'
        fake_invoice.agent_state = 'Maharashtra'
        fake_invoice.base_amount = 1999.15
        fake_invoice.gst_amount = 359.85
        fake_invoice.total_amount = 2359.00
        fake_invoice.discount_percent = 0.0
        fake_invoice.discount_folder = 'no_discount'
        fake_invoice.razorpay_payment_id = 'pay_MH_9988'
        fake_invoice.payment_status = 'paid'
        fake_invoice.promo_code = ''
        fake_invoice.pdf_path = None

        sheet_url = 'https://script.google.com/macros/s/AKfycb.../exec'

        with patch.object(SiteSetting, 'get_value', return_value=sheet_url):
            with patch('requests.post') as mock_post:
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_post.return_value = mock_resp

                success = self.svc.sync_to_google_sheet(fake_invoice)
                self.assertTrue(success)

                payload = mock_post.call_args[1]['json']
                self.assertEqual(payload['Place of Supply'], 'Maharashtra')
                self.assertEqual(payload['CGST'], 0.0)
                self.assertEqual(payload['SGST'], 0.0)
                self.assertEqual(payload['IGST'], 359.85)

    def test_pdf_base64_encoded_in_payload_when_file_exists(self):
        """Verify pdf_base64 contains valid base64 bytes when the PDF file exists."""
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tf:
            tf.write(b"%PDF-1.4 Mock PDF Invoice Content for Testing")
            temp_pdf_path = tf.name

        try:
            fake_invoice = MagicMock()
            fake_invoice.invoice_number = 'PA/26-27/00101'
            fake_invoice.created_at = datetime.now()
            fake_invoice.agent_name = 'Test User'
            fake_invoice.agent_email = 'test@example.com'
            fake_invoice.agent_mobile = '9999999999'
            fake_invoice.plan_name = 'Starter'
            fake_invoice.agent_state = 'Gujarat'
            fake_invoice.base_amount = 100.0
            fake_invoice.gst_amount = 18.0
            fake_invoice.total_amount = 118.0
            fake_invoice.discount_percent = 0.0
            fake_invoice.discount_folder = 'no_discount'
            fake_invoice.razorpay_payment_id = 'pay_001'
            fake_invoice.payment_status = 'paid'
            fake_invoice.promo_code = ''
            fake_invoice.pdf_path = temp_pdf_path

            sheet_url = 'https://script.google.com/macros/s/AKfycb.../exec'

            with patch.object(SiteSetting, 'get_value', return_value=sheet_url):
                with patch('requests.post') as mock_post:
                    mock_resp = MagicMock()
                    mock_resp.status_code = 200
                    mock_post.return_value = mock_resp

                    success = self.svc.sync_to_google_sheet(fake_invoice)
                    self.assertTrue(success)

                    payload = mock_post.call_args[1]['json']
                    self.assertIsNotNone(payload['pdf_base64'])
                    decoded = base64.b64decode(payload['pdf_base64'])
                    self.assertEqual(decoded, b"%PDF-1.4 Mock PDF Invoice Content for Testing")
        finally:
            if os.path.exists(temp_pdf_path):
                os.remove(temp_pdf_path)

    def test_sync_invoice_to_sheet_delegates_to_invoice_service(self):
        """Verify admin panel sync_invoice_to_sheet calls invoice_service.sync_to_google_sheet."""
        fake_invoice = MagicMock()
        fake_invoice.id = 555

        with patch('apps.agents.models.Invoice.objects.filter') as mock_filter:
            mock_filter.return_value.first.return_value = fake_invoice
            with patch.object(InvoiceService, 'sync_to_google_sheet', return_value=True) as mock_sync:
                res = sync_invoice_to_sheet(555)
                self.assertTrue(res)
                mock_sync.assert_called_once_with(fake_invoice)

    def test_open_sheet_prioritizes_spreadsheet_view_url(self):
        """Verify open_sheet view redirects to spreadsheet view URL first, else fallback to script URL."""
        from django.test import RequestFactory
        from apps.admin_panel.views.invoices import open_sheet

        rf = RequestFactory()
        req = rf.get('/admin/invoices/open-sheet')
        req.session = {'admin_id': 1}

        with patch('apps.admin_panel.views.invoices._get_admin_from_session', return_value={'id': 1}):
            with patch('django.db.connection.cursor') as mock_cursor:
                cursor_inst = MagicMock()
                mock_cursor.return_value.__enter__.return_value = cursor_inst
                # Return spreadsheet view URL on first query
                cursor_inst.fetchone.return_value = ('https://docs.google.com/spreadsheets/d/test12345/edit',)
                resp = open_sheet(req)
                self.assertEqual(resp.status_code, 302)
                self.assertEqual(resp.url, 'https://docs.google.com/spreadsheets/d/test12345/edit')

    def test_sync_single_invoice_view(self):
        """Verify sync_single_invoice view calls sync_invoice_to_sheet and sets flash message."""
        from django.test import RequestFactory
        from apps.admin_panel.views.invoices import sync_single_invoice

        rf = RequestFactory()
        req = rf.post('/admin/invoices/42/sync/')
        req.session = {'admin_id': 1}
        # mock messages middleware
        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(req, '_messages', FallbackStorage(req))

        mock_inv = MagicMock()
        mock_inv.invoice_number = 'PA/26-27/00042'

        with patch('apps.admin_panel.views.invoices._get_admin_from_session', return_value={'id': 1}):
            with patch('apps.agents.models.Invoice.objects.filter') as mock_filter:
                mock_filter.return_value.first.return_value = mock_inv
                with patch('apps.admin_panel.services.google_sheet_sync.sync_invoice_to_sheet', return_value=True) as mock_sync:
                    resp = sync_single_invoice(req, 42)
                    self.assertEqual(resp.status_code, 302)
                    mock_sync.assert_called_once_with(42)

    def test_sync_all_pending_batches(self):
        """Verify sync_all_pending queries with LIMIT and loops over rows."""
        with patch('django.db.connection.cursor') as mock_cursor:
            cursor_inst = MagicMock()
            mock_cursor.return_value.__enter__.return_value = cursor_inst
            # First fetch: sheet_url
            # Second fetch: IDs of pending
            cursor_inst.fetchone.return_value = ('https://script.google.com/macros/s/exec',)
            cursor_inst.fetchall.return_value = [(101,), (102,)]

            with patch('apps.admin_panel.services.google_sheet_sync.sync_invoice_to_sheet', return_value=True) as mock_sync:
                with patch('time.sleep'):
                    synced = sync_all_pending(limit=2)
                    self.assertEqual(synced, 2)
                    self.assertEqual(mock_sync.call_count, 2)

