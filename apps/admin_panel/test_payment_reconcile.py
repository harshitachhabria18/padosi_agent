import json
import unittest
from unittest.mock import patch, MagicMock
from decimal import Decimal
from django.test import RequestFactory
from django.contrib.auth.models import AnonymousUser

from apps.admin_panel.views.payment_reconcile import (
    payment_reconcile_dashboard,
    reconcile_inspect_payment,
    reconcile_execute_payment,
    _plan_details_from_amount,
)


class TestPlanDetailsFromAmount(unittest.TestCase):
    def test_trial_plan_amount(self):
        slug, name = _plan_details_from_amount(1.00)
        self.assertEqual(slug, 'free_trial')
        self.assertEqual(name, 'Trial Plan')

    def test_starter_plan_amount(self):
        slug, name = _plan_details_from_amount(2359.00)
        self.assertEqual(slug, 'starter')
        self.assertIn('Starter', name)

    def test_professional_plan_amount(self):
        slug, name = _plan_details_from_amount(5899.00)
        self.assertEqual(slug, 'professional')
        self.assertIn('Professional', name)

    def test_exclusive_plan_amount(self):
        slug, name = _plan_details_from_amount(10000.00)
        self.assertEqual(slug, 'exclusive')
        self.assertIn('Exclusive', name)

    def test_override_from_notes(self):
        slug, name = _plan_details_from_amount(2359.00, {'plan_type': 'exclusive', 'plan_name': 'Exclusive VIP'})
        self.assertEqual(slug, 'exclusive')
        self.assertEqual(name, 'Exclusive VIP')


class TestPaymentReconcileViews(unittest.TestCase):
    def setUp(self):
        self.rf = RequestFactory()

    def test_dashboard_unauthorized(self):
        req = self.rf.get('/admin/payments/reconcile/')
        with patch('apps.admin_panel.views.payment_reconcile._get_admin_from_session', return_value=None):
            resp = payment_reconcile_dashboard(req)
            self.assertEqual(resp.status_code, 302)
            self.assertEqual(resp.url, '/admin/login/')

    def test_inspect_unauthorized(self):
        req = self.rf.post('/admin/payments/reconcile/inspect/', data=json.dumps({'query': 'pay_123'}), content_type='application/json')
        with patch('apps.admin_panel.views.payment_reconcile._get_admin_from_session', return_value=None):
            resp = reconcile_inspect_payment(req)
            self.assertEqual(resp.status_code, 403)

    def test_inspect_payment_id_success(self):
        req = self.rf.post(
            '/admin/payments/reconcile/inspect/',
            data=json.dumps({'query': 'pay_ABC12345'}),
            content_type='application/json'
        )
        fake_payment = {
            'id': 'pay_ABC12345',
            'order_id': 'order_XYZ999',
            'amount': 235900,
            'status': 'captured',
            'email': 'karan@example.com',
            'contact': '+919876543210',
            'method': 'upi',
            'notes': {'plan_type': 'starter'},
        }

        mock_client = MagicMock()
        mock_client.payment.fetch.return_value = fake_payment

        with patch('apps.admin_panel.views.payment_reconcile._get_admin_from_session', return_value={'id': 1}):
            with patch('apps.admin_panel.views.payment_reconcile.razorpay_client', return_value=mock_client):
                with patch('apps.agents.models.Agent.objects.filter') as mock_agent_filter:
                    mock_agent_filter.return_value.first.return_value = None
                    with patch('apps.agents.models.AgentSubscription.objects.filter') as mock_sub_filter:
                        mock_sub_filter.return_value.first.return_value = None
                        with patch('apps.agents.models.AgentDraft.objects.filter') as mock_draft_filter:
                            mock_draft_filter.return_value.first.return_value = None
                            with patch('apps.agents.models.Invoice.objects.filter') as mock_inv_filter:
                                mock_inv_filter.return_value.first.return_value = None

                                resp = reconcile_inspect_payment(req)
                                self.assertEqual(resp.status_code, 200)
                                data = json.loads(resp.content)
                                self.assertTrue(data['success'])
                                self.assertTrue(data['has_razorpay'])
                                self.assertEqual(data['razorpay']['payment_id'], 'pay_ABC12345')
                                self.assertEqual(data['razorpay']['amount_rupees'], 2359.00)
                                self.assertEqual(data['razorpay']['inferred_plan_type'], 'starter')

    def test_execute_reconcile_existing_agent(self):
        req = self.rf.post(
            '/admin/payments/reconcile/execute/',
            data=json.dumps({
                'payment_id': 'pay_TEST999',
                'order_id': 'order_TEST999',
                'email': 'existing@example.com',
                'plan_type': 'starter',
                'plan_name': "Starter's Plan",
            }),
            content_type='application/json'
        )

        fake_payment = {
            'id': 'pay_TEST999',
            'order_id': 'order_TEST999',
            'amount': 235900,
            'status': 'captured',
            'email': 'existing@example.com',
            'contact': '+919999988888',
        }
        mock_client = MagicMock()
        mock_client.payment.fetch.return_value = fake_payment

        mock_agent = MagicMock()
        mock_agent.id = 77
        mock_agent.fullname = 'Existing Agent'
        mock_agent.email = 'existing@example.com'

        mock_sub = MagicMock()
        mock_sub.id = 88
        mock_sub.agent = mock_agent

        mock_invoice = MagicMock()
        mock_invoice.invoice_number = 'PA/26-27/00077'
        mock_invoice.synced_to_sheet = True

        with patch('apps.admin_panel.views.payment_reconcile._get_admin_from_session', return_value={'id': 1}):
            with patch('apps.admin_panel.views.payment_reconcile.razorpay_client', return_value=mock_client):
                with patch('apps.agents.models.Agent.objects.filter') as mock_agent_filter:
                    mock_agent_filter.return_value.first.return_value = mock_agent
                    with patch('apps.agents.models.AgentSubscription.objects.filter') as mock_sub_filter:
                        mock_sub_filter.return_value.order_by.return_value.first.return_value = mock_sub
                        with patch('apps.admin_panel.views.payment_reconcile.create_or_link_django_user'):
                            with patch('apps.admin_panel.views.payment_reconcile.fulfill_invoice_and_welcome', return_value=mock_invoice):
                                resp = reconcile_execute_payment(req)
                                self.assertEqual(resp.status_code, 200)
                                data = json.loads(resp.content)
                                self.assertTrue(data['success'])
                                self.assertEqual(data['invoice_number'], 'PA/26-27/00077')
                                self.assertEqual(data['agent_name'], 'Existing Agent')

    def test_inspect_order_id_with_messy_input(self):
        req = self.rf.post(
            '/admin/payments/reconcile/inspect/',
            data=json.dumps({'query': 'Order_id:-order_TgAtfYxCS12pG6'}),
            content_type='application/json'
        )
        fake_order = {
            'id': 'order_TgAtfYxCS12pG6',
            'amount': 235900,
            'status': 'paid',
            'receipt': 'agent_draft_99_1790318572',
        }
        fake_payment = {
            'id': 'pay_TgAtr0PKkdyKnz',
            'order_id': 'order_TgAtfYxCS12pG6',
            'amount': 235900,
            'status': 'captured',
            'email': 'yashwantsinghmoral@gmail.com',
            'contact': '+918521514171',
            'method': 'upi',
            'notes': [],
        }

        mock_client = MagicMock()
        mock_client.order.fetch.return_value = fake_order
        mock_client.order.payments.return_value = {'items': [fake_payment]}

        mock_draft = MagicMock()
        mock_draft.id = 99
        mock_draft.fullname = 'Yashwant Singh Moral'
        mock_draft.email = 'yashwantsinghmoral@gmail.com'
        mock_draft.mobile = '+918521514171'
        mock_draft.registration_step = 2

        with patch('apps.admin_panel.views.payment_reconcile._get_admin_from_session', return_value={'id': 1}):
            with patch('apps.admin_panel.views.payment_reconcile.razorpay_client', return_value=mock_client):
                with patch('apps.agents.models.Agent.objects.filter') as mock_agent_filter:
                    mock_agent_filter.return_value.first.return_value = None
                    with patch('apps.agents.models.AgentSubscription.objects.filter') as mock_sub_filter:
                        mock_sub_filter.return_value.first.return_value = None
                        with patch('apps.agents.models.AgentDraft.objects.filter') as mock_draft_filter:
                            mock_draft_filter.return_value.first.return_value = mock_draft
                            with patch('apps.agents.models.Invoice.objects.filter') as mock_inv_filter:
                                mock_inv_filter.return_value.first.return_value = None

                                resp = reconcile_inspect_payment(req)
                                self.assertEqual(resp.status_code, 200)
                                data = json.loads(resp.content)
                                self.assertTrue(data['success'])
                                self.assertTrue(data['has_razorpay'])
                                self.assertEqual(data['razorpay']['order_id'], 'order_TgAtfYxCS12pG6')
                                self.assertEqual(data['razorpay']['payment_id'], 'pay_TgAtr0PKkdyKnz')
                                self.assertEqual(data['razorpay']['email'], 'yashwantsinghmoral@gmail.com')
                                self.assertEqual(data['razorpay']['amount_rupees'], 2359.00)
                                self.assertEqual(data['db_match']['draft']['id'], 99)
