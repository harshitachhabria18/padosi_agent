import json
import logging
from typing import Dict, Any, List, Optional, Set, Union
from decimal import Decimal, InvalidOperation
from sqlalchemy.orm import Session
from sqlalchemy import func
from fastapi import HTTPException, status

from fastapi_app.models.agent import Agent
from fastapi_app.models.agent_profile import AgentProfile
from fastapi_app.models.agent_lead import AgentLead
from fastapi_app.models.agent_review import AgentReview
from fastapi_app.models.agent_subscription import AgentSubscription
from fastapi_app.models.agent_insurance_segment import AgentInsuranceSegment
from fastapi_app.models.agent_portfolio import AgentPortfolio
from fastapi_app.models.agent_product_expertise import AgentProductExpertise
from fastapi_app.models.agent_lead_preference import AgentLeadPreference
from fastapi_app.models.agent_serviceable_city import AgentServiceableCity
from fastapi_app.models.agent_performance_stat import AgentPerformanceStat
from fastapi_app.models.referral_code import ReferralCode
from fastapi_app.models.referral_usage import ReferralUsage
from fastapi_app.models.site_setting import SiteSetting

logger = logging.getLogger(__name__)

PLAN_SLUGS = ('free_trial', 'starter', 'professional', 'exclusive')

SLUG_NORMALISE = {
    'basic': 'starter',
    'starter': 'starter',
    'standard': 'starter',
    'starters_plan': 'starter',
    'starters-plan': 'starter',
    'free trial': 'free_trial',
    'free_trial': 'free_trial',
    'professional': 'professional',
    'professionals_plan': 'professional',
    'professionals-plan': 'professional',
    'pro': 'professional',
    'exclusive': 'exclusive',
    'exclusive_partner': 'exclusive',
    'exclusive_partner_plan': 'exclusive',
    'elite': 'starter',
    'eliting_plan': 'starter',
}

EDIT_PROFILE_CHILD_FEATURES = (
    'edit_profile_basic',
    'edit_profile_professional',
    'edit_profile_portfolio',
    'edit_profile_additional',
)

EDIT_PROFILE_PROFESSIONAL_CHILD_FEATURES = (
    'edit_profile_certifications',
    'edit_profile_claim_support',
)

EDIT_PROFILE_PORTFOLIO_CHILD_FEATURES = (
    'manage_portfolio',
    'edit_profile_companies',
)

EDIT_PROFILE_ADDITIONAL_CHILD_FEATURES = (
    'upload_achievements',
    'edit_profile_social_media',
    'edit_profile_professional_bio',
)

LEAD_PREFERENCE_CHILD_FEATURES = (
    'receive_leads',
    'lead_portfolio_analysis',
    'lead_claims_support',
)

FEATURE_PARENTS = {
    'edit_profile_basic': ('edit_profile',),
    'edit_profile_professional': ('edit_profile',),
    'edit_profile_portfolio': ('edit_profile',),
    'edit_profile_additional': ('edit_profile',),
    'edit_profile_certifications': ('edit_profile_professional', 'edit_profile'),
    'edit_profile_claim_support': ('edit_profile_professional', 'edit_profile'),
    'manage_portfolio': ('edit_profile_portfolio', 'edit_profile'),
    'edit_profile_companies': ('edit_profile_portfolio', 'edit_profile'),
    'upload_achievements': ('edit_profile_additional', 'edit_profile'),
    'edit_profile_social_media': ('edit_profile_additional', 'edit_profile'),
    'edit_profile_professional_bio': ('edit_profile_additional', 'edit_profile'),
    'edit_profile_career_timeline': ('edit_profile_additional', 'edit_profile'),
    'qr_poster_download': ('qr_codes',),
}

STARTER_BASE_FEATURE_SLUGS = (
    'dashboard_stats',
    'sales_insights',
    'rank_boost_tips',
    'view_public_profile',
    'edit_profile',
    'edit_profile_basic',
    'edit_profile_professional',
    'edit_profile_portfolio',
    'edit_profile_additional',
    'edit_profile_certifications',
    'edit_profile_claim_support',
    'manage_portfolio',
    'edit_profile_companies',
    'upload_achievements',
    'edit_profile_social_media',
    'edit_profile_professional_bio',
    'qr_codes',
    'qr_poster_download',
)

FEATURE_ATTR_MAP = {
    'dashboard_stats': ['show_performance_stats'],
    'lead_management': ['show_recent_leads'],
    'legacy_lead_status': ['show_lead_status'],
    'sales_insights': ['show_sales_insights'],
    'rank_boost_tips': ['show_rank_boost_tips'],
    'view_public_profile': ['show_view_public_profile_btn'],
    'edit_profile': ['show_edit_profile_full'],
    'edit_profile_basic': ['show_edit_profile_basic'],
    'edit_profile_professional': ['show_edit_profile_professional'],
    'edit_profile_career_timeline': ['show_career_timeline'],
    'edit_profile_social_media': ['show_social_media'],
    'edit_profile_certifications': ['show_agent_certificate'],
    'edit_profile_professional_bio': ['show_professional_bio'],
    'edit_profile_claim_support': ['show_claim_support'],
    'edit_profile_portfolio': ['show_edit_profile_portfolio'],
    'edit_profile_companies': ['show_companies'],
    'edit_profile_additional': ['show_edit_profile_additional'],
    'manage_portfolio': ['show_portfolio'],
    'upload_achievements': ['show_achievement'],
    'view_reviews': ['show_review_management'],
    'public_profile': ['show_profile_section'],
    'agent_directory_visibility': ['is_listed_in_directory'],
    'receive_leads': ['show_new_business_leads'],
    'lead_preferences': ['show_lead_preferences'],
    'lead_portfolio_analysis': ['show_lead_portfolio_analysis'],
    'lead_claims_support': ['show_lead_claims_support'],
    'premium_support': ['premium_priority_support'],
    'visibility_aio': ['show_visibility_aio'],
    'visibility_geo': ['show_visibility_geo'],
    'visibility_seo': ['show_visibility_seo'],
    'visibility_priority_ranking': ['show_visibility_priority_ranking'],
    'qr_codes': ['show_qr_codes'],
    'qr_poster_download': ['show_qr_poster_download'],
}

FEATURE_LABELS = {
    'dashboard_stats': 'Dashboard Performance & Stats',
    'lead_management': 'Lead Management & Recent Leads',
    'sales_insights': 'Sales Insights Widget',
    'rank_boost_tips': 'Rank Boost Tips Modal',
    'view_public_profile': 'View Public Profile Button',
    'edit_profile': 'Edit Profile (Full Access)',
    'edit_profile_basic': 'Edit Profile: Basic Details',
    'edit_profile_professional': 'Edit Profile: Professional Details',
    'edit_profile_portfolio': 'Edit Profile: Product Portfolio',
    'edit_profile_additional': 'Edit Profile: Additional Details',
    'manage_portfolio': 'Product Portfolio / Services',
    'upload_achievements': 'Gallery / Achievement Photos',
    'view_reviews': 'Review Management',
    'public_profile': 'Public Profile Customization',
    'agent_directory_visibility': 'Listed in Find Agents Directory',
    'receive_leads': 'Lead Pref: New Business',
    'lead_preferences': 'Lead Preferences Section',
    'lead_portfolio_analysis': 'Lead Pref: Portfolio Analysis',
    'lead_claims_support': 'Lead Pref: Claims Support',
    'edit_profile_certifications': 'Agent Certificate',
    'edit_profile_career_timeline': 'Career Timeline',
    'edit_profile_professional_bio': 'Professional Bio',
    'edit_profile_social_media': 'Social Media Links',
    'edit_profile_claim_support': 'Claim Support',
    'edit_profile_companies': 'Companies Represented',
    'legacy_lead_status': 'Lead Status',
    'visibility_aio': 'Visibility: AIO',
    'visibility_geo': 'Visibility: GEO',
    'visibility_seo': 'Visibility: SEO',
    'visibility_priority_ranking': 'Visibility: Priority Ranking',
    'qr_codes': 'QR Code Service',
    'qr_poster_download': 'QR Poster Download',
}

NUMERIC_OPS = ('gte', 'gt', 'lte', 'lt', 'eq')
BOOL_OPS = ('eq', 'neq')
SEGMENT_CHOICES = ('health', 'life', 'motor', 'sme')

METRIC_CATALOG = {
    'reviews': {'label': 'Reviews', 'type': 'number', 'operators': NUMERIC_OPS, 'default_op': 'gte'},
    'leads': {'label': 'Leads', 'type': 'number', 'operators': NUMERIC_OPS, 'default_op': 'gte'},
    'total_leads': {'label': 'Total Leads', 'type': 'number', 'operators': NUMERIC_OPS, 'default_op': 'gte'},
    'closed_leads': {'label': 'Closed Leads', 'type': 'number', 'operators': NUMERIC_OPS, 'default_op': 'gte'},
    'referrals': {'label': 'Referrals', 'type': 'number', 'operators': NUMERIC_OPS, 'default_op': 'gte'},
    'profile_completion': {'label': 'Profile Completion %', 'type': 'number', 'operators': NUMERIC_OPS, 'default_op': 'gte'},
    'irdai_certificate': {'label': 'IRDAI Certificate', 'type': 'boolean', 'operators': BOOL_OPS, 'default_op': 'eq'},
    'amfi_certificate': {'label': 'AMFI Certificate', 'type': 'boolean', 'operators': BOOL_OPS, 'default_op': 'eq'},
    'experience': {'label': 'Experience (years)', 'type': 'number', 'operators': NUMERIC_OPS, 'default_op': 'gte'},
    'client_base': {'label': 'Client Base', 'type': 'number', 'operators': NUMERIC_OPS, 'default_op': 'gte'},
    'claim_settle_rate': {'label': 'Claim Settle Rate %', 'type': 'number', 'operators': NUMERIC_OPS, 'default_op': 'gte'},
    'total_claim_amount': {'label': 'Total Claim Amount (₹)', 'type': 'number', 'operators': NUMERIC_OPS, 'default_op': 'gte'},
    'portfolio_products': {'label': 'Product Portfolio (count)', 'type': 'number', 'operators': NUMERIC_OPS, 'default_op': 'gte'},
    'portfolio_segments': {'label': 'Product Portfolio Segments (count)', 'type': 'number', 'operators': NUMERIC_OPS, 'default_op': 'gte'},
    'portfolio_segment': {'label': 'Product Portfolio Segment', 'type': 'segment', 'operators': BOOL_OPS, 'default_op': 'eq'},
}

def normalize_plan_slug(plan_type: Optional[str]) -> str:
    if not plan_type:
        return ''
    pt = str(plan_type).strip().lower().replace(' ', '_').replace('-', '_')
    return SLUG_NORMALISE.get(pt, pt)

def _to_number(value: Any, default: float = 0.0) -> float:
    if value is None or value == '':
        return default
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError, InvalidOperation):
        return default

def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in ('1', 'true', 'yes', 'on')

def _compare(actual: Any, op: str, expected: Any, metric_type: str) -> bool:
    op = (op or 'eq').lower()
    if metric_type == 'boolean':
        actual_b = _to_bool(actual)
        expected_b = _to_bool(expected)
        if op == 'neq':
            return actual_b != expected_b
        return actual_b == expected_b

    if metric_type == 'segment':
        segments = actual if isinstance(actual, (set, list, tuple)) else []
        needle = str(expected or '').strip().lower()
        present = needle in {str(s).strip().lower() for s in segments}
        if op == 'neq':
            return not present
        return present

    actual_n = _to_number(actual)
    expected_n = _to_number(expected)
    if op == 'gt':
        return actual_n > expected_n
    if op == 'lte':
        return actual_n <= expected_n
    if op == 'lt':
        return actual_n < expected_n
    if op == 'eq':
        return actual_n == expected_n
    return actual_n >= expected_n

def canonical_plan_feature_slugs(plan_slug: str) -> List[str]:
    slug = normalize_plan_slug(plan_slug)
    if slug == 'starter':
        return list(STARTER_BASE_FEATURE_SLUGS)
    if slug in ('professional', 'exclusive'):
        return list(FEATURE_ATTR_MAP.keys())
    if slug == 'free_trial':
        return ['dashboard_stats', 'edit_profile', 'edit_profile_basic']
    return []

class LockUnlockService:
    def __init__(self, db: Session):
        self.db = db

    def get_site_setting_json(self, key: str, default: Any = None) -> Any:
        try:
            record = self.db.query(SiteSetting).filter(SiteSetting.key == key).first()
            if not record or not record.value:
                return default
            try:
                return json.loads(record.value)
            except Exception:
                return record.value
        except Exception:
            return default

    def profile_completion_percent(self, agent: Agent, profile: Optional[AgentProfile] = None) -> int:
        completion = 15
        if not profile:
            profile = self.db.query(AgentProfile).filter(AgentProfile.agent_id == agent.id).first()
        
        if profile:
            if profile.address and profile.languages:
                completion += 15
            
            cities_count = self.db.query(AgentServiceableCity).filter(AgentServiceableCity.agent_id == agent.id).count()
            if profile.service_pincodes and cities_count > 0:
                completion += 15

            segments_count = self.db.query(AgentInsuranceSegment).filter(AgentInsuranceSegment.agent_id == agent.id).count()
            if segments_count > 0:
                completion += 15

            portfolio_count = self.db.query(AgentPortfolio).filter(AgentPortfolio.agent_id == agent.id).count()
            if portfolio_count > 0:
                completion += 15

            if profile.profile_photo_path:
                completion += 10

            pref_exists = self.db.query(AgentLeadPreference).filter(AgentLeadPreference.agent_id == agent.id).first() is not None
            if pref_exists:
                completion += 15

        if str(agent.status) == 'pending':
            completion = 100

        return min(completion, 100)

    def collect_agent_metrics(self, agent: Agent) -> Dict[str, Any]:
        profile = self.db.query(AgentProfile).filter(AgentProfile.agent_id == agent.id).first()

        reviews_count = self.db.query(AgentReview).filter(
            AgentReview.agent_id == agent.id,
            AgentReview.is_approved == True
        ).count()
        if reviews_count == 0:
            reviews_count = int(getattr(agent, 'review_count', 0) or 0)

        total_leads = self.db.query(AgentLead).filter(AgentLead.agent_id == agent.id).count()
        closed_leads = self.db.query(AgentLead).filter(
            AgentLead.agent_id == agent.id,
            AgentLead.lead_status == 'closed'
        ).count()

        referrals = 0
        ref_code = self.db.query(ReferralCode).filter(ReferralCode.agent_id == agent.id).first()
        if ref_code:
            referrals = int(ref_code.total_referrals or 0)

        irdai = False
        amfi = False
        if profile:
            irdai = bool((profile.license_number or '').strip() or profile.irdai_license_doc)
            amfi = bool((profile.arn_number or '').strip() or profile.amfi_license_doc)

        experience = 0
        try:
            exp_val = getattr(agent, 'experience_range', '') or (profile.experience_years if profile else '')
            # Extract first digits if present
            import re
            m = re.search(r'\d+', str(exp_val))
            if m:
                experience = int(m.group())
        except Exception:
            pass

        client_base = 0
        try:
            cb_val = getattr(agent, 'client_base', '')
            import re
            m = re.search(r'\d+', str(cb_val))
            if m:
                client_base = int(m.group())
        except Exception:
            pass

        claim_settle_rate = 0.0
        total_claim_amount = 0.0
        perf = self.db.query(AgentPerformanceStat).filter(AgentPerformanceStat.agent_id == agent.id).first()
        if perf:
            try:
                claim_settle_rate = float(perf.success_rate or 0)
                total_claim_amount = float(perf.claims_amount or 0)
            except Exception:
                pass

        portfolio_products = self.db.query(AgentProductExpertise).filter(
            AgentProductExpertise.agent_id == agent.id
        ).count()

        segments_rows = self.db.query(AgentInsuranceSegment.segment_type).filter(
            AgentInsuranceSegment.agent_id == agent.id
        ).all()
        segments = [str(r[0]).strip().lower() for r in segments_rows if r[0] and str(r[0]).strip() != '-']

        completion = self.profile_completion_percent(agent, profile)

        return {
            'reviews': reviews_count,
            'leads': total_leads,
            'total_leads': total_leads,
            'closed_leads': closed_leads,
            'referrals': referrals,
            'profile_completion': completion,
            'irdai_certificate': irdai,
            'amfi_certificate': amfi,
            'experience': experience,
            'client_base': client_base,
            'claim_settle_rate': claim_settle_rate,
            'total_claim_amount': total_claim_amount,
            'portfolio_products': portfolio_products,
            'portfolio_segments': len(set(segments)),
            'portfolio_segment': set(segments),
        }

    def _condition_passes(self, condition: Dict[str, Any], metrics: Dict[str, Any]) -> bool:
        metric = (condition.get('metric') or '').strip()
        spec = METRIC_CATALOG.get(metric)
        if not spec:
            return False
        return _compare(
            metrics.get(metric),
            condition.get('op') or spec.get('default_op', 'gte'),
            condition.get('value'),
            spec['type'],
        )

    def _format_condition_hint(self, condition: Dict[str, Any], metrics: Dict[str, Any]) -> str:
        metric = (condition.get('metric') or '').strip()
        spec = METRIC_CATALOG.get(metric) or {}
        label = spec.get('label', metric)
        actual = metrics.get(metric)
        target = condition.get('value')
        if spec.get('type') == 'boolean':
            want = _to_bool(target)
            return f"Upload {label}" if want else f"No {label}"
        if spec.get('type') == 'segment':
            return f"Add {str(target).title()} insurance segment"
        
        actual_n = _to_number(actual)
        target_n = _to_number(target)
        remaining = max(0, target_n - actual_n)
        if remaining == int(remaining):
            rem_str = str(int(remaining))
            act_str = str(int(actual_n))
            tar_str = str(int(target_n))
        else:
            rem_str = f"{remaining:.1f}"
            act_str = f"{actual_n:.1f}"
            tar_str = f"{target_n:.1f}"
        
        if remaining > 0:
            return f"Requires {tar_str} {label.lower()} ({act_str}/{tar_str} - {rem_str} more needed)"
        return f"{tar_str} {label.lower()} required"

    def get_feature_access_map(self, agent: Agent) -> Dict[str, Dict[str, Any]]:
        plan_slug = normalize_plan_slug(agent.plan_type) or 'free_trial'
        features_config = self.get_site_setting_json('plan_features_config', {})
        unlock_rules_data = self.get_site_setting_json('feature_unlock_rules', {'rules': []})
        
        if isinstance(unlock_rules_data, list):
            rules = unlock_rules_data
        elif isinstance(unlock_rules_data, dict):
            rules = unlock_rules_data.get('rules') or []
        else:
            rules = []

        # 1. Base Plan features
        if isinstance(features_config, dict) and plan_slug in features_config:
            base_features = set(features_config.get(plan_slug) or [])
        else:
            base_features = set(canonical_plan_feature_slugs(plan_slug))

        # Materialize child steps if edit_profile is present
        if 'edit_profile' in base_features and not any(step in base_features for step in EDIT_PROFILE_CHILD_FEATURES):
            base_features.update(EDIT_PROFILE_CHILD_FEATURES)

        metrics = self.collect_agent_metrics(agent)

        # 2. Evaluate Dynamic Unlock Rules
        unlocked_by_activity = {}
        locked_hints = {}

        for rule in rules:
            if not isinstance(rule, dict) or not rule.get('enabled', True):
                continue
            feature = (rule.get('feature') or '').strip()
            if not feature or feature not in FEATURE_ATTR_MAP:
                continue
            rule_plans = rule.get('plans') or list(PLAN_SLUGS)
            if plan_slug not in rule_plans:
                continue

            conditions = [c for c in (rule.get('conditions') or []) if c.get('metric')]
            if not conditions:
                continue

            match = (rule.get('match') or 'all').lower()
            results = [self._condition_passes(c, metrics) for c in conditions]
            passed = any(results) if match == 'any' else all(results)

            if passed:
                unlocked_by_activity[feature] = "activity_rule"
            else:
                # Generate hint
                hint_parts = [self._format_condition_hint(c, metrics) for c in conditions if not self._condition_passes(c, metrics)]
                if hint_parts and feature not in locked_hints:
                    locked_hints[feature] = ", ".join(hint_parts)

        # 3. Review Growth Milestones
        growth_cfg = self.get_site_setting_json('review_growth_config', {})
        if plan_slug in ('starter', 'free_trial') and growth_cfg.get('enabled', True):
            review_count = metrics['reviews']
            threshold = int(growth_cfg.get('starter_upgrade_threshold', 5))
            if review_count >= threshold:
                unlocked_by_activity['lead_management'] = "review_growth"
                unlocked_by_activity['edit_profile_career_timeline'] = "review_growth"
                unlocked_by_activity['public_profile'] = "review_growth"
                unlocked_by_activity['receive_leads'] = "review_growth"
            else:
                needed = threshold - review_count
                rg_hint = f"Get {needed} more reviews ({review_count}/{threshold}) to unlock"
                for rg_feat in ('lead_management', 'edit_profile_career_timeline', 'public_profile', 'receive_leads'):
                    if rg_feat not in locked_hints:
                        locked_hints[rg_feat] = rg_hint

        # 4. Construct complete access map for all features
        all_features = list(FEATURE_ATTR_MAP.keys())
        access_map = {}

        for feat in all_features:
            is_base = feat in base_features
            is_act = feat in unlocked_by_activity
            is_unlocked = is_base or is_act
            
            hint = None
            if not is_unlocked:
                hint = locked_hints.get(feat)
                if not hint:
                    if plan_slug == 'free_trial':
                        hint = "Upgrade to Starter or Professional's Plan to unlock"
                    else:
                        hint = "Upgrade to Professional's Plan to unlock"

            source = "plan" if is_base else ("activity_rule" if is_act else None)

            access_map[feat] = {
                "feature_slug": feat,
                "label": FEATURE_LABELS.get(feat, feat),
                "is_locked": not is_unlocked,
                "unlocked_by": source,
                "unlock_hint": hint if not is_unlocked else None,
                "upgrade_required": not is_unlocked and plan_slug in ('free_trial', 'starter'),
            }

        return access_map

    def is_feature_unlocked(self, agent: Agent, feature_slug: str) -> bool:
        access_map = self.get_feature_access_map(agent)
        feat_data = access_map.get(feature_slug)
        if not feat_data:
            return True  # Fail-safe open for unknown features
        return not feat_data["is_locked"]

    def require_feature_unlocked(self, agent: Agent, feature_slug: str):
        access_map = self.get_feature_access_map(agent)
        feat_data = access_map.get(feature_slug)
        if feat_data and feat_data["is_locked"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "success": False,
                    "error_code": "FEATURE_LOCKED",
                    "feature": feature_slug,
                    "message": f"{feat_data['label']} is locked on your current plan.",
                    "unlock_hint": feat_data["unlock_hint"],
                    "upgrade_required": feat_data["upgrade_required"]
                }
            )
