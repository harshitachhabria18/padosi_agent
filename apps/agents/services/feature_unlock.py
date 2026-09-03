"""
Activity-based feature unlocks.

Plan checkboxes remain the base entitlement. Rules in
SiteSetting['feature_unlock_rules'] can only ADD features when an agent's
metrics meet admin-configured conditions.
"""
import logging
from decimal import Decimal, InvalidOperation

logger = logging.getLogger(__name__)

PLAN_SLUGS = ('free_trial', 'starter', 'professional', 'exclusive')


def get_plan_slugs():
    """DB-driven plan slugs from new_updates, with hardcoded fallback."""
    try:
        from apps.agents.models import SubscriptionPlan
        slugs = [s for s in SubscriptionPlan.objects.values_list('slug', flat=True) if s]
        if slugs:
            return slugs
    except Exception:
        pass
    return list(PLAN_SLUGS)

PLAN_LABELS = {
    'free_trial': 'Free Trial / Expired',
    'starter': 'Starter Plan',
    'professional': 'Professional Plan',
    'exclusive': 'Exclusive Plan',
}

EDIT_PROFILE_CHILD_FEATURES = (
    'edit_profile_basic',
    'edit_profile_professional',
    'edit_profile_portfolio',
    'edit_profile_additional',
)

# Nested sections inside Professional Details (step 2)
EDIT_PROFILE_PROFESSIONAL_CHILD_FEATURES = (
    'edit_profile_certifications',
    'edit_profile_claim_support',
)

# Nested sections inside Product Portfolio (step 3)
EDIT_PROFILE_PORTFOLIO_CHILD_FEATURES = (
    'manage_portfolio',
    'edit_profile_companies',
)

# Nested sections inside Additional Details (step 4).
# Career timeline stays review-gated and is not included here.
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

# Unlocking a child also turns its parent section(s) on.
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
}

# Starter plan: always unlocked (no review required). Includes the edit-profile
# form sections that used to work before granular lock flags existed.
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
)

# Unlocked on Starter only after admin review-growth threshold (configurable in admin)
REVIEW_CONDITION_FEATURE_SLUGS = (
    'legacy_lead_status',
    'lead_management',
    'public_profile',
    'lead_preferences',
    'receive_leads',
    'edit_profile_career_timeline',
)

LEAD_PREFERENCES_DEFAULT_ON = frozenset(('professional', 'exclusive'))

SLUG_NORMALISE = {
    'basic': 'starter',
    'starter': 'starter',
    'standard': 'starter',          # legacy — Standard Plan was old Starter
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
    'elite': 'starter',             # legacy — no dedicated SiteSettings key
    'eliting_plan': 'starter',
}

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
}

FEATURE_LABELS = {
    'dashboard_stats': 'Dashboard Performance & Stats',
    'lead_management': 'Lead Management & Recent Leads',
    'sales_insights': 'Sales Insights Widget',
    'rank_boost_tips': 'Rank Boost Tips Modal',
    'view_public_profile': 'View Public Profile Button',
    'edit_profile': 'Edit Profile (Full Access)',
    'edit_profile_basic': 'Edit Profile: Basic Details',
    'edit_profile_professional': 'Edit Profile: Professional',
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
    'edit_profile_social_media': 'Social Media',
    'edit_profile_claim_support': 'Claim Support',
    'edit_profile_companies': 'Companies',
    'legacy_lead_status': 'Lead Status',
    'visibility_aio': 'More Visibility: AIO',
    'visibility_geo': 'More Visibility: GEO',
    'visibility_seo': 'More Visibility: SEO',
    'visibility_priority_ranking': 'More Visibility: Priority Ranking',
    'qr_codes': 'QR Codes',
}

NUMERIC_OPS = ('gte', 'gt', 'lte', 'lt', 'eq')
BOOL_OPS = ('eq', 'neq')
SEGMENT_CHOICES = ('health', 'life', 'motor', 'sme')

METRIC_CATALOG = {
    'reviews': {
        'label': 'Reviews',
        'type': 'number',
        'operators': NUMERIC_OPS,
        'widget': 'number',
        'default_op': 'gte',
    },
    'leads': {
        'label': 'Leads',
        'type': 'number',
        'operators': NUMERIC_OPS,
        'widget': 'number',
        'default_op': 'gte',
    },
    'total_leads': {
        'label': 'Total Leads',
        'type': 'number',
        'operators': NUMERIC_OPS,
        'widget': 'number',
        'default_op': 'gte',
    },
    'closed_leads': {
        'label': 'Closed Leads',
        'type': 'number',
        'operators': NUMERIC_OPS,
        'widget': 'number',
        'default_op': 'gte',
    },
    'referrals': {
        'label': 'Referrals',
        'type': 'number',
        'operators': NUMERIC_OPS,
        'widget': 'number',
        'default_op': 'gte',
    },
    'profile_completion': {
        'label': 'Profile Completion %',
        'type': 'number',
        'operators': NUMERIC_OPS,
        'widget': 'percent',
        'default_op': 'gte',
    },
    'irdai_certificate': {
        'label': 'IRDAI Certificate',
        'type': 'boolean',
        'operators': BOOL_OPS,
        'widget': 'boolean',
        'default_op': 'eq',
    },
    'amfi_certificate': {
        'label': 'AMFI Certificate',
        'type': 'boolean',
        'operators': BOOL_OPS,
        'widget': 'boolean',
        'default_op': 'eq',
    },
    'experience': {
        'label': 'Experience (years)',
        'type': 'number',
        'operators': NUMERIC_OPS,
        'widget': 'number',
        'default_op': 'gte',
    },
    'client_base': {
        'label': 'Client Base',
        'type': 'number',
        'operators': NUMERIC_OPS,
        'widget': 'number',
        'default_op': 'gte',
    },
    'claim_settle_rate': {
        'label': 'Claim Settle Rate %',
        'type': 'number',
        'operators': NUMERIC_OPS,
        'widget': 'percent',
        'default_op': 'gte',
    },
    'total_claim_amount': {
        'label': 'Total Claim Amount (₹)',
        'type': 'number',
        'operators': NUMERIC_OPS,
        'widget': 'currency',
        'default_op': 'gte',
    },
    'portfolio_products': {
        'label': 'Product Portfolio (N products)',
        'type': 'number',
        'operators': NUMERIC_OPS,
        'widget': 'number',
        'default_op': 'gte',
    },
    'portfolio_segments': {
        'label': 'Product Portfolio Segments (count)',
        'type': 'number',
        'operators': NUMERIC_OPS,
        'widget': 'number',
        'default_op': 'gte',
    },
    'portfolio_segment': {
        'label': 'Product Portfolio Segment',
        'type': 'segment',
        'operators': BOOL_OPS,
        'widget': 'segment',
        'default_op': 'eq',
    },
}

_OP_LABELS = {
    'gte': '≥',
    'gt': '>',
    'lte': '≤',
    'lt': '<',
    'eq': '=',
    'neq': '≠',
}


def normalize_plan_slug(plan_type):
    if not plan_type:
        return ''
    pt = str(plan_type).strip()
    slug = pt.lower().replace(' ', '_')
    return SLUG_NORMALISE.get(slug, slug)


def plan_slug_from_name(plan_name):
    """Map a display name / selected_plan string to a canonical slug."""
    name = str(plan_name or '').strip().lower()
    if not name:
        return ''
    if 'trial' in name:
        return 'free_trial'
    if 'exclusive' in name:
        return 'exclusive'
    if 'professional' in name or name in ('pro', 'pro_plan', 'pro plan'):
        return 'professional'
    if 'starter' in name or 'basic' in name:
        return 'starter'
    return normalize_plan_slug(name) if normalize_plan_slug(name) in PLAN_SLUGS else ''


def resolve_checkout_plan_slug(plan_type, plan_name=None):
    """
    Accept checkout identifiers from web, upgrade, and legacy clients.

    Valid inputs: canonical slugs, aliases (basic/pro), display names,
    and numeric SubscriptionPlan ids. Returns a PLAN_SLUGS value or None.
    """
    raw = str(plan_type or '').strip()
    if raw:
        slug = normalize_plan_slug(raw)
        if slug in PLAN_SLUGS:
            return slug
        named = plan_slug_from_name(raw)
        if named in PLAN_SLUGS:
            return named
        if raw.isdigit():
            try:
                from apps.agents.models import SubscriptionPlan
                plan = SubscriptionPlan.objects.filter(id=int(raw)).first()
                if plan:
                    named = plan_slug_from_name(plan.name)
                    if named in PLAN_SLUGS:
                        return named
            except Exception:
                logger.warning('Failed to resolve SubscriptionPlan id=%s', raw, exc_info=True)
    if plan_name:
        named = plan_slug_from_name(plan_name)
        if named in PLAN_SLUGS:
            return named
    return None


def get_unlock_rules():
    from apps.home.models import SiteSetting
    data = SiteSetting.get_value('feature_unlock_rules', {'rules': []}) or {'rules': []}
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get('rules') or []
    return []


def profile_completion_percent(agent):
    """Same 15-point rubric used by the agent dashboard. Do not change the math."""
    completion = 15
    profile = agent.get_primary_profile()
    if profile:
        if profile.address and profile.languages:
            completion += 15
        if getattr(profile, 'service_pincodes', None) and agent.serviceableCities.exists():
            completion += 15
        if agent.insuranceSegments.exists():
            completion += 15
        if hasattr(agent, 'portfolios') and agent.portfolios.exists():
            completion += 15
        if profile.profile_photo_path:
            completion += 10
        if hasattr(agent, 'leadPreferences') and agent.leadPreferences:
            completion += 15

    if getattr(agent, 'status', None) == 'pending':
        completion = 100
    return min(completion, 100)


def collect_agent_metrics(agent):
    """Read live activity metrics used by unlock rules."""
    profile = agent.get_primary_profile()
    try:
        reviews = int(agent.review_count or 0)
    except Exception:
        reviews = 0

    leads = 0
    closed_leads = 0
    try:
        leads = agent.leads.count()
        closed_leads = agent.leads.filter(lead_status='closed').count()
    except Exception:
        pass

    referrals = 0
    try:
        from apps.admin_panel.models.referral_usage import ReferralUsage
        referrals = ReferralUsage.objects.filter(
            referrer_agent=agent, status='converted'
        ).count()
    except Exception:
        try:
            from apps.admin_panel.models.referral_code import ReferralCode
            code = ReferralCode.objects.filter(agent=agent).first()
            referrals = int(getattr(code, 'total_referrals', 0) or 0) if code else 0
        except Exception:
            referrals = 0

    irdai = False
    amfi = False
    if profile:
        irdai = bool((profile.license_number or '').strip() or profile.irdai_license_doc)
        amfi = bool((profile.arn_number or '').strip() or profile.amfi_license_doc)

    try:
        experience = int(agent.experience_years or 0)
    except (TypeError, ValueError):
        experience = 0

    try:
        client_base = int(agent.client_base or 0)
    except (TypeError, ValueError):
        client_base = 0

    claim_settle_rate = 0
    total_claim_amount = 0
    try:
        perf = getattr(agent, 'performanceStats', None)
        if perf:
            claim_settle_rate = float(perf.success_rate or 0)
            total_claim_amount = float(perf.claims_amount or 0)
    except Exception:
        pass

    portfolio_products = 0
    try:
        portfolio_products = agent.productExpertise.count()
    except Exception:
        pass

    segments = []
    try:
        segments = [
            (s or '').strip().lower()
            for s in agent.insuranceSegments.values_list('segment_type', flat=True)
            if s and str(s).strip() and str(s).strip() != '-'
        ]
    except Exception:
        segments = []

    try:
        completion = profile_completion_percent(agent)
    except Exception:
        completion = 15

    return {
        'reviews': reviews,
        'leads': leads,
        'total_leads': leads,
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


def _to_number(value, default=0):
    if value is None or value == '':
        return default
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError, InvalidOperation):
        return default


def _to_bool(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in ('1', 'true', 'yes', 'on')


def _compare(actual, op, expected, metric_type):
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
    return actual_n >= expected_n  # gte default


def _condition_passes(condition, metrics):
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


def _rule_applies(rule, plan_slug):
    if not rule.get('enabled', True):
        return False
    feature = (rule.get('feature') or '').strip()
    if not feature or feature not in FEATURE_ATTR_MAP:
        return False
    plans = rule.get('plans') or list(PLAN_SLUGS)
    return plan_slug in plans


def _rule_passes(rule, metrics):
    conditions = [c for c in (rule.get('conditions') or []) if c.get('metric')]
    if not conditions:
        return False
    match = (rule.get('match') or 'all').lower()
    results = [_condition_passes(c, metrics) for c in conditions]
    if match == 'any':
        return any(results)
    return all(results)


def evaluate_unlock_rules(agent, plan_slug, metrics=None, rules=None):
    """Return extra show_* attribute names unlocked by passing rules."""
    extra_attrs = set()
    if not plan_slug:
        return extra_attrs
    rules = rules if rules is not None else get_unlock_rules()
    if not rules:
        return extra_attrs
    metrics = metrics if metrics is not None else collect_agent_metrics(agent)
    for rule in rules:
        if not _rule_applies(rule, plan_slug):
            continue
        if _rule_passes(rule, metrics):
            extra_attrs.update(FEATURE_ATTR_MAP.get(rule.get('feature'), []))
    return extra_attrs


def has_directory_unlock_rule(plan_slug, rules=None):
    rules = rules if rules is not None else get_unlock_rules()
    for rule in rules:
        if not _rule_applies(rule, plan_slug):
            continue
        if rule.get('feature') == 'agent_directory_visibility':
            return True
    return False


def needs_activity_eval_for_directory(base_plan, plan_slug, rules=None):
    """Skip metric collection when the agent is already listed, or no directory rule exists."""
    if base_plan is None:
        return False
    if getattr(base_plan, 'is_listed_in_directory', True):
        return False
    return has_directory_unlock_rule(plan_slug, rules=rules)


class OverlayPlan:
    """Additive wrapper: extra attrs are True, everything else defers to the base plan."""

    def __init__(self, base, extra_attrs):
        self._base = base
        self._extra = set(extra_attrs or [])

    def __getattr__(self, name):
        if name in self._extra:
            return True
        return getattr(self._base, name)

    def __getitem__(self, name):
        return getattr(self, name)

    def __bool__(self):
        return True

    def __repr__(self):
        return f'OverlayPlan(base={self._base!r}, extra={sorted(self._extra)!r})'


def overlay_plan(base_plan, extra_attrs):
    """Keep fail-open: None stays None. Skip wrap when there is nothing to add."""
    if base_plan is None:
        return None
    extra = set(extra_attrs or [])
    if not extra:
        return base_plan
    return OverlayPlan(base_plan, extra)


def _format_current(metric, actual):
    spec = METRIC_CATALOG.get(metric) or {}
    metric_type = spec.get('type')
    if metric_type == 'boolean':
        return 'have' if _to_bool(actual) else 'missing'
    if metric_type == 'segment':
        if isinstance(actual, (set, list, tuple)):
            return ', '.join(sorted(actual)) or 'none'
        return str(actual or 'none')
    number = _to_number(actual)
    if spec.get('widget') == 'percent':
        if number == int(number):
            return str(int(number))
        return f'{number:.1f}'
    if spec.get('widget') == 'currency':
        if number == int(number):
            return str(int(number))
        return f'{number:.2f}'
    if number == int(number):
        return str(int(number))
    return str(number)


def _format_target(metric, value):
    spec = METRIC_CATALOG.get(metric) or {}
    if spec.get('type') == 'boolean':
        return 'present' if _to_bool(value) else 'absent'
    if spec.get('type') == 'segment':
        return str(value or '').replace('_', ' ').title() or 'segment'
    number = _to_number(value)
    if number == int(number):
        return str(int(number))
    return str(number)


def format_condition_fragment(condition, metrics):
    metric = (condition.get('metric') or '').strip()
    spec = METRIC_CATALOG.get(metric) or {}
    label = spec.get('label', metric)
    actual = metrics.get(metric)
    target = condition.get('value')
    if spec.get('type') == 'boolean':
        want = _to_bool(target)
        have = _to_bool(actual)
        state = 'have' if have else 'missing'
        return f"{label} ({state})" if want else f"no {label} ({state})"
    if spec.get('type') == 'segment':
        have = _to_bool(_compare(actual, 'eq', target, 'segment'))
        state = 'have' if have else 'missing'
        return f"{_format_target(metric, target)} segment ({state})"
    current = _format_current(metric, actual)
    needed = _format_target(metric, target)
    return f"{needed} {label.lower()} ({current}/{needed})"


def format_unlock_fragment(rule, metrics):
    parts = []
    for condition in rule.get('conditions') or []:
        if not condition.get('metric'):
            continue
        parts.append(format_condition_fragment(condition, metrics))
    return ', '.join(parts)


def build_unlock_hints(agent, plan_slug, metrics=None, rules=None):
    """
    Map show_* attrs (and feature slugs) to a remaining-condition fragment.
    Only includes features that are still locked and have an applicable rule.
    """
    rules = rules if rules is not None else get_unlock_rules()
    if not rules or not plan_slug:
        return {}
    metrics = metrics if metrics is not None else collect_agent_metrics(agent)
    hints = {}
    for rule in rules:
        if not _rule_applies(rule, plan_slug):
            continue
        if _rule_passes(rule, metrics):
            continue
        fragment = format_unlock_fragment(rule, metrics)
        if not fragment:
            continue
        feature = rule.get('feature')
        if feature not in hints:
            hints[feature] = fragment
        for attr in FEATURE_ATTR_MAP.get(feature, []):
            if attr not in hints:
                hints[attr] = fragment
    return hints


def sanitize_unlock_rules(raw_rules):
    """Validate admin-submitted rules before persisting."""
    cleaned = []
    if not isinstance(raw_rules, list):
        return cleaned
    for i, rule in enumerate(raw_rules):
        if not isinstance(rule, dict):
            continue
        feature = (rule.get('feature') or '').strip()
        if feature not in FEATURE_ATTR_MAP:
            continue
        conditions = []
        for cond in rule.get('conditions') or []:
            if not isinstance(cond, dict):
                continue
            metric = (cond.get('metric') or '').strip()
            spec = METRIC_CATALOG.get(metric)
            if not spec:
                continue
            op = (cond.get('op') or spec.get('default_op', 'gte')).lower()
            if op not in spec['operators']:
                op = spec.get('default_op', 'gte')
            value = cond.get('value')
            if spec['type'] == 'boolean':
                value = True if _to_bool(value) else False
            elif spec['type'] == 'segment':
                value = str(value or '').strip().lower()
                if value not in SEGMENT_CHOICES:
                    continue
            else:
                if value is None or value == '':
                    continue
                value = _to_number(value)
            conditions.append({'metric': metric, 'op': op, 'value': value})
        if not conditions:
            continue
        plans = [p for p in (rule.get('plans') or []) if p in PLAN_SLUGS]
        if not plans:
            plans = list(PLAN_SLUGS)
        rule_id = str(rule.get('id') or '').strip() or f'rule_{i + 1}'
        cleaned.append({
            'id': rule_id,
            'enabled': bool(rule.get('enabled', True)),
            'feature': feature,
            'plans': plans,
            'match': 'any' if rule.get('match') == 'any' else 'all',
            'conditions': conditions,
        })
    return cleaned


def lead_preferences_configured(config):
    """True once any plan list explicitly includes the lead_preferences feature."""
    source = config if isinstance(config, dict) else {}
    for slug in PLAN_SLUGS:
        raw = source.get(slug) or []
        if isinstance(raw, (list, tuple)) and 'lead_preferences' in raw:
            return True
    return False


def canonical_plan_feature_slugs(plan_slug):
    """Default entitlements when admin has not saved a plan_features_config list."""
    slug = normalize_plan_slug(plan_slug)
    if slug == 'starter':
        return list(STARTER_BASE_FEATURE_SLUGS)
    if slug in ('professional', 'exclusive'):
        return list(FEATURE_ATTR_MAP.keys())
    if slug == 'free_trial':
        return ['dashboard_stats', 'edit_profile']
    return []


def resolve_plan_feature_slugs(plan_slug, features_config=None):
    """
    Entitlements for a plan slug.

    Admin lock/unlock writes plan_features_config; that saved list is the
    source of truth. Missing/unknown slugs fall back to canonical defaults.
    Review-gated extras can still be added later via overlay rules.
    """
    slug = normalize_plan_slug(plan_slug)
    if isinstance(features_config, dict):
        saved = features_config.get(slug)
        if isinstance(saved, (list, tuple)):
            return [feat for feat in saved if feat in FEATURE_ATTR_MAP]
    return canonical_plan_feature_slugs(slug)


def with_feature_defaults(plan_slug, enabled_features, features_config=None):
    """
    Apply product defaults for features that did not exist when a config was saved.

    Starter / free trial: Lead Preferences stay locked unless admin checks the box.
    Professional / Exclusive: unlocked until admin has configured the feature.
    """
    enabled = list(enabled_features or [])
    slug = normalize_plan_slug(plan_slug)
    if 'lead_preferences' in enabled:
        return enabled
    if lead_preferences_configured(features_config):
        return enabled
    if slug in LEAD_PREFERENCES_DEFAULT_ON:
        if 'lead_preferences' not in enabled:
            enabled.append('lead_preferences')
        for child in LEAD_PREFERENCE_CHILD_FEATURES:
            if child not in enabled:
                enabled.append(child)
    return enabled


def with_all_plan_feature_defaults(config):
    """Copy plan feature lists and backfill lead_preferences product defaults."""
    copied = copy_plan_features_config(config)
    if lead_preferences_configured(copied):
        return copied
    for slug in LEAD_PREFERENCES_DEFAULT_ON:
        if 'lead_preferences' not in copied[slug]:
            copied[slug].append('lead_preferences')
        for child in LEAD_PREFERENCE_CHILD_FEATURES:
            if child not in copied[slug]:
                copied[slug].append(child)
    return copied


def plan_shows_feature(agent_plan, attr, default=True):
    """Read a show_* flag from PlanFeatureProxy, OverlayPlan, or SubscriptionPlan."""
    if agent_plan is None:
        return default
    try:
        return bool(getattr(agent_plan, attr))
    except AttributeError:
        return default


def materialize_edit_profile_steps(features):
    """
    Legacy configs may list only edit_profile without the four step slugs.
    Treat that as implicit full step access until an admin locks a step.
    """
    features = list(features or [])
    if 'edit_profile' not in features:
        return features
    if any(step in features for step in EDIT_PROFILE_CHILD_FEATURES):
        return features
    for step in EDIT_PROFILE_CHILD_FEATURES:
        if step not in features:
            features.append(step)
    return features


def copy_plan_features_config(config):
    """Shallow-copy plan feature lists so callers cannot mutate SiteSetting data in place."""
    copied = {}
    source = config if isinstance(config, dict) else {}
    for slug in PLAN_SLUGS:
        raw = source.get(slug)
        if isinstance(raw, (list, tuple)):
            copied[slug] = list(raw)
        else:
            # Missing key: seed canonical defaults so locking one section
            # does not save an empty list and lock the entire plan.
            copied[slug] = canonical_plan_feature_slugs(slug)
    return copied


def child_features_for(feature):
    """Nested slugs that lock/unlock together with a parent section."""
    children = []
    if feature == 'edit_profile':
        children.extend(EDIT_PROFILE_CHILD_FEATURES)
        children.extend(EDIT_PROFILE_PROFESSIONAL_CHILD_FEATURES)
        children.extend(EDIT_PROFILE_PORTFOLIO_CHILD_FEATURES)
        children.extend(EDIT_PROFILE_ADDITIONAL_CHILD_FEATURES)
    elif feature == 'edit_profile_professional':
        children.extend(EDIT_PROFILE_PROFESSIONAL_CHILD_FEATURES)
    elif feature == 'edit_profile_portfolio':
        children.extend(EDIT_PROFILE_PORTFOLIO_CHILD_FEATURES)
    elif feature == 'edit_profile_additional':
        children.extend(EDIT_PROFILE_ADDITIONAL_CHILD_FEATURES)
    elif feature == 'lead_preferences':
        children.extend(LEAD_PREFERENCE_CHILD_FEATURES)
    return children


def toggle_plan_feature(config, plan_slug, feature, locked):
    """
    Enable or disable one feature on a single plan slug.

    Returns a new config dict. Other plan lists are copied unchanged.
    Locking a parent also drops its nested children. Unlocking a parent
    restores those children; unlocking a child also turns its parents on.
    """
    slug = normalize_plan_slug(plan_slug)
    if slug not in PLAN_SLUGS:
        raise ValueError('Unknown plan slug')
    if feature not in FEATURE_ATTR_MAP:
        raise ValueError('Unknown feature')

    new_config = copy_plan_features_config(config)
    features = materialize_edit_profile_steps(list(new_config[slug]))
    if locked:
        drop = {feature}
        drop.update(child_features_for(feature))
        features = [item for item in features if item not in drop]
        if (
            feature in EDIT_PROFILE_CHILD_FEATURES
            and 'edit_profile' in features
            and not any(step in features for step in EDIT_PROFILE_CHILD_FEATURES)
        ):
            features = [item for item in features if item != 'edit_profile']
    else:
        restore = [feature]
        restore.extend(child_features_for(feature))
        restore.extend(FEATURE_PARENTS.get(feature, ()))
        for item in restore:
            if item not in features and item in FEATURE_ATTR_MAP:
                features.append(item)
        if feature in LEAD_PREFERENCE_CHILD_FEATURES and 'lead_preferences' not in features:
            features.append('lead_preferences')
    new_config[slug] = features
    return new_config


def _rule_plans(rule):
    plans = [p for p in (rule.get('plans') or []) if p in PLAN_SLUGS]
    return plans or list(PLAN_SLUGS)


def upsert_plan_unlock_rule(rules, plan_slug, feature, conditions, match='all'):
    """
    Attach or update an unlock rule for one plan + feature.

    If an existing rule covers this feature and other plans, that rule is split
    so the other plans keep their original conditions.
    """
    slug = normalize_plan_slug(plan_slug)
    if slug not in PLAN_SLUGS or feature not in FEATURE_ATTR_MAP:
        return list(rules or [])

    updated_this_plan = False
    next_rules = []
    for rule in rules or []:
        if not isinstance(rule, dict) or rule.get('feature') != feature:
            next_rules.append(rule)
            continue
        plans = _rule_plans(rule)
        if slug not in plans:
            next_rules.append(rule)
            continue
        others = [p for p in plans if p != slug]
        if others:
            split = dict(rule)
            split['plans'] = others
            next_rules.append(split)
            this_id = f'rule_{slug}_{feature}'
        else:
            this_id = str(rule.get('id') or '').strip() or f'rule_{slug}_{feature}'
        if not updated_this_plan:
            next_rules.append({
                'id': this_id,
                'enabled': True,
                'feature': feature,
                'plans': [slug],
                'match': match,
                'conditions': conditions,
            })
            updated_this_plan = True

    if not updated_this_plan:
        next_rules.append({
            'id': f'rule_{slug}_{feature}',
            'enabled': True,
            'feature': feature,
            'plans': [slug],
            'match': match,
            'conditions': conditions,
        })
    return sanitize_unlock_rules(next_rules)


def remove_plan_only_unlock_rule(rules, plan_slug, feature):
    """On unlock, drop rules that apply only to this plan+feature. Keep multi-plan rules."""
    slug = normalize_plan_slug(plan_slug)
    kept = []
    for rule in rules or []:
        if not isinstance(rule, dict):
            continue
        if rule.get('feature') != feature:
            kept.append(rule)
            continue
        plans = _rule_plans(rule)
        if plans == [slug]:
            continue
        kept.append(rule)
    return kept
