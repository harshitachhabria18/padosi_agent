"""
Regression tests for the 2026-09-23 security audit fixes.

Each test pins one confirmed vulnerability so it cannot silently return:
payment-flow account takeover / plan escalation, passwordless portal logins,
PII leaks, IDOR/traversal on private files, review tampering, stored XSS
serialisation and spoofable client IPs.
"""
import json
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.urls import reverse

from apps.agents.models import Agent, AgentProfile, AgentReview, AgentSubscription, Client


def _paid_agent(email='paid@example.com', mobile='9876500100', status='active', plan_type='starter'):
    user = User.objects.create_user(email, email, None)
    agent = Agent.objects.create(
        user=user, fullname='Paid Agent', email=email, mobile=mobile,
        status=status, plan_type=plan_type,
    )
    AgentSubscription.objects.create(
        agent=agent, selected_plan="Starter's Plan", registration_amount=Decimal('1999.00'),
        payment_status='completed', status='active',
        razorpay_order_id=f'order_PAID{agent.pk}', razorpay_payment_id=f'pay_PAID{agent.pk}',
    )
    return agent


class PaymentCallbackTakeoverTests(TestCase):
    """AUD-SEC-001: /agent-register/payment-callback/?agent_id=N logged anyone in as agent N."""

    def test_callback_with_foreign_agent_id_does_not_log_in(self):
        victim = _paid_agent()
        resp = self.client.get(
            reverse('agents:agent_register_payment_callback') + f'?agent_id={victim.pk}'
        )
        self.assertEqual(resp.status_code, 302)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_verify_payment_known_order_id_does_not_log_in_other_session(self):
        victim = _paid_agent()
        sub = victim.subscriptions.first()
        resp = self.client.post(
            reverse('agents:agent_register_verify_payment'),
            data=json.dumps({'razorpay_order_id': sub.razorpay_order_id}),
            content_type='application/json',
        )
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertEqual(resp.json().get('redirect_url'), reverse('agents:agent_login'))


@patch('apps.agents.views.registration.queue_invoice_and_welcome')
@patch('apps.agents.views.registration.razorpay_client')
class PaymentPlanBindingTests(TestCase):
    """AUD-SEC-002: activation must use the priced order's plan, not the client's."""

    def _pending_order(self):
        agent = Agent.objects.create(
            fullname='Buyer', email='buyer@example.com', mobile='9876500200',
            status='pending_payment', plan_type='starter',
        )
        sub = AgentSubscription.objects.create(
            agent=agent, selected_plan="Starter's Plan", registration_amount=Decimal('1999.00'),
            payment_status='pending', status='inactive', razorpay_order_id='order_BUY1',
        )
        return agent, sub

    def _gateway(self, mock_client, amount_paise):
        client = MagicMock()
        client.payment.fetch.return_value = {'status': 'captured', 'amount': amount_paise}
        mock_client.return_value = client

    def test_client_plan_type_cannot_escalate_plan(self, mock_client, _queue):
        agent, sub = self._pending_order()
        self._gateway(mock_client, 199900)
        session = self.client.session
        session['pending_checkout'] = {
            'agent_id': agent.pk, 'order_id': sub.razorpay_order_id,
            'plan_type': 'starter', 'plan_name': "Starter's Plan",
        }
        session.save()

        self.client.post(
            reverse('agents:agent_register_verify_payment'),
            data=json.dumps({
                'razorpay_order_id': sub.razorpay_order_id,
                'razorpay_payment_id': 'pay_BUY1',
                'razorpay_signature': 'sig',
                'plan_type': 'exclusive',
                'plan_name': 'Exclusive Plan',
            }),
            content_type='application/json',
        )
        agent.refresh_from_db()
        sub.refresh_from_db()
        self.assertEqual(sub.payment_status, 'completed')
        self.assertEqual(agent.plan_type, 'starter')

    def test_order_of_other_agent_is_rejected(self, mock_client, _queue):
        agent, sub = self._pending_order()
        other = Agent.objects.create(
            fullname='Other', email='other@example.com', mobile='9876500300',
            status='pending_payment', plan_type='starter',
        )
        self._gateway(mock_client, 199900)
        session = self.client.session
        session['pending_checkout'] = {'agent_id': other.pk, 'order_id': 'order_OTHER'}
        session.save()

        resp = self.client.post(
            reverse('agents:agent_register_verify_payment'),
            data=json.dumps({
                'razorpay_order_id': sub.razorpay_order_id,
                'razorpay_payment_id': 'pay_BUY1',
                'razorpay_signature': 'sig',
            }),
            content_type='application/json',
        )
        self.assertFalse(resp.json().get('success'))
        sub.refresh_from_db()
        self.assertEqual(sub.payment_status, 'pending')
        self.assertNotIn('_auth_user_id', self.client.session)


class OrderPlanSlugTests(SimpleTestCase):
    def test_unparseable_plan_name_never_defaults_to_professional(self):
        from apps.agents.views.registration import _order_plan_slug
        sub = MagicMock(selected_plan='Digital Card Plan')
        agent = MagicMock(plan_type='starter')
        self.assertEqual(_order_plan_slug(sub, agent), 'starter')


class PaymentFailureStatusTests(TestCase):
    """AUD-SEC-006: payment-failure must not act on a body-supplied agent_id."""

    def test_foreign_agent_id_cannot_unsuspend(self):
        victim = _paid_agent(status='suspended')
        self.client.post(
            reverse('agents:payment_failure'),
            data=json.dumps({'agent_id': victim.pk}),
            content_type='application/json',
        )
        victim.refresh_from_db()
        self.assertEqual(victim.status, 'suspended')


class RegisterFailedPiiTests(TestCase):
    """AUD-SEC-005: failed page leaked any agent's email/mobile via ?agent_id=."""

    def test_agent_id_query_param_is_ignored(self):
        victim = _paid_agent(email='leak@example.com')
        resp = self.client.get(reverse('agents:agent_register_failed') + f'?agent_id={victim.pk}')
        self.assertNotContains(resp, 'leak@example.com')


class ClientQuickRegisterTakeoverTests(TestCase):
    """AUD-SEC-003: quick-register signed anyone in as any existing user."""

    def _post(self, email, mobile='9876500400'):
        return self.client.post(
            reverse('agents:client_quick_register'),
            data=json.dumps({'fullname': 'Visitor', 'email': email, 'mobile': mobile}),
            content_type='application/json',
        )

    def test_staff_email_is_not_logged_in(self):
        User.objects.create_user('boss', 'boss@example.com', 'x', is_staff=True, is_superuser=True)
        resp = self._post('boss@example.com')
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_agent_email_is_not_logged_in_or_converted(self):
        agent = _paid_agent(email='agentx@example.com')
        self._post('agentx@example.com')
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertFalse(Client.objects.filter(user=agent.user).exists())

    def test_agent_email_without_auth_user_gets_no_new_account(self):
        Agent.objects.create(fullname='Orphan', email='orphan@example.com', mobile='9876500500', status='active')
        self._post('orphan@example.com', mobile='9876500501')
        self.assertFalse(User.objects.filter(email__iexact='orphan@example.com').exists())

    def test_new_client_has_unusable_password(self):
        self._post('fresh@example.com', mobile='9876500600')
        user = User.objects.get(email='fresh@example.com')
        self.assertFalse(user.has_usable_password())


class PrivateFileTraversalTests(TestCase):
    """AUD-SEC-008: owner check ran on the raw path (agents/<id>/../../...)."""

    def test_traversal_out_of_own_folder_is_forbidden(self):
        agent = _paid_agent()
        self.client.force_login(agent.user)
        url = reverse('serve_private_file', args=[f'agents/{agent.pk}/../../invoices/other.pdf'])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 403)

    def test_public_media_fallback_refuses_private_dir(self):
        resp = self.client.get('/media/app//private/invoices/other.pdf')
        self.assertEqual(resp.status_code, 404)


class ReviewTamperingTests(TestCase):
    """AUD-SEC-010: anonymous review update_or_create keyed on an unverified email."""

    def test_anonymous_cannot_overwrite_existing_review(self):
        agent = _paid_agent()
        AgentProfile.objects.create(agent=agent, slug='paid-agent')
        AgentReview.objects.create(
            agent=agent, reviewer_name='Happy', reviewer_email='happy@example.com',
            rating=5, review='Wonderful service from this agent.', is_approved=True,
        )
        resp = self.client.post(reverse('agents:agent_store_review', args=['paid-agent']), {
            'rating': '1', 'review': 'Terrible terrible terrible.',
            'fullname': 'Attacker', 'email': 'happy@example.com', 'mobile': '9876500700',
        })
        self.assertEqual(resp.status_code, 422)
        review = AgentReview.objects.get(agent=agent, reviewer_email='happy@example.com')
        self.assertEqual(review.rating, 5)


class ParticipantsPrivacyTests(TestCase):
    """AUD-SEC-009: participant PII listing and Facebook actions without ownership."""

    def test_participant_listing_requires_admin(self):
        resp = self.client.get('/participants')
        self.assertEqual(resp.status_code, 403)

    def test_facebook_action_requires_ownership(self):
        from apps.agents.models import Participant
        participant = Participant.objects.create(
            full_name='P', email='p@example.com', phone_number='9876500800',
            have_insurance='no', mutual_fund='no', shareable_id='part_abc',
            participant_shared='No', facebook_access_token='tok',
        )
        resp = self.client.post(reverse('agents:facebook_auto_post'), {
            'participant_id': participant.pk, 'message': 'spam', 'link': 'https://evil.example',
        })
        self.assertEqual(resp.status_code, 403)


class SocialFollowTierTests(TestCase):
    """AUD-SEC-011: arbitrary platform strings unlocked every discount tier."""

    def test_unknown_platform_rejected(self):
        resp = self.client.post(
            reverse('agents:plan_social_follow'),
            data=json.dumps({'platform': 'zzz-fake', 'agent_id': 1}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)


class HomepageReviewSerialisationTests(SimpleTestCase):
    """AUD-SEC-004: homepage testimonials were stored XSS."""

    def test_markup_is_escaped_and_script_cannot_close(self):
        from apps.home.views.pages import _reviews_json_for_script
        out = _reviews_json_for_script([{
            'name': '<img src=x onerror =alert(1)>', 'comment': '</script><script>x()</script>',
            'rating': 5.0, 'service': 'Verified Client', 'image': 'https://a/?b=1&c=2', 'agent_url': None,
        }])
        self.assertNotIn('<img', out)
        self.assertNotIn('</script', out.lower())
        self.assertEqual(json.loads(out)[0]['rating'], 5.0)


class SafeJsonFilterTests(SimpleTestCase):
    def test_script_breakout_escaped(self):
        from apps.home.templatetags.json_tags import safe_json
        out = safe_json({'name': '</script><b>'})
        self.assertNotIn('<', out)
        self.assertEqual(json.loads(out), {'name': '</script><b>'})
        self.assertEqual(safe_json(None, '{}'), '{}')


class ProfileEmailTakeoverTests(TestCase):
    """AUD-SEC-007: an agent could adopt a staff user's email and log in as them."""

    def test_email_of_other_auth_user_is_taken(self):
        from apps.agents.views.dashboard import _email_taken_by_other_login
        User.objects.create_user('staffer', 'staff@example.com', 'x', is_staff=True)
        agent = _paid_agent()
        self.assertTrue(_email_taken_by_other_login('staff@example.com', agent))
        self.assertFalse(_email_taken_by_other_login(agent.email, agent))


class ClientIpSpoofingTests(SimpleTestCase):
    """AUD-SEC-012: X-Forwarded-For[0] is client-controlled."""

    def test_rightmost_public_hop_wins(self):
        from apps.admin_panel.middleware import ThreatMonitorMiddleware
        req = RequestFactory().get('/', HTTP_X_FORWARDED_FOR='1.2.3.4, 49.36.10.20', REMOTE_ADDR='127.0.0.1')
        self.assertEqual(ThreatMonitorMiddleware.get_client_ip(req), '49.36.10.20')

    def test_direct_client_header_ignored(self):
        from apps.admin_panel.middleware import ThreatMonitorMiddleware
        req = RequestFactory().get('/', HTTP_X_FORWARDED_FOR='127.0.0.1', REMOTE_ADDR='49.36.10.21')
        self.assertEqual(ThreatMonitorMiddleware.get_client_ip(req), '49.36.10.21')


class RefundWebhookTests(TestCase):
    """A full Razorpay refund revokes the paid subscription; partial refunds don't."""

    def _refund_event(self, sub, refunded, status):
        return {
            'event': 'refund.processed',
            'payload': {'payment': {'entity': {
                'id': sub.razorpay_payment_id, 'order_id': sub.razorpay_order_id,
                'amount': 199900, 'amount_refunded': refunded, 'refund_status': status,
            }}},
        }

    def test_full_refund_revokes_access(self):
        from apps.agents.services.account_auth import agent_can_access_dashboard
        from apps.agents.views.registration import _handle_refund_webhook
        agent = _paid_agent(email='refund@example.com')
        sub = agent.subscriptions.first()
        resp = _handle_refund_webhook(self._refund_event(sub, 199900, 'full'))
        self.assertEqual(resp.status_code, 200)
        sub.refresh_from_db()
        agent.refresh_from_db()
        self.assertEqual(sub.payment_status, 'refunded')
        self.assertEqual(agent.status, 'pending_payment')
        self.assertFalse(agent_can_access_dashboard(agent))

    def test_partial_refund_keeps_access(self):
        from apps.agents.views.registration import _handle_refund_webhook
        agent = _paid_agent(email='partial@example.com')
        sub = agent.subscriptions.first()
        _handle_refund_webhook(self._refund_event(sub, 50000, 'partial'))
        sub.refresh_from_db()
        self.assertEqual(sub.payment_status, 'completed')


class DefaultPasswordTests(TestCase):
    """New website agents get their 10-digit mobile as the initial password."""

    def test_new_agent_temp_password_is_mobile(self):
        from apps.agents.services.account_auth import create_or_link_django_user, verify_agent_password
        mobile = '9876500900'
        agent = Agent.objects.create(
            fullname='New', email='newagent@example.com', mobile=mobile, status='active',
        )
        create_or_link_django_user(agent)
        ok, _, _ = verify_agent_password(agent.email, mobile, agent=agent)
        self.assertTrue(ok)
        ok_email, _, _ = verify_agent_password(agent.email, agent.email, agent=agent)
        self.assertFalse(ok_email)


class RegistrationPhotoUploadTests(SimpleTestCase):
    """Real photos keep uploading whatever their file name; non-images are refused."""

    @staticmethod
    def _image_upload(name, fmt='JPEG'):
        import io
        from PIL import Image
        from django.core.files.uploadedfile import SimpleUploadedFile
        buf = io.BytesIO()
        Image.new('RGB', (8, 8), (200, 10, 10)).save(buf, format=fmt)
        return SimpleUploadedFile(name, buf.getvalue(), content_type='image/jpeg')

    def test_real_photos_accepted_with_any_name(self):
        from apps.agents.views.registration import _validated_photo_upload
        for name, fmt, ext in (
            ('me.jpg', 'JPEG', '.jpg'), ('ME.JPG', 'JPEG', '.jpg'),
            ('whatsapp.jfif', 'JPEG', '.jpg'), ('IMG_2031', 'JPEG', '.jpg'),
            ('shot.png', 'PNG', '.png'), ('pic.webp', 'WEBP', '.webp'),
        ):
            upload = _validated_photo_upload(self._image_upload(name, fmt))
            self.assertIsNotNone(upload, name)
            self.assertTrue(upload.name.endswith(ext), (name, upload.name))

    def test_non_images_rejected(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from apps.agents.views.registration import _validated_photo_upload
        html = SimpleUploadedFile('evil.jpg', b'<html><script>alert(1)</script></html>', content_type='image/jpeg')
        svg = SimpleUploadedFile('x.svg', b'<svg xmlns="http://www.w3.org/2000/svg"></svg>', content_type='image/svg+xml')
        self.assertIsNone(_validated_photo_upload(html))
        self.assertIsNone(_validated_photo_upload(svg))
        self.assertIsNone(_validated_photo_upload(None))
