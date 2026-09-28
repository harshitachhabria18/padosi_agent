from datetime import datetime, timedelta
from unittest.mock import patch

from django.test import Client, TestCase
from django.urls import reverse

from apps.agents.models import Agent, AgentSubscription
from apps.event_referral.models import EventReferralCampaign, EventReferralParticipant
from apps.event_referral.services.participant_service import evaluate_participant
from apps.event_referral.services.qualification_service import (
    is_event_referral_code,
    qualify_event_referral,
    register_referred_agent,
)
from apps.agents.services.account_auth import agent_can_access_dashboard


class EventReferralRegistrationTests(TestCase):
    def setUp(self):
        EventReferralCampaign.objects.all().delete()
        self.campaign = EventReferralCampaign.objects.create(is_enabled=True)

    def test_event_page_uses_agent_registration_template(self):
        client = Client()
        resp = client.get(reverse('event_referral:register'))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'agents/registration.html')
        self.assertTrue(resp.context['event_referral_mode'])

    @patch('apps.agents.services.brevo.email_service')
    def test_step1_finalize_creates_challenge_agent(self, mock_email):
        mock_email.send_welcome.return_value = True
        client = Client()
        session = client.session
        session['event_referral_registration'] = True
        session.save()

        resp = client.post(
            reverse('agents:agent_register_step1'),
            {
                'fullname': 'Test Agent',
                'email': 'evtest@example.com',
                'mobile': '9876543210',
                'whatsapp': '9876543210',
                'agent_pincode': '380001',
                'state': 'Gujarat',
                'experience_range': '3',
                'segments[]': ['life'],
                'client_base': '100',
                'agree_terms': 'on',
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get('success'))
        agent = Agent.objects.get(email='evtest@example.com')
        self.assertEqual(agent.status, 'event_challenge')
        self.assertTrue(agent_can_access_dashboard(agent))
        self.assertTrue(EventReferralParticipant.objects.filter(agent=agent).exists())
        mock_email.send_welcome.assert_called_once()
        welcome_kwargs = mock_email.send_welcome.call_args.kwargs
        welcome_args = mock_email.send_welcome.call_args.args
        self.assertEqual(welcome_args[0], 'evtest@example.com')
        self.assertEqual(welcome_args[2], '9876543210')
        self.assertEqual(welcome_kwargs.get('subject'), 'Welcome to Paldi — your PadosiAgent login details')

    def test_ev_code_detection(self):
        self.assertTrue(is_event_referral_code('EV-ABC123'))
        self.assertFalse(is_event_referral_code('PA-ABC123'))


class EventReferralQualificationTests(TestCase):
    def setUp(self):
        EventReferralCampaign.objects.all().delete()
        self.campaign = EventReferralCampaign.objects.create(
            is_enabled=True,
            required_paid_referrals=2,
            window_hours=48,
        )
        self.referrer = Agent.objects.create(
            fullname='Referrer',
            email='referrer@example.com',
            mobile='9000000001',
            status='event_challenge',
            plan_type='',
        )
        self.participant = EventReferralParticipant.create_for_agent(self.referrer, self.campaign)
        self.participant.required_paid_referrals = 2
        self.participant.save()

    def _paid_agent(self, email, mobile):
        return Agent.objects.create(
            fullname='Ref',
            email=email,
            mobile=mobile,
            status='pending_approval',
            plan_type='basic',
            referred_by_code=self.participant.referral_code,
        )

    def _subscription(self, agent):
        return AgentSubscription.objects.create(
            agent=agent,
            selected_plan='Starter',
            registration_amount=100,
            payment_status='completed',
            status='active',
            razorpay_order_id='order_test123456',
            razorpay_payment_id='pay_test1234567',
        )

    def test_paid_referrals_grant_basic_plan(self):
        for i in range(2):
            agent = self._paid_agent(f'ref{i}@example.com', f'900000000{i+2}')
            register_referred_agent(agent)
            qualify_event_referral(agent, self._subscription(agent))
        self.participant.refresh_from_db()
        self.referrer.refresh_from_db()
        self.assertEqual(self.participant.status, 'won')
        self.assertEqual(self.referrer.plan_type, 'basic')

    def test_late_payment_does_not_count(self):
        self.participant.deadline_at = datetime.now() - timedelta(hours=1)
        self.participant.save()
        agent = self._paid_agent('late@example.com', '9000000099')
        register_referred_agent(agent)
        qualify_event_referral(agent, self._subscription(agent))
        self.participant.refresh_from_db()
        self.assertEqual(self.participant.paid_count, 0)
        evaluate_participant(self.participant, block_on_expire=True)
        self.referrer.refresh_from_db()
        self.assertEqual(self.referrer.status, 'suspended')

    def test_self_referral_rejected(self):
        self.referrer.referred_by_code = self.participant.referral_code
        self.referrer.save()
        register_referred_agent(self.referrer)
        self.assertFalse(
            self.participant.referrals.filter(referred_agent=self.referrer, state='paid').exists()
        )
