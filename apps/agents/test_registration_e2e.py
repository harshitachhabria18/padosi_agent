"""End-to-end agent registration: step 1 -> step 2 -> plan -> Razorpay -> dashboard.

Razorpay is mocked at the gateway boundary (order creation + client); every
Django view, session key and DB write in between is the real code path.
"""
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import TestCase, override_settings

from apps.agents.models import Agent, AgentSubscription
from apps.home.models import SiteSetting
from apps.home.models.pincode import Pincode

ORDER_ID = 'order_E2EREG0000001'
PAYMENT_ID = 'pay_E2EREG0000001'


def _no_favorites():
    # favorite_agents is a legacy Laravel table whose test-DB copy lacks the
    # user_id/agent_id columns; stub only that one lookup on the dashboard.
    fav = MagicMock()
    fav.objects.filter.return_value.values_list.return_value = []
    return patch('apps.agents.views.dashboard.FavoriteAgent', fav)


@override_settings(ALLOWED_HOSTS=['testserver', 'localhost'])
class AgentRegistrationEndToEndTests(TestCase):
    def setUp(self):
        cache.clear()
        Pincode.objects.create(
            pincode='380001', office_name='Ahmedabad GPO', district='Ahmedabad',
            state='Gujarat', latitude='23.02250000', longitude='72.57140000',
        )
        SiteSetting.set_value('pricing_config', {
            'starter': {'name': "Starter's Plan", 'full_price': 1999},
            'professional': {'name': "Professional's Plan", 'full_price': 4999},
        }, 'pricing')
        SiteSetting.set_value('trial_plan_config', {'price': 99, 'duration_days': 30}, 'pricing')

    def _step1(self, email='e2e.agent@example.com'):
        return self.client.post('/agent-register-step1/', {
            'fullname': 'E2E Agent',
            'email': email,
            'mobile': '9876543210',
            'agent_pincode': '380001',
            'state': 'Gujarat',
            'experience_range': '5',
            'segments[]': ['life'],
        })

    def _razorpay_client(self, amount_paise):
        client = MagicMock()
        client.utility.verify_payment_signature.return_value = True
        client.payment.fetch.return_value = {'status': 'captured', 'amount': amount_paise}
        return client

    def _register_and_create_order(self, plan_type='starter'):
        r1 = self._step1()
        self.assertEqual(r1.status_code, 200, r1.content)
        self.assertTrue(r1.json()['success'])

        r2 = self.client.post('/agent-register-step2/', {'bio': 'Helping families.'})
        self.assertEqual(r2.status_code, 200, r2.content)

        page = self.client.get('/chooseplan/')
        self.assertEqual(page.status_code, 200)

        with patch('apps.agents.views.registration.create_checkout_order',
                   return_value=(ORDER_ID, False)):
            r3 = self.client.post(
                '/agent-register/complete/',
                data={'plan_type': plan_type},
                content_type='application/json',
            )
        self.assertEqual(r3.status_code, 200, r3.content)
        body = r3.json()
        self.assertTrue(body.get('success', True), body)

        sub = AgentSubscription.objects.get(razorpay_order_id=ORDER_ID)
        self.assertEqual(sub.payment_status, 'pending')
        self.assertEqual(sub.agent.status, 'pending_payment')
        self.assertEqual(sub.agent.plan_type, plan_type)
        return sub

    @patch('apps.agents.views.registration.queue_invoice_and_welcome')
    def test_starter_registration_payment_login_dashboard(self, _queue):
        sub = self._register_and_create_order('starter')
        amount_paise = int(round(float(sub.registration_amount) * 100))

        with patch('apps.agents.views.registration.razorpay_client',
                   return_value=self._razorpay_client(amount_paise)):
            r = self.client.post(
                '/agent-register/verify-payment/',
                data={
                    'razorpay_order_id': ORDER_ID,
                    'razorpay_payment_id': PAYMENT_ID,
                    'razorpay_signature': 'sig_e2e',
                },
                content_type='application/json',
            )
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()['success'], r.json())

        sub.refresh_from_db()
        agent = Agent.objects.get(pk=sub.agent_id)
        self.assertEqual(sub.payment_status, 'completed')
        self.assertEqual(agent.plan_type, 'starter')
        self.assertIn(agent.status, ('active', 'pending_approval'))
        _queue.assert_called_once()

        # Signed in by the payment itself; dashboard is open.
        with _no_favorites():
            dash = self.client.get('/agent/dashboard/')
        self.assertEqual(dash.status_code, 200)

        # New agent's temporary password is their registered mobile number.
        self.client.logout()
        login = self.client.post('/agent-login/', {'email': agent.email, 'password': agent.mobile})
        self.assertEqual(login.status_code, 302)
        self.assertIn('/agent/dashboard', login['Location'])

    @patch('apps.agents.views.registration.queue_invoice_and_welcome')
    def test_razorpay_redirect_callback_activates_and_logs_in(self, _queue):
        """Netbanking/UPI redirect flow (POST to payment-callback)."""
        sub = self._register_and_create_order('professional')
        amount_paise = int(round(float(sub.registration_amount) * 100))

        with patch('apps.agents.views.registration.razorpay_client',
                   return_value=self._razorpay_client(amount_paise)):
            r = self.client.post('/agent-register/payment-callback/', {
                'razorpay_order_id': ORDER_ID,
                'razorpay_payment_id': PAYMENT_ID,
                'razorpay_signature': 'sig_e2e',
            })
        self.assertEqual(r.status_code, 302)
        self.assertNotIn('agent-login', r['Location'])
        sub.refresh_from_db()
        self.assertEqual(sub.payment_status, 'completed')
        self.assertEqual(sub.agent.plan_type, 'professional')
        with _no_favorites():
            self.assertEqual(self.client.get('/agent/dashboard/').status_code, 200)

    @patch('apps.agents.views.registration.queue_invoice_and_welcome')
    def test_unpaid_agent_is_sent_to_chooseplan(self, _queue):
        sub = self._register_and_create_order('starter')
        from apps.agents.views.registration import create_or_link_django_user
        self.client.force_login(create_or_link_django_user(sub.agent))
        dash = self.client.get('/agent/dashboard/')
        self.assertEqual(dash.status_code, 302)
        self.assertIn('/chooseplan/', dash['Location'])

    def test_step1_rejects_bad_input_and_keeps_good_input(self):
        bad = self.client.post('/agent-register-step1/', {
            'fullname': 'X', 'email': 'nope', 'mobile': '12345',
            'agent_pincode': '000000', 'state': '',
        })
        self.assertEqual(bad.status_code, 400)
        self.assertFalse(bad.json()['success'])
        good = self._step1('second.agent@example.com')
        self.assertEqual(good.status_code, 200, good.content)
        self.assertEqual(good.json()['redirect'], '/chooseplan/')
