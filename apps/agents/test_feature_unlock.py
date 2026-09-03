from django.test import SimpleTestCase

from apps.agents.services.feature_unlock import (
    OverlayPlan,
    evaluate_unlock_rules,
    filter_overlay_extras,
    needs_activity_eval_for_directory,
    overlay_plan,
    remove_plan_only_unlock_rule,
    resolve_plan_feature_slugs,
    resolve_plan_entitlements,
    load_plan_features_config,
    sanitize_unlock_rules,
    toggle_plan_feature,
    upsert_plan_unlock_rule,
    with_feature_defaults,
)
from apps.agents.views.dashboard import PlanFeatureProxy, _resolve_agent_plan


CERT_RULE = {
    'id': 'r1',
    'enabled': True,
    'feature': 'edit_profile_certifications',
    'plans': ['starter'],
    'match': 'all',
    'conditions': [
        {'metric': 'reviews', 'op': 'gte', 'value': 10},
        {'metric': 'referrals', 'op': 'gte', 'value': 5},
    ],
}


class FakePlan:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class FeatureUnlockEvaluatorTests(SimpleTestCase):
    def test_and_passes_when_all_metrics_met(self):
        extra = evaluate_unlock_rules(
            agent=None,
            plan_slug='starter',
            metrics={'reviews': 10, 'referrals': 5},
            rules=[CERT_RULE],
        )
        self.assertIn('show_agent_certificate', extra)

    def test_and_fails_when_one_metric_is_short(self):
        extra = evaluate_unlock_rules(
            agent=None,
            plan_slug='starter',
            metrics={'reviews': 10, 'referrals': 2},
            rules=[CERT_RULE],
        )
        self.assertEqual(extra, set())

    def test_or_passes_if_any_condition_passes(self):
        rule = dict(CERT_RULE, match='any')
        extra = evaluate_unlock_rules(
            agent=None,
            plan_slug='starter',
            metrics={'reviews': 10, 'referrals': 0},
            rules=[rule],
        )
        self.assertIn('show_agent_certificate', extra)

    def test_rule_ignored_when_plan_slug_not_in_plans(self):
        extra = evaluate_unlock_rules(
            agent=None,
            plan_slug='professional',
            metrics={'reviews': 50, 'referrals': 50},
            rules=[CERT_RULE],
        )
        self.assertEqual(extra, set())

    def test_disabled_rule_ignored(self):
        rule = dict(CERT_RULE, enabled=False)
        extra = evaluate_unlock_rules(
            agent=None,
            plan_slug='starter',
            metrics={'reviews': 50, 'referrals': 50},
            rules=[rule],
        )
        self.assertEqual(extra, set())

    def test_empty_rules_unlock_nothing(self):
        extra = evaluate_unlock_rules(
            agent=None,
            plan_slug='starter',
            metrics={'reviews': 50},
            rules=[],
        )
        self.assertEqual(extra, set())


class OverlayPlanTests(SimpleTestCase):
    def test_overlay_adds_feature_without_removing_plan_features(self):
        base = FakePlan(show_agent_certificate=False, show_performance_stats=True)
        wrapped = overlay_plan(base, {'show_agent_certificate'})
        self.assertTrue(wrapped.show_agent_certificate)
        self.assertTrue(wrapped.show_performance_stats)

    def test_plan_checkbox_feature_stays_on_when_metrics_fail(self):
        base = PlanFeatureProxy(['edit_profile_certifications', 'dashboard_stats'])
        extra = evaluate_unlock_rules(
            agent=None,
            plan_slug='starter',
            metrics={'reviews': 1, 'referrals': 0},
            rules=[CERT_RULE],
        )
        wrapped = overlay_plan(base, extra)
        self.assertTrue(wrapped.show_agent_certificate)
        self.assertTrue(wrapped.show_performance_stats)
        self.assertFalse(wrapped.show_career_timeline)

    def test_overlay_does_not_override_none_fail_open(self):
        self.assertIsNone(overlay_plan(None, {'show_agent_certificate'}))
        self.assertIsNone(_resolve_agent_plan('', agent=object()))
        self.assertIsNone(_resolve_agent_plan(None))

    def test_overlay_skipped_when_no_extras(self):
        base = FakePlan(show_portfolio=False)
        self.assertIs(overlay_plan(base, set()), base)

    def test_overlay_plan_is_truthy(self):
        wrapped = OverlayPlan(FakePlan(show_portfolio=False), {'show_portfolio'})
        self.assertTrue(bool(wrapped))


class DirectoryShortCircuitTests(SimpleTestCase):
    def test_skip_when_already_listed(self):
        base = FakePlan(is_listed_in_directory=True)
        self.assertFalse(needs_activity_eval_for_directory(
            base, 'starter',
            rules=[{
                'enabled': True,
                'feature': 'agent_directory_visibility',
                'plans': ['starter'],
                'match': 'all',
                'conditions': [{'metric': 'reviews', 'op': 'gte', 'value': 1}],
            }],
        ))

    def test_skip_when_no_directory_rule(self):
        base = FakePlan(is_listed_in_directory=False)
        self.assertFalse(needs_activity_eval_for_directory(
            base, 'starter', rules=[CERT_RULE]
        ))

    def test_evaluate_when_locked_and_directory_rule_exists(self):
        base = FakePlan(is_listed_in_directory=False)
        self.assertTrue(needs_activity_eval_for_directory(
            base, 'starter',
            rules=[{
                'enabled': True,
                'feature': 'agent_directory_visibility',
                'plans': ['starter'],
                'match': 'all',
                'conditions': [{'metric': 'reviews', 'op': 'gte', 'value': 1}],
            }],
        ))

    def test_skip_when_base_plan_is_none(self):
        self.assertFalse(needs_activity_eval_for_directory(None, 'starter', rules=[CERT_RULE]))


class SanitizeUnlockRulesTests(SimpleTestCase):
    def test_drops_unknown_metrics_and_empty_rules(self):
        cleaned = sanitize_unlock_rules([
            {
                'feature': 'edit_profile_certifications',
                'plans': ['starter'],
                'match': 'all',
                'enabled': True,
                'conditions': [
                    {'metric': 'not_a_real_metric', 'op': 'gte', 'value': 1},
                ],
            },
            {
                'feature': 'edit_profile_certifications',
                'plans': ['nope'],
                'conditions': [{'metric': 'reviews', 'op': 'gte', 'value': 10}],
            },
        ])
        self.assertEqual(len(cleaned), 1)
        self.assertEqual(cleaned[0]['plans'], ['free_trial', 'starter', 'professional', 'exclusive'])
        self.assertEqual(cleaned[0]['conditions'][0]['value'], 10.0)


SHARED_CONFIG = {
    'free_trial': ['dashboard_stats'],
    'starter': ['dashboard_stats', 'edit_profile', 'edit_profile_basic', 'sales_insights'],
    'professional': ['dashboard_stats', 'lead_management'],
    'exclusive': ['premium_support'],
}


class ResolvePlanFeatureSlugsTests(SimpleTestCase):
    def test_starter_honors_saved_lock_and_unlock(self):
        config = {
            'starter': [
                'dashboard_stats', 'edit_profile', 'lead_management',
                'edit_profile_certifications', 'edit_profile_claim_support',
            ],
        }
        slugs = resolve_plan_feature_slugs('starter', config)
        self.assertIn('dashboard_stats', slugs)
        self.assertIn('lead_management', slugs)
        self.assertIn('edit_profile_certifications', slugs)
        self.assertIn('edit_profile_claim_support', slugs)
        self.assertNotIn('sales_insights', slugs)

    def test_starter_falls_back_to_base_when_unconfigured(self):
        slugs = resolve_plan_feature_slugs('starter', {})
        self.assertIn('dashboard_stats', slugs)
        self.assertIn('sales_insights', slugs)
        self.assertIn('qr_codes', slugs)
        self.assertIn('edit_profile_certifications', slugs)
        self.assertIn('edit_profile_claim_support', slugs)
        self.assertNotIn('lead_management', slugs)

    def test_professional_unlocks_every_feature_when_unconfigured(self):
        slugs = resolve_plan_feature_slugs('professional', {})
        self.assertIn('lead_management', slugs)
        self.assertIn('visibility_aio', slugs)
        self.assertIn('rank_boost_tips', slugs)

    def test_professional_honors_saved_lock(self):
        config = {'professional': ['dashboard_stats', 'edit_profile']}
        slugs = resolve_plan_feature_slugs('professional', config)
        self.assertIn('edit_profile', slugs)
        self.assertNotIn('visibility_aio', slugs)

    def test_starter_proxy_matches_canonical_list(self):
        slugs = resolve_plan_feature_slugs('starter', {})
        proxy = PlanFeatureProxy(slugs)
        self.assertTrue(proxy.show_performance_stats)
        self.assertTrue(proxy.show_sales_insights)
        self.assertTrue(proxy.show_qr_codes)
        self.assertTrue(proxy.show_edit_profile_professional)
        self.assertTrue(proxy.show_agent_certificate)
        self.assertTrue(proxy.show_claim_support)
        self.assertFalse(proxy.show_recent_leads)
        self.assertFalse(proxy.show_profile_section)

    def test_edit_profile_legacy_implies_four_steps_not_nested_sections(self):
        proxy = PlanFeatureProxy(['edit_profile'])
        self.assertTrue(proxy.show_edit_profile_full)
        self.assertTrue(proxy.show_edit_profile_basic)
        self.assertTrue(proxy.show_edit_profile_professional)
        self.assertTrue(proxy.show_edit_profile_portfolio)
        self.assertTrue(proxy.show_edit_profile_additional)
        self.assertFalse(proxy.show_agent_certificate)
        self.assertFalse(proxy.show_claim_support)

    def test_lock_basic_step_sticks_while_edit_profile_stays_on(self):
        config = {
            'starter': list(resolve_plan_feature_slugs('starter', {})),
            'professional': [],
            'free_trial': [],
            'exclusive': [],
        }
        updated = toggle_plan_feature(config, 'starter', 'edit_profile_basic', locked=True)
        self.assertNotIn('edit_profile_basic', updated['starter'])
        self.assertIn('edit_profile', updated['starter'])
        self.assertIn('edit_profile_professional', updated['starter'])
        proxy = PlanFeatureProxy(resolve_plan_feature_slugs('starter', updated))
        self.assertFalse(proxy.show_edit_profile_basic)
        self.assertTrue(proxy.show_edit_profile_professional)
        self.assertTrue(proxy.show_edit_profile_full)

    def test_unlock_basic_step_restores_only_that_step(self):
        config = {
            'starter': [
                'edit_profile', 'edit_profile_professional',
                'edit_profile_portfolio', 'edit_profile_additional',
            ],
            'professional': [],
            'free_trial': [],
            'exclusive': [],
        }
        updated = toggle_plan_feature(config, 'starter', 'edit_profile_basic', locked=False)
        self.assertIn('edit_profile_basic', updated['starter'])
        self.assertIn('edit_profile', updated['starter'])
        proxy = PlanFeatureProxy(resolve_plan_feature_slugs('starter', updated))
        self.assertTrue(proxy.show_edit_profile_basic)
        self.assertTrue(proxy.show_edit_profile_professional)

    def test_lock_all_steps_drops_edit_profile_parent(self):
        config = {
            'starter': list(resolve_plan_feature_slugs('starter', {})),
            'professional': [],
            'free_trial': [],
            'exclusive': [],
        }
        for step in (
            'edit_profile_basic',
            'edit_profile_professional',
            'edit_profile_portfolio',
            'edit_profile_additional',
        ):
            config = toggle_plan_feature(config, 'starter', step, locked=True)
        self.assertNotIn('edit_profile', config['starter'])
        proxy = PlanFeatureProxy(resolve_plan_feature_slugs('starter', config))
        self.assertFalse(proxy.show_edit_profile_full)
        self.assertFalse(proxy.show_edit_profile_basic)

    def test_lock_dashboard_stats_sticks_on_starter(self):
        config = {
            'starter': list(resolve_plan_feature_slugs('starter', {})),
            'professional': ['dashboard_stats'],
            'free_trial': [],
            'exclusive': [],
        }
        updated = toggle_plan_feature(config, 'starter', 'dashboard_stats', locked=True)
        self.assertNotIn('dashboard_stats', updated['starter'])
        slugs = resolve_plan_feature_slugs('starter', updated)
        self.assertNotIn('dashboard_stats', slugs)
        proxy = PlanFeatureProxy(slugs)
        self.assertFalse(proxy.show_performance_stats)
        self.assertTrue(proxy.show_qr_codes)

    def test_lock_certificate_sticks_while_edit_profile_stays_on(self):
        config = {
            'starter': list(resolve_plan_feature_slugs('starter', {})),
            'professional': [],
            'free_trial': [],
            'exclusive': [],
        }
        updated = toggle_plan_feature(config, 'starter', 'edit_profile_certifications', locked=True)
        self.assertNotIn('edit_profile_certifications', updated['starter'])
        self.assertIn('edit_profile', updated['starter'])
        proxy = PlanFeatureProxy(resolve_plan_feature_slugs('starter', updated))
        self.assertFalse(proxy.show_agent_certificate)
        self.assertTrue(proxy.show_edit_profile_professional)

    def test_lock_on_missing_plan_list_starts_from_defaults(self):
        updated = toggle_plan_feature({}, 'starter', 'dashboard_stats', locked=True)
        self.assertNotIn('dashboard_stats', updated['starter'])
        self.assertIn('edit_profile', updated['starter'])
        self.assertIn('qr_codes', updated['starter'])


class PlanFeatureToggleTests(SimpleTestCase):
    def test_lock_starter_does_not_change_other_plans(self):
        updated = toggle_plan_feature(SHARED_CONFIG, 'starter', 'sales_insights', locked=True)
        self.assertNotIn('sales_insights', updated['starter'])
        self.assertEqual(updated['free_trial'], ['dashboard_stats'])
        self.assertEqual(updated['professional'], ['dashboard_stats', 'lead_management'])
        self.assertEqual(updated['exclusive'], ['premium_support'])

    def test_unlock_restores_feature_on_that_slug_only(self):
        locked = toggle_plan_feature(SHARED_CONFIG, 'starter', 'sales_insights', locked=True)
        restored = toggle_plan_feature(locked, 'starter', 'sales_insights', locked=False)
        self.assertIn('sales_insights', restored['starter'])
        self.assertEqual(restored['professional'], SHARED_CONFIG['professional'])

    def test_lock_edit_profile_drops_child_keys(self):
        updated = toggle_plan_feature(SHARED_CONFIG, 'starter', 'edit_profile', locked=True)
        self.assertNotIn('edit_profile', updated['starter'])
        self.assertNotIn('edit_profile_basic', updated['starter'])
        self.assertIn('dashboard_stats', updated['starter'])

    def test_unlock_edit_profile_restores_child_keys(self):
        locked = toggle_plan_feature(SHARED_CONFIG, 'starter', 'edit_profile', locked=True)
        restored = toggle_plan_feature(locked, 'starter', 'edit_profile', locked=False)
        self.assertIn('edit_profile', restored['starter'])
        for child in (
            'edit_profile_basic',
            'edit_profile_professional',
            'edit_profile_portfolio',
            'edit_profile_additional',
            'edit_profile_certifications',
            'edit_profile_claim_support',
            'manage_portfolio',
            'edit_profile_professional_bio',
        ):
            self.assertIn(child, restored['starter'])

    def test_unlock_professional_restores_license_and_stats(self):
        updated = toggle_plan_feature(
            SHARED_CONFIG, 'starter', 'edit_profile_professional', locked=False,
        )
        self.assertIn('edit_profile_professional', updated['starter'])
        self.assertIn('edit_profile_certifications', updated['starter'])
        self.assertIn('edit_profile_claim_support', updated['starter'])
        self.assertIn('edit_profile', updated['starter'])

    def test_lock_professional_drops_nested_license_and_stats(self):
        unlocked = toggle_plan_feature(
            SHARED_CONFIG, 'starter', 'edit_profile_professional', locked=False,
        )
        locked = toggle_plan_feature(
            unlocked, 'starter', 'edit_profile_professional', locked=True,
        )
        self.assertNotIn('edit_profile_professional', locked['starter'])
        self.assertNotIn('edit_profile_certifications', locked['starter'])
        self.assertNotIn('edit_profile_claim_support', locked['starter'])
        self.assertIn('edit_profile', locked['starter'])

    def test_source_config_is_not_mutated(self):
        original = list(SHARED_CONFIG['starter'])
        toggle_plan_feature(SHARED_CONFIG, 'starter', 'sales_insights', locked=True)
        self.assertEqual(SHARED_CONFIG['starter'], original)


class PlanUnlockRuleUpsertTests(SimpleTestCase):
    def test_lock_with_conditions_splits_multi_plan_rule(self):
        rules = [{
            'id': 'shared',
            'enabled': True,
            'feature': 'sales_insights',
            'plans': ['starter', 'professional'],
            'match': 'all',
            'conditions': [{'metric': 'reviews', 'op': 'gte', 'value': 3}],
        }]
        updated = upsert_plan_unlock_rule(
            rules, 'starter', 'sales_insights',
            [{'metric': 'leads', 'op': 'gte', 'value': 5}],
            match='all',
        )
        by_plans = {tuple(rule['plans']): rule for rule in updated}
        self.assertEqual(by_plans[('professional',)]['conditions'][0]['metric'], 'reviews')
        self.assertEqual(by_plans[('starter',)]['conditions'][0]['metric'], 'leads')
        self.assertEqual(by_plans[('starter',)]['conditions'][0]['value'], 5.0)

    def test_unlock_removes_rule_only_for_that_plan_feature(self):
        rules = [
            {
                'id': 'only_starter',
                'enabled': True,
                'feature': 'sales_insights',
                'plans': ['starter'],
                'match': 'all',
                'conditions': [{'metric': 'reviews', 'op': 'gte', 'value': 2}],
            },
            {
                'id': 'shared',
                'enabled': True,
                'feature': 'sales_insights',
                'plans': ['starter', 'professional'],
                'match': 'all',
                'conditions': [{'metric': 'leads', 'op': 'gte', 'value': 1}],
            },
        ]
        kept = remove_plan_only_unlock_rule(rules, 'starter', 'sales_insights')
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]['id'], 'shared')
        self.assertEqual(kept[0]['plans'], ['starter', 'professional'])


class AdminLockPreviewDoesNotChangeProxyTests(SimpleTestCase):
    def test_plan_feature_proxy_still_fail_open_and_additive(self):
        proxy = PlanFeatureProxy(['dashboard_stats'])
        self.assertTrue(proxy.show_performance_stats)
        self.assertFalse(proxy.show_sales_insights)
        self.assertIsNone(overlay_plan(None, {'show_sales_insights'}))
        wrapped = overlay_plan(proxy, {'show_sales_insights'})
        self.assertTrue(wrapped.show_sales_insights)
        self.assertTrue(wrapped.show_performance_stats)


class LeadPreferencesPlanDefaultTests(SimpleTestCase):
    def test_starter_stays_locked_until_admin_enables_it(self):
        config = {
            'free_trial': ['dashboard_stats'],
            'starter': ['dashboard_stats', 'lead_management'],
            'professional': ['dashboard_stats'],
            'exclusive': ['dashboard_stats'],
        }
        enabled = with_feature_defaults('starter', config['starter'], config)
        self.assertNotIn('lead_preferences', enabled)
        proxy = PlanFeatureProxy(enabled)
        self.assertFalse(proxy.show_lead_preferences)
        self.assertTrue(proxy.show_recent_leads)
        self.assertFalse(proxy.show_new_business_leads)
        self.assertFalse(proxy.show_lead_portfolio_analysis)
        self.assertFalse(proxy.show_lead_claims_support)

    def test_professional_respects_explicit_empty_list(self):
        config = {
            'starter': ['dashboard_stats'],
            'professional': [],
            'free_trial': [],
            'exclusive': [],
        }
        enabled = with_feature_defaults('professional', config['professional'], config)
        self.assertEqual(enabled, [])
        proxy = PlanFeatureProxy(enabled)
        self.assertFalse(proxy.show_rank_boost_tips)
        self.assertFalse(proxy.show_qr_codes)
        self.assertFalse(proxy.show_lead_preferences)

    def test_professional_unlock_sticks_for_header_and_qr_features(self):
        config = {
            'starter': ['dashboard_stats'],
            'professional': [],
            'free_trial': [],
            'exclusive': [],
        }
        for feature in (
            'rank_boost_tips',
            'view_public_profile',
            'qr_codes',
            'manage_portfolio',
            'lead_preferences',
        ):
            config = toggle_plan_feature(config, 'professional', feature, locked=False)
            self.assertIn(feature, config['professional'])
            proxy = PlanFeatureProxy(resolve_plan_entitlements('professional', config))
            if feature == 'rank_boost_tips':
                self.assertTrue(proxy.show_rank_boost_tips)
            elif feature == 'view_public_profile':
                self.assertTrue(proxy.show_view_public_profile_btn)
            elif feature == 'qr_codes':
                self.assertTrue(proxy.show_qr_codes)
            elif feature == 'manage_portfolio':
                self.assertTrue(proxy.show_portfolio)
            elif feature == 'lead_preferences':
                self.assertTrue(proxy.show_lead_preferences)
            config = toggle_plan_feature(config, 'professional', feature, locked=True)

    def test_professional_gets_lead_preferences_from_canonical_when_unconfigured(self):
        enabled = resolve_plan_entitlements('professional', {})
        self.assertIn('lead_preferences', enabled)
        self.assertIn('qr_codes', enabled)
        self.assertIn('rank_boost_tips', enabled)

    def test_admin_can_unlock_starter_lead_preferences(self):
        locked = {
            'starter': ['dashboard_stats'],
            'professional': ['dashboard_stats', 'lead_preferences'],
            'free_trial': [],
            'exclusive': ['lead_preferences'],
        }
        updated = toggle_plan_feature(locked, 'starter', 'lead_preferences', locked=False)
        self.assertIn('lead_preferences', updated['starter'])
        self.assertIn('receive_leads', updated['starter'])
        self.assertIn('lead_portfolio_analysis', updated['starter'])
        self.assertIn('lead_claims_support', updated['starter'])
        self.assertIn('lead_preferences', updated['professional'])

    def test_admin_can_lock_professional_lead_preferences(self):
        config = {
            'starter': ['dashboard_stats'],
            'professional': [
                'dashboard_stats', 'lead_preferences',
                'receive_leads', 'lead_portfolio_analysis', 'lead_claims_support',
            ],
            'free_trial': [],
            'exclusive': ['lead_preferences'],
        }
        updated = toggle_plan_feature(config, 'professional', 'lead_preferences', locked=True)
        self.assertNotIn('lead_preferences', updated['professional'])
        self.assertNotIn('receive_leads', updated['professional'])
        self.assertNotIn('lead_portfolio_analysis', updated['professional'])
        self.assertNotIn('lead_claims_support', updated['professional'])
        enabled = with_feature_defaults('professional', updated['professional'], updated)
        self.assertNotIn('lead_preferences', enabled)

    def test_lock_one_lead_item_keeps_parent_and_siblings(self):
        config = {
            'starter': [
                'lead_preferences', 'receive_leads',
                'lead_portfolio_analysis', 'lead_claims_support',
            ],
            'professional': ['lead_preferences'],
            'free_trial': [],
            'exclusive': [],
        }
        updated = toggle_plan_feature(config, 'starter', 'lead_portfolio_analysis', locked=True)
        self.assertIn('lead_preferences', updated['starter'])
        self.assertIn('receive_leads', updated['starter'])
        self.assertNotIn('lead_portfolio_analysis', updated['starter'])
        self.assertIn('lead_claims_support', updated['starter'])

    def test_unlock_lead_item_also_unlocks_parent_section(self):
        config = {
            'starter': ['dashboard_stats'],
            'professional': ['lead_preferences'],
            'free_trial': [],
            'exclusive': [],
        }
        updated = toggle_plan_feature(config, 'starter', 'receive_leads', locked=False)
        self.assertIn('receive_leads', updated['starter'])
        self.assertIn('lead_preferences', updated['starter'])
        self.assertNotIn('lead_portfolio_analysis', updated['starter'])


class FilterOverlayExtrasTests(SimpleTestCase):
    def test_review_overlay_dropped_when_admin_locked_feature(self):
        config = {
            'starter': ['dashboard_stats', 'edit_profile', 'lead_management'],
            'professional': ['dashboard_stats'],
            'free_trial': [],
            'exclusive': [],
        }
        extras = {
            'show_lead_preferences',
            'show_new_business_leads',
            'show_recent_leads',
        }
        filtered = filter_overlay_extras('starter', extras, config)
        self.assertNotIn('show_lead_preferences', filtered)
        self.assertNotIn('show_new_business_leads', filtered)
        self.assertIn('show_recent_leads', filtered)

    def test_overlay_kept_when_feature_enabled_in_saved_plan(self):
        config = {
            'starter': ['dashboard_stats', 'lead_preferences', 'receive_leads'],
            'professional': [],
            'free_trial': [],
            'exclusive': [],
        }
        extras = {'show_lead_preferences', 'show_new_business_leads'}
        filtered = filter_overlay_extras('starter', extras, config)
        self.assertEqual(filtered, extras)

    def test_overlay_unfiltered_when_plan_has_no_saved_list(self):
        extras = {'show_lead_preferences'}
        filtered = filter_overlay_extras('starter', extras, {})
        self.assertEqual(filtered, extras)

