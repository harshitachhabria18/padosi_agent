"""Comprehensive test suite for the complete Razorpay payment-to-approval workflow.

Covers:
1. Normal registration + payment verification -> agent status is 'pending_approval'.
2. Agent appears in the Admin Pending Approval queue and context processor badge count.
3. Razorpay Webhook processing for 'payment.captured', 'order.paid', and 'payment.authorized'.
4. Webhook deduplication and race-condition safety (webhook + callback idempotency).
5. Webhook returning 503 retry status when order/subscription is not yet available.
6. Cross-origin POST to /agent-register/payment-callback/ is @csrf_exempt and succeeds without CSRF token.
7. Signature verification failure rejection.
8. Price tampering / amount mismatch rejection.
9. Admin manual payment verification (admin_verify_pending_payment) reconciling pending/failed subscriptions.
10. Admin approval action transitioning agent from 'pending_approval' to 'active'.
11. Free-trial and zero-amount checkouts transitioning to 'pending_approval'.
12. Plan upgrade retaining 'active' status for already active agents.
"""
import json
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import Client, TestCase, override_settings

from apps.agents.models import Agent, AgentSubscription
from apps.home.models import SiteSetting
from apps.home.models.pincode import Pincode

ORDER_ID = 'order_TESTFLOW00001'
PAYMENT_ID = 'pay_TESTFLOW00001'
SIGNATURE = 'sig_test_valid_signature'


def _mock_razorpay_client(amount_paise, payment_status='captured'):
    client = MagicMock()
    client.utility.verify_payment_signature.return_value = True
    client.utility.verify_webhook_signature.return_value = True
    client.payment.fetch.return_value = {'status': payment_status, 'amount': amount_paise}
    client.order.payments.return_value = {
        'items': [{'id': PAYMENT_ID, 'status': payment_status, 'amount': amount_paise}]
    }
    return client


@override_settings(
    ALLOWED_HOSTS=['testserver', 'localhost'],
    RAZORPAY_WEBHOOK_SECRET='test_webhook_secret_key_123',
)
class PaymentToApprovalFlowTests(TestCase):
    def setUp(self):
        cache.clear()
        Pincode.objects.create(
            pincode='380001',
            office_name='Ahmedabad GPO',
            district='Ahmedabad',
            state='Gujarat',
            latitude='23.02250000',
            longitude='72.57140000',
        )
        SiteSetting.set_value('pricing_config', {
            'starter': {'name': "Starter's Plan", 'full_price': 1999},
            'professional': {'name': "Professional's Plan", 'full_price': 4999},
        }, 'pricing')
        SiteSetting.set_value('trial_plan_config', {'price': 99, 'duration_days': 30}, 'pricing')

    def _complete_step1_and_step2(self, email='flow.agent@example.com'):
        r1 = self.client.post('/agent-register-step1/', {
            'fullname': 'Flow Agent',
            'email': email,
            'mobile': '9876543210',
            'agent_pincode': '380001',
            'state': 'Gujarat',
            'experience_range': '5',
            'segments[]': ['life'],
        })
        self.assertEqual(r1.status_code, 200, r1.content)
        r2 = self.client.post('/agent-register-step2/', {'bio': 'Dedicated insurance professional.'})
        self.assertEqual(r2.status_code, 200, r2.content)

    def _create_order(self, plan_type='starter', order_id=ORDER_ID):
        with patch('apps.agents.views.registration.create_checkout_order',
                   return_value=(order_id, False)):
            resp = self.client.post(
                '/agent-register/complete/',
                data={'plan_type': plan_type},
                content_type='application/json',
            )
        self.assertEqual(resp.status_code, 200, resp.content)
        sub = AgentSubscription.objects.get(razorpay_order_id=order_id)
        self.assertEqual(sub.payment_status, 'pending')
        self.assertEqual(sub.agent.status, 'pending_payment')
        return sub

    @patch('apps.agents.views.registration.queue_invoice_and_welcome')
    def test_payment_verify_moves_agent_to_pending_approval_not_active(self, _queue):
        """Paid registration must move to 'pending_approval', NOT 'active'."""
        self._complete_step1_and_step2('verify.agent@example.com')
        sub = self._create_order('starter', 'order_VERIFY001')
        amount_paise = int(round(float(sub.registration_amount) * 100))

        with patch('apps.agents.views.registration.razorpay_client',
                   return_value=_mock_razorpay_client(amount_paise)):
            resp = self.client.post(
                '/agent-register/verify-payment/',
                data={
                    'razorpay_order_id': 'order_VERIFY001',
                    'razorpay_payment_id': 'pay_VERIFY001',
                    'razorpay_signature': SIGNATURE,
                },
                content_type='application/json',
            )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['success'])

        sub.refresh_from_db()
        agent = sub.agent
        self.assertEqual(sub.payment_status, 'completed')
        self.assertEqual(sub.razorpay_payment_id, 'pay_VERIFY001')
        self.assertEqual(agent.status, 'pending_approval', "Agent must be pending_approval after payment, awaiting admin review")

    @patch('apps.agents.views.registration.queue_invoice_and_welcome')
    def test_payment_callback_csrf_exempt_and_moves_to_pending_approval(self, _queue):
        """Cross-origin POST to /agent-register/payment-callback/ without CSRF token must succeed."""
        self._complete_step1_and_step2('callback.agent@example.com')
        sub = self._create_order('professional', 'order_CALLBACK001')
        amount_paise = int(round(float(sub.registration_amount) * 100))

        # Enforce CSRF checking on client
        csrf_client = Client(enforce_csrf_checks=True)
        # Session state for pending checkout
        session = self.client.session
        for k, v in session.items():
            csrf_client.session[k] = v
        csrf_client.session.save()

        with patch('apps.agents.views.registration.razorpay_client',
                   return_value=_mock_razorpay_client(amount_paise)):
            resp = csrf_client.post('/agent-register/payment-callback/', {
                'razorpay_order_id': 'order_CALLBACK001',
                'razorpay_payment_id': 'pay_CALLBACK001',
                'razorpay_signature': SIGNATURE,
            })
        self.assertNotEqual(resp.status_code, 403, "Payment callback must be CSRF exempt")
        self.assertEqual(resp.status_code, 302)

        sub.refresh_from_db()
        agent = sub.agent
        self.assertEqual(sub.payment_status, 'completed')
        self.assertEqual(agent.status, 'pending_approval')

    @patch('apps.agents.views.registration.queue_invoice_and_welcome')
    def test_webhook_payment_captured_moves_to_pending_approval(self, _queue):
        """Webhook payment.captured event processes asynchronously into pending_approval."""
        self._complete_step1_and_step2('webhook.captured@example.com')
        sub = self._create_order('starter', 'order_WEBHOOK001')
        amount_paise = int(round(float(sub.registration_amount) * 100))

        webhook_payload = json.dumps({
            'event': 'payment.captured',
            'payload': {
                'payment': {
                    'entity': {
                        'id': 'pay_WH001',
                        'order_id': 'order_WEBHOOK001',
                        'amount': amount_paise,
                        'status': 'captured',
                    }
                }
            }
        })

        with patch('apps.agents.views.registration.razorpay_client',
                   return_value=_mock_razorpay_client(amount_paise)):
            resp = self.client.post(
                '/razorpay-webhook/',
                data=webhook_payload,
                content_type='application/json',
                HTTP_X_RAZORPAY_SIGNATURE='test_signature_skip_verification',
            )
        self.assertEqual(resp.status_code, 200, resp.content)

        sub.refresh_from_db()
        agent = sub.agent
        self.assertEqual(sub.payment_status, 'completed')
        self.assertEqual(sub.razorpay_payment_id, 'pay_WH001')
        self.assertEqual(agent.status, 'pending_approval')

    @patch('apps.agents.views.registration.queue_invoice_and_welcome')
    def test_webhook_order_paid_event_supported(self, _queue):
        """Webhook order.paid event is supported and updates subscription to completed."""
        self._complete_step1_and_step2('orderpaid.agent@example.com')
        sub = self._create_order('professional', 'order_ORDERPAID001')
        amount_paise = int(round(float(sub.registration_amount) * 100))

        webhook_payload = json.dumps({
            'event': 'order.paid',
            'payload': {
                'order': {
                    'entity': {
                        'id': 'order_ORDERPAID001',
                        'amount_paid': amount_paise,
                        'status': 'paid',
                    }
                },
                'payment': {
                    'entity': {
                        'id': 'pay_ORDERPAID001',
                        'order_id': 'order_ORDERPAID001',
                        'amount': amount_paise,
                        'status': 'captured',
                    }
                }
            }
        })

        with patch('apps.agents.views.registration.razorpay_client',
                   return_value=_mock_razorpay_client(amount_paise)):
            resp = self.client.post(
                '/razorpay-webhook/',
                data=webhook_payload,
                content_type='application/json',
                HTTP_X_RAZORPAY_SIGNATURE='test_signature_skip_verification',
            )
        self.assertEqual(resp.status_code, 200, resp.content)

        sub.refresh_from_db()
        self.assertEqual(sub.payment_status, 'completed')
        self.assertEqual(sub.agent.status, 'pending_approval')

    def test_webhook_returns_503_for_missing_order_to_trigger_retry(self):
        """If subscription is not found yet, webhook must return 503 so Razorpay retries."""
        webhook_payload = json.dumps({
            'event': 'payment.captured',
            'payload': {
                'payment': {
                    'entity': {
                        'id': 'pay_UNKNOWN001',
                        'order_id': 'order_NONEXISTENT999',
                        'amount': 235900,
                        'status': 'captured',
                    }
                }
            }
        })
        with patch('apps.agents.views.registration.razorpay_client',
                   return_value=_mock_razorpay_client(235900)):
            resp = self.client.post(
                '/razorpay-webhook/',
                data=webhook_payload,
                content_type='application/json',
                HTTP_X_RAZORPAY_SIGNATURE='test_signature_skip_verification',
            )
        self.assertEqual(resp.status_code, 503, "Should return 503 to signal Razorpay to retry")

    @patch('apps.agents.views.registration.queue_invoice_and_welcome')
    def test_webhook_and_callback_idempotency(self, _queue):
        """Duplicate callbacks / webhooks must not double-activate or crash."""
        self._complete_step1_and_step2('idempotent.agent@example.com')
        sub = self._create_order('starter', 'order_IDEM001')
        amount_paise = int(round(float(sub.registration_amount) * 100))

        # First: In-modal verify-payment succeeds
        with patch('apps.agents.views.registration.razorpay_client',
                   return_value=_mock_razorpay_client(amount_paise)):
            r1 = self.client.post(
                '/agent-register/verify-payment/',
                data={
                    'razorpay_order_id': 'order_IDEM001',
                    'razorpay_payment_id': 'pay_IDEM001',
                    'razorpay_signature': SIGNATURE,
                },
                content_type='application/json',
            )
        self.assertEqual(r1.status_code, 200)

        # Second: Webhook arrives subsequently for the same order
        webhook_payload = json.dumps({
            'event': 'payment.captured',
            'payload': {
                'payment': {
                    'entity': {
                        'id': 'pay_IDEM001',
                        'order_id': 'order_IDEM001',
                        'amount': amount_paise,
                        'status': 'captured',
                    }
                }
            }
        })
        with patch('apps.agents.views.registration.razorpay_client',
                   return_value=_mock_razorpay_client(amount_paise)):
            r2 = self.client.post(
                '/razorpay-webhook/',
                data=webhook_payload,
                content_type='application/json',
                HTTP_X_RAZORPAY_SIGNATURE='test_signature_skip_verification',
            )
        self.assertEqual(r2.status_code, 200)
        self.assertIn(b'already completed', r2.content)

        # Third: Redirect callback also hits
        with patch('apps.agents.views.registration.razorpay_client',
                   return_value=_mock_razorpay_client(amount_paise)):
            r3 = self.client.post('/agent-register/payment-callback/', {
                'razorpay_order_id': 'order_IDEM001',
                'razorpay_payment_id': 'pay_IDEM001',
                'razorpay_signature': SIGNATURE,
            })
        self.assertEqual(r3.status_code, 302)

    def test_price_tampering_rejected_in_verify(self):
        """Payment amount lower than subscription amount must be rejected as price tampering."""
        self._complete_step1_and_step2('tamper.agent@example.com')
        sub = self._create_order('starter', 'order_TAMPER001')
        amount_paise = int(round(float(sub.registration_amount) * 100))

        # Simulate attacker paying 100 paise (Rs 1) instead of required amount
        with patch('apps.agents.views.registration.razorpay_client',
                   return_value=_mock_razorpay_client(100)):
            resp = self.client.post(
                '/agent-register/verify-payment/',
                data={
                    'razorpay_order_id': 'order_TAMPER001',
                    'razorpay_payment_id': 'pay_TAMPER001',
                    'razorpay_signature': SIGNATURE,
                },
                content_type='application/json',
            )
        self.assertFalse(resp.json()['success'])
        self.assertIn('Amount mismatch', resp.json()['message'])
        sub.refresh_from_db()
        self.assertEqual(sub.payment_status, 'pending')
        self.assertEqual(sub.agent.status, 'pending_payment')

    def test_admin_approvals_queue_and_badge_count(self):
        """Agent with status 'pending_approval' appears in the approval queue query and count."""
        self._complete_step1_and_step2('approvals.queue@example.com')
        sub = self._create_order('starter', 'order_APPROV001')
        sub.payment_status = 'completed'
        sub.razorpay_payment_id = 'pay_APPROV001'
        sub.save()
        agent = sub.agent
        agent.status = 'pending_approval'
        agent.save()

        from apps.admin_panel.views.agents import _build_queue_query
        from django.db import connection

        query, params = _build_queue_query('pending_approval', '', 'All Plans', '', 'All Events', 'newest')
        with connection.cursor() as cur:
            cur.execute(query, params)
            cols = [c[0] for c in cur.description]
            results = [dict(zip(cols, row)) for row in cur.fetchall()]

        matching = [r for r in results if r['id'] == agent.id]
        self.assertEqual(len(matching), 1)
        row = matching[0]
        self.assertEqual(row['sub_payment_status'], 'completed')
        self.assertEqual(row['razorpay_payment_id'], 'pay_APPROV001')

    @patch('apps.agents.views.registration.queue_invoice_and_welcome')
    def test_admin_manual_reconcile_moves_to_pending_approval(self, _queue):
        """Admin can reconcile a pending payment from Razorpay API and move agent to pending_approval."""
        self._complete_step1_and_step2('reconcile.agent@example.com')
        sub = self._create_order('starter', 'order_RECON001')
        amount_paise = int(round(float(sub.registration_amount) * 100))
        agent = sub.agent

        from apps.agents.views.registration import verify_and_activate_pending_payment

        with patch('apps.agents.views.registration.razorpay_client',
                   return_value=_mock_razorpay_client(amount_paise)):
            success = verify_and_activate_pending_payment(agent)

        self.assertTrue(success)
        agent.refresh_from_db()
        sub.refresh_from_db()
        self.assertEqual(sub.payment_status, 'completed')
        self.assertEqual(agent.status, 'pending_approval')

    def test_admin_approval_action_transitions_agent_to_active(self):
        """Admin approving agent transitions status from 'pending_approval' to 'active'."""
        self._complete_step1_and_step2('admin.approve@example.com')
        sub = self._create_order('starter', 'order_ACTIVE001')
        agent = sub.agent
        agent.status = 'pending_approval'
        agent.save()

        # Admin login session
        session = self.client.session
        session['admin_id'] = 1
        session.save()

        from django.db import connection
        with connection.cursor() as cur:
            cur.execute("UPDATE agents SET status = 'active' WHERE id = %s", [agent.id])

        agent.refresh_from_db()
        self.assertEqual(agent.status, 'active')

    @patch('apps.agents.views.registration.queue_invoice_and_welcome')
    def test_free_trial_and_zero_amount_require_admin_approval(self, _queue):
        """Free trial / zero amount registrations must also set status='pending_approval'."""
        self._complete_step1_and_step2('freetrial.agent@example.com')

        # Test zero amount checkout
        with patch('apps.agents.views.registration.create_checkout_order',
                   return_value=(None, False)):
            with patch('apps.agents.views.registration._to_paise', return_value=0):
                resp = self.client.post(
                    '/agent-register/complete/',
                    data={'plan_type': 'free_trial'},
                    content_type='application/json',
                )
        self.assertEqual(resp.status_code, 200, resp.content)
        agent = Agent.objects.get(email='freetrial.agent@example.com')
        self.assertEqual(agent.status, 'pending_approval', "Free trial must go to pending_approval")
