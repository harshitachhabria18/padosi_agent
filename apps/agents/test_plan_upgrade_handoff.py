"""App upgrade link: one-time token logs the agent into the website checkout."""
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from django.contrib.auth.models import User
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse

from apps.agents.models import Agent, AgentSubscription, PlanUpgradeHandoff
from plan_upgrade_handoff import (
    hash_handoff_token,
    new_handoff_token,
    upgrade_target_allowed,
)


def _paid_agent(email='paid@example.com', mobile='9876500100', plan_type='starter'):
    user = User.objects.create_user(email, email, None)
    agent = Agent.objects.create(
        user=user, fullname='Paid Agent', email=email, mobile=mobile,
        status='active', plan_type=plan_type,
    )
    AgentSubscription.objects.create(
        agent=agent, selected_plan="Starter's Plan", registration_amount=Decimal('1999.00'),
        payment_status='completed', status='active',
        razorpay_order_id=f'order_PAID{agent.pk}', razorpay_payment_id=f'pay_PAID{agent.pk}',
    )
    return agent


def _store_token(agent, plan_slug='professional', expires_at=None):
    raw = new_handoff_token()
    PlanUpgradeHandoff.objects.create(
        token_hash=hash_handoff_token(raw),
        agent=agent,
        plan_slug=plan_slug,
        expires_at=expires_at or (datetime.now() + timedelta(minutes=3)),
    )
    return raw


class UpgradeTargetTests(SimpleTestCase):
    def test_only_a_higher_paid_plan_is_allowed(self):
        self.assertTrue(upgrade_target_allowed('starter', 'professional'))
        self.assertTrue(upgrade_target_allowed('free_trial', 'starter'))
        self.assertTrue(upgrade_target_allowed('', 'pro'))
        self.assertFalse(upgrade_target_allowed('professional', 'starter'))
        self.assertFalse(upgrade_target_allowed('professional', 'professional'))
        self.assertFalse(upgrade_target_allowed('exclusive', 'professional'))
        self.assertFalse(upgrade_target_allowed('starter', 'exclusive'))


class AppUpgradeHandoffTests(TestCase):
    def test_valid_token_logs_in_and_opens_upgrade(self):
        agent = _paid_agent()
        raw = _store_token(agent)
        resp = self.client.get(reverse('agents:app_upgrade_handoff'), {'token': raw})
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/agent/dashboard/', resp['Location'])
        self.assertIn('upgrade=professional', resp['Location'])
        self.assertEqual(self.client.session['_auth_user_id'], str(agent.user_id))
        self.assertIsNotNone(PlanUpgradeHandoff.objects.get(agent=agent).used_at)

    def test_token_cannot_be_reused(self):
        agent = _paid_agent()
        raw = _store_token(agent)
        first = self.client.get(reverse('agents:app_upgrade_handoff'), {'token': raw})
        self.assertEqual(first.status_code, 302)

        other = Client()
        second = other.get(reverse('agents:app_upgrade_handoff'), {'token': raw})
        self.assertEqual(second.status_code, 302)
        self.assertIn('/agent-login/', second['Location'])
        self.assertNotIn('_auth_user_id', other.session)

    def test_expired_or_missing_token_does_not_log_in(self):
        agent = _paid_agent()
        raw = _store_token(agent, expires_at=datetime.now() - timedelta(seconds=1))
        resp = self.client.get(reverse('agents:app_upgrade_handoff'), {'token': raw})
        self.assertIn('/agent-login/', resp['Location'])
        self.assertNotIn('_auth_user_id', self.client.session)

        resp = self.client.get(reverse('agents:app_upgrade_handoff'), {'token': 'not-a-real-token'})
        self.assertIn('/agent-login/', resp['Location'])
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_agent_id_query_without_token_does_not_log_in(self):
        agent = _paid_agent()
        resp = self.client.get(reverse('agents:app_upgrade_handoff'), {'agent_id': agent.pk})
        self.assertIn('/agent-login/', resp['Location'])
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_handoff_switches_away_from_another_logged_in_agent(self):
        target = _paid_agent()
        other = _paid_agent(email='other@example.com', mobile='9876500101')
        self.client.force_login(other.user)
        raw = _store_token(target)
        resp = self.client.get(reverse('agents:app_upgrade_handoff'), {'token': raw})
        self.assertIn('upgrade=professional', resp['Location'])
        self.assertEqual(self.client.session['_auth_user_id'], str(target.user_id))

    def test_blocked_agent_is_not_logged_in(self):
        agent = _paid_agent()
        agent.status = 'suspended'
        agent.save(update_fields=['status'])
        raw = _store_token(agent)
        resp = self.client.get(reverse('agents:app_upgrade_handoff'), {'token': raw})
        self.assertIn('/agent-login/', resp['Location'])
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_unpaid_agent_is_sent_to_chooseplan(self):
        user = User.objects.create_user('new@example.com', 'new@example.com', None)
        agent = Agent.objects.create(
            user=user, fullname='New Agent', email='new@example.com', mobile='9876500199',
            status='pending_payment', plan_type='',
        )
        raw = _store_token(agent, plan_slug='starter')
        resp = self.client.get(reverse('agents:app_upgrade_handoff'), {'token': raw})
        self.assertIn('/chooseplan/', resp['Location'])
        self.assertEqual(self.client.session['_auth_user_id'], str(user.id))

    def test_dashboard_marks_the_upgrade_to_open(self):
        from django.conf import settings
        from django.template import Context, Template

        from apps.agents.services.plan_upgrade_handoff import dashboard_upgrade_slug

        starter = SimpleNamespace(plan_type='starter')
        self.assertEqual(dashboard_upgrade_slug(starter, 'professional'), 'professional')
        self.assertEqual(dashboard_upgrade_slug(starter, 'starter'), '')
        self.assertEqual(dashboard_upgrade_slug(starter, 'exclusive'), '')

        source = (settings.BASE_DIR / 'templates/agents/dashboard.html').read_text(encoding='utf-8')
        start = source.index('<div id="app-upgrade-plan"')
        snippet = source[start:source.index('{% endblock %}', start)]
        html = Template(snippet).render(Context({
            'app_upgrade_plan': 'professional',
            'starterDisc': 1999,
        }))
        self.assertIn('data-plan="professional"', html)
        self.assertIn('openProfessionalUpgradeModal', html)


class _FakeQuery:
    def __init__(self, count):
        self._count = count

    def filter(self, *args, **kwargs):
        return self

    def count(self):
        return self._count


class _FakeDB:
    def __init__(self, count=0):
        self._count = count
        self.added = []
        self.committed = False

    def query(self, model):
        return _FakeQuery(self._count)

    def add(self, row):
        self.added.append(row)

    def commit(self):
        self.committed = True


class FastAPIHandoffApiTests(SimpleTestCase):
    def setUp(self):
        from fastapi_app.database import get_db
        from fastapi_app.dependencies.auth import get_current_agent
        from fastapi_app.main import app
        from starlette.testclient import TestClient

        self.app = app
        self.client = TestClient(app, raise_server_exceptions=False)
        self.get_db = get_db
        self.get_current_agent = get_current_agent
        self.app.dependency_overrides.clear()

    def tearDown(self):
        self.app.dependency_overrides.clear()

    def _agent(self, plan_type='starter'):
        return SimpleNamespace(id=7, plan_type=plan_type, status='active', email='paid@example.com')

    def test_missing_token_is_rejected(self):
        resp = self.client.post('/v1/agents/plan-upgrade/handoff', json={'plan_slug': 'professional'})
        self.assertIn(resp.status_code, (401, 403))

    def test_issues_one_time_url_for_the_token_agent(self):
        db = _FakeDB()
        self.app.dependency_overrides[self.get_current_agent] = lambda: self._agent('starter')
        self.app.dependency_overrides[self.get_db] = lambda: db
        resp = self.client.post('/v1/agents/plan-upgrade/handoff', json={'plan_slug': 'professional'})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body['success'])
        self.assertEqual(body['plan_slug'], 'professional')
        self.assertEqual(body['expires_in'], 180)
        self.assertIn('/agent/app-upgrade/?token=', body['url'])
        token = parse_qs(urlparse(body['url']).query)['token'][0]
        self.assertTrue(db.committed)
        self.assertEqual(db.added[0].agent_id, 7)
        self.assertEqual(db.added[0].plan_slug, 'professional')
        self.assertEqual(db.added[0].token_hash, hash_handoff_token(token))
        self.assertNotIn(token, db.added[0].token_hash)

    def test_same_or_lower_plan_is_rejected(self):
        self.app.dependency_overrides[self.get_current_agent] = lambda: self._agent('professional')
        self.app.dependency_overrides[self.get_db] = lambda: _FakeDB()
        resp = self.client.post('/v1/agents/plan-upgrade/handoff', json={'plan_slug': 'professional'})
        self.assertEqual(resp.status_code, 409)

    def test_unknown_plan_is_rejected(self):
        self.app.dependency_overrides[self.get_current_agent] = lambda: self._agent('starter')
        self.app.dependency_overrides[self.get_db] = lambda: _FakeDB()
        resp = self.client.post('/v1/agents/plan-upgrade/handoff', json={'plan_slug': 'exclusive'})
        self.assertEqual(resp.status_code, 400)

    def test_too_many_links_are_rejected(self):
        self.app.dependency_overrides[self.get_current_agent] = lambda: self._agent('starter')
        self.app.dependency_overrides[self.get_db] = lambda: _FakeDB(count=5)
        resp = self.client.post('/v1/agents/plan-upgrade/handoff', json={'plan_slug': 'professional'})
        self.assertEqual(resp.status_code, 429)
