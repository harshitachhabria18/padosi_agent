from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.contrib.auth.models import User
from unittest.mock import MagicMock, patch

from apps.agents.models import Agent, AgentProfile, AgentReview
from apps.agents.services.feature_unlock import overlay_plan
from apps.agents.services.qr_branded import build_qr_target_url, generate_branded_qr_png
from apps.agents.services.review_growth import (
    extra_unlock_attrs,
    get_review_growth_status,
    review_threshold_just_crossed,
    sanitize_qr_config,
    sanitize_review_growth_config,
    should_show_popup,
    should_show_upgrade_cta,
    should_show_upgrade_progress,
)
from apps.agents.views.dashboard import PlanFeatureProxy, _resolve_agent_plan
from apps.home.models import SiteSetting


class ReviewGrowthConfigTests(SimpleTestCase):
    def test_sanitize_clamps_delays_and_filters_features(self):
        cfg = sanitize_review_growth_config({
            'popup_delay_ms': 50,
            'review_scroll_delay_ms': 99999,
            'min_reviews': 0,
            'unlock_feature_slugs': ['sales_insights', 'not_a_feature', 'view_reviews'],
            'eligible_plans': ['starter', 'bogus'],
        })
        self.assertEqual(cfg['popup_delay_ms'], 1500)
        self.assertEqual(cfg['review_scroll_delay_ms'], 5000)
        self.assertEqual(cfg['min_reviews'], 1)
        self.assertEqual(cfg['unlock_feature_slugs'], ['sales_insights', 'view_reviews'])
        self.assertEqual(cfg['eligible_plans'], ['starter'])
        self.assertTrue(sanitize_review_growth_config({}).get('visibility_section_enabled'))
        self.assertFalse(sanitize_review_growth_config({
            'visibility_section_enabled': 'off',
        })['visibility_section_enabled'])

    def test_qr_config_defaults(self):
        cfg = sanitize_qr_config({'enabled': 'off', 'allow_download': 'on'})
        self.assertFalse(cfg['enabled'])
        self.assertTrue(cfg['allow_download'])

    def test_review_threshold_just_crossed(self):
        with patch('apps.agents.services.review_growth.get_review_growth_config', return_value={
            'enabled': True,
            'min_reviews': 3,
        }):
            self.assertFalse(review_threshold_just_crossed(2, 2))
            self.assertTrue(review_threshold_just_crossed(2, 3))
            self.assertFalse(review_threshold_just_crossed(3, 4))
            self.assertFalse(review_threshold_just_crossed(1, 5))

    def test_sanitize_upgrade_cta_toggle(self):
        cfg = sanitize_review_growth_config({'upgrade_cta_enabled': 'off'})
        self.assertFalse(cfg['upgrade_cta_enabled'])
        cfg_on = sanitize_review_growth_config({'upgrade_cta_enabled': 'on'})
        self.assertTrue(cfg_on['upgrade_cta_enabled'])

    def test_sanitize_starter_unlock_toggle(self):
        cfg = sanitize_review_growth_config({'starter_unlock_enabled': 'off'})
        self.assertFalse(cfg['starter_unlock_enabled'])
        cfg_on = sanitize_review_growth_config({'starter_unlock_enabled': 'on'})
        self.assertTrue(cfg_on['starter_unlock_enabled'])

    def test_sanitize_upgrade_pricing(self):
        cfg = sanitize_review_growth_config({
            'upgrade_price_enabled': 'off',
            'upgrade_promo_price': 4500,
            'upgrade_full_price': 6500,
            'upgrade_show_full_price': 'off',
        })
        self.assertFalse(cfg['upgrade_price_enabled'])
        self.assertEqual(cfg['upgrade_promo_price'], 4500)
        self.assertEqual(cfg['upgrade_full_price'], 6500)
        self.assertFalse(cfg['upgrade_show_full_price'])

    def test_gst_inclusive(self):
        from apps.agents.services.review_growth import gst_inclusive
        self.assertEqual(gst_inclusive(4999), 5899)
        self.assertEqual(gst_inclusive(6999), 8259)


class BrandedQrPngTests(SimpleTestCase):
    def test_generate_png_header(self):
        agent = MagicMock()
        agent.id = 1
        agent.fullname = 'Test Agent'
        agent.get_primary_profile.return_value = MagicMock(display_name='Test Agent')
        with patch('apps.agents.services.qr_branded.SiteSetting.get_value', return_value='PadosiAgent'):
            png = generate_branded_qr_png(agent, 'reviews', 'https://example.com/profile/x/?focus=reviews')
        self.assertTrue(png.startswith(b'\x89PNG\r\n\x1a\n'))
        self.assertGreater(len(png), 500)


class ReviewGrowthUnlockTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user('starter_agent', 'starter@example.com', 'pw12345!')
        self.agent = Agent.objects.create(
            user=self.user,
            fullname='Starter Agent',
            email='starter@example.com',
            mobile='9876500001',
            status='active',
            plan_type='starter',
        )
        self.profile = AgentProfile.objects.create(
            agent=self.agent,
            slug='starter-agent',
            display_name='Starter Agent',
            is_profile_visible=True,
            is_card_visible=True,
        )
        SiteSetting.set_value('qr_service_config', {'enabled': True, 'allow_download': True}, 'pricing')
        SiteSetting.set_value('review_growth_config', sanitize_review_growth_config({
            'enabled': True,
            'min_reviews': 2,
            'eligible_plans': ['starter'],
            'unlock_feature_slugs': ['sales_insights', 'view_reviews'],
        }), 'pricing')
        SiteSetting.set_value('plan_features_config', {
            'starter': ['dashboard_stats', 'edit_profile', 'lead_management'],
            'professional': [
                'dashboard_stats', 'sales_insights',
                'visibility_aio', 'visibility_geo', 'visibility_seo', 'visibility_priority_ranking',
            ],
        }, 'pricing')

    def _add_reviews(self, count):
        for i in range(count):
            AgentReview.objects.create(
                agent=self.agent,
                reviewer_name=f'Reviewer {i}',
                reviewer_email=f'rev{i}@example.com',
                rating=5,
                review='Great neighbourhood agent.',
                is_approved=True,
            )

    def test_popup_shows_below_threshold_not_after(self):
        self.assertTrue(should_show_popup(self.agent))
        self._add_reviews(2)
        self.assertFalse(should_show_popup(self.agent))

    def test_upgrade_cta_only_for_starter_at_threshold(self):
        self.assertFalse(should_show_upgrade_cta(self.agent))
        self.assertTrue(should_show_upgrade_progress(self.agent))
        self._add_reviews(2)
        self.assertTrue(should_show_upgrade_cta(self.agent))
        self.assertFalse(should_show_upgrade_progress(self.agent))
        status = get_review_growth_status(self.agent)
        self.assertTrue(status['upgrade_ready'])
        self.assertEqual(status['review_count'], 2)
        self.agent.plan_type = 'professional'
        self.agent.save(update_fields=['plan_type'])
        self.assertFalse(should_show_upgrade_cta(self.agent))
        self.assertFalse(should_show_upgrade_progress(self.agent))

    def test_unlock_is_additive_and_does_not_remove_base(self):
        base = PlanFeatureProxy(['dashboard_stats', 'lead_management'])
        self.assertFalse(base.show_sales_insights)
        self._add_reviews(2)
        extra = extra_unlock_attrs(self.agent)
        self.assertIn('show_sales_insights', extra)
        wrapped = overlay_plan(base, extra)
        self.assertTrue(wrapped.show_sales_insights)
        self.assertTrue(wrapped.show_performance_stats)

    def test_resolve_plan_adds_unlocks_without_visibility(self):
        self._add_reviews(2)
        plan = _resolve_agent_plan('starter', agent=self.agent)
        self.assertTrue(plan.show_recent_leads)
        self.assertTrue(plan.show_sales_insights)
        extra = extra_unlock_attrs(self.agent)
        self.assertTrue(extra)
        wrapped = overlay_plan(plan, extra)
        self.assertFalse(wrapped.show_visibility_aio)

    def test_resolve_honors_saved_starter_and_keeps_independent_locks(self):
        plan = _resolve_agent_plan('starter', agent=self.agent)
        self.assertTrue(plan.show_performance_stats)
        self.assertTrue(plan.show_edit_profile_full)
        self.assertTrue(plan.show_recent_leads)
        self.assertTrue(plan.show_edit_profile_professional)
        self.assertFalse(plan.show_agent_certificate)
        self.assertFalse(plan.show_claim_support)
        self.assertFalse(plan.show_profile_section)


class AgentQrAndCardTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user('qr_agent', 'qr@example.com', 'pw12345!')
        self.agent = Agent.objects.create(
            user=self.user,
            fullname='QR Agent',
            email='qr@example.com',
            mobile='9876500002',
            status='active',
            plan_type='starter',
        )
        self.profile = AgentProfile.objects.create(
            agent=self.agent,
            slug='qr-agent',
            display_name='QR Agent',
            is_profile_visible=True,
            is_card_visible=True,
        )
        SiteSetting.set_value('qr_service_config', {'enabled': True, 'allow_download': True}, 'pricing')

    def test_target_urls_encode_profile_card_and_reviews(self):
        request = self.client.get('/').wsgi_request
        profile_url = build_qr_target_url(request, self.agent, 'profile')
        card_url = build_qr_target_url(request, self.agent, 'card')
        reviews_url = build_qr_target_url(request, self.agent, 'reviews')
        self.assertIn('/profile/qr-agent/', profile_url)
        self.assertIn('/card/qr-agent/', card_url)
        self.assertIn('/review/qr-agent/', reviews_url)
        self.assertNotIn('focus=reviews', reviews_url)

    def test_public_qr_png_when_enabled(self):
        url = reverse('agents:agent_public_qr_image', kwargs={'slug': 'qr-agent', 'qr_type': 'profile'})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'image/png')
        self.assertGreater(len(response.content), 200)

    def test_public_qr_404_when_disabled(self):
        SiteSetting.set_value('qr_service_config', sanitize_qr_config({'enabled': False}), 'pricing')
        url = reverse('agents:agent_public_qr_image', kwargs={'slug': 'qr-agent', 'qr_type': 'card'})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_download_requires_login(self):
        url = reverse('agents:agent_qr_download', kwargs={'qr_type': 'reviews'})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.client.force_login(self.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment', response['Content-Disposition'])

    def test_card_page_200_and_missing_slug_404(self):
        response = self.client.get(reverse('agents:agent_public_card', args=['qr-agent']))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'QR Agent')
        missing = self.client.get(reverse('agents:agent_public_card', args=['no-such-agent']))
        self.assertEqual(missing.status_code, 404)

    def test_review_card_page_200_and_missing_slug_404(self):
        response = self.client.get(reverse('agents:agent_review_card', args=['qr-agent']))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'QR Agent')
        self.assertContains(response, 'Your Experience Matters')
        self.assertContains(response, 'PadosiAgent logo')
        missing = self.client.get(reverse('agents:agent_review_card', args=['no-such-agent']))
        self.assertEqual(missing.status_code, 404)

    def test_public_review_page_200(self):
        response = self.client.get(reverse('agents:agent_public_review', args=['qr-agent']))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Rate & Review')
        self.assertContains(response, 'QR Agent')

    def test_profile_focus_reviews_renders_scroll_hook(self):
        response = self.client.get(
            reverse('agents:agent_public_profile', args=['qr-agent']) + '?focus=reviews'
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="reviews-section"')
        self.assertContains(response, 'data-scroll-delay')
        self.assertContains(response, 'focus')
