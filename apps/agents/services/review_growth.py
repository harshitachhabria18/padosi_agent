"""
QR service + review-growth settings.

Admin-managed SiteSetting JSON. Unlocks are additive only — they never
remove plan checkbox entitlements.
"""
import logging

from apps.agents.services.feature_unlock import (
    FEATURE_ATTR_MAP,
    FEATURE_LABELS,
    PLAN_SLUGS,
    REVIEW_CONDITION_FEATURE_SLUGS,
    normalize_plan_slug,
    plan_shows_feature,
)
from apps.home.models import SiteSetting

logger = logging.getLogger(__name__)

QR_TYPES = ('profile', 'card', 'reviews')

QR_TYPE_LABELS = {
    'profile': 'Profile',
    'card': 'Agent Card',
    'reviews': 'Reviews & Rating',
}

DEFAULT_QR_CONFIG = {
    'enabled': True,
    'allow_download': True,
}

DEFAULT_UNLOCK_FEATURES = REVIEW_CONDITION_FEATURE_SLUGS

DEFAULT_REVIEW_GROWTH = {
    'enabled': True,
    'popup_enabled': True,
    'upgrade_cta_enabled': True,
    'starter_unlock_enabled': True,
    'popup_delay_ms': 2500,
    'min_reviews': 3,
    'eligible_plans': ['starter'],
    'unlock_feature_slugs': list(DEFAULT_UNLOCK_FEATURES),
    'upgrade_plan': 'professional',
    'upgrade_title': 'Unlock full visibility',
    'upgrade_message': (
        'You have collected enough reviews to unlock more dashboard features. '
        'Upgrade to Professional for AIO, GEO, SEO and Priority Ranking — '
        'and open every remaining locked section.'
    ),
    'upgrade_price_enabled': True,
    'upgrade_promo_price': 4999,
    'upgrade_full_price': 6999,
    'upgrade_show_full_price': True,
    'review_scroll_delay_ms': 3000,
    'visibility_section_enabled': True,
}


def _as_bool(value, default=True):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in ('1', 'true', 'yes', 'on'):
        return True
    if text in ('0', 'false', 'no', 'off', ''):
        return False
    return default


def _as_int(value, default, minimum=None, maximum=None):
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    if minimum is not None:
        number = max(minimum, number)
    if maximum is not None:
        number = min(maximum, number)
    return number


def sanitize_qr_config(raw):
    data = raw if isinstance(raw, dict) else {}
    return {
        'enabled': _as_bool(data.get('enabled'), True),
        'allow_download': _as_bool(data.get('allow_download'), True),
    }


def sanitize_review_growth_config(raw):
    data = raw if isinstance(raw, dict) else {}
    eligible = [
        p for p in (data.get('eligible_plans') or DEFAULT_REVIEW_GROWTH['eligible_plans'])
        if p in PLAN_SLUGS
    ]
    if not eligible:
        eligible = list(DEFAULT_REVIEW_GROWTH['eligible_plans'])

    unlock = []
    for feat in data.get('unlock_feature_slugs') or DEFAULT_UNLOCK_FEATURES:
        feat = str(feat or '').strip()
        if feat in FEATURE_ATTR_MAP and feat not in unlock:
            unlock.append(feat)

    upgrade_plan = normalize_plan_slug(data.get('upgrade_plan') or 'professional')
    if upgrade_plan not in PLAN_SLUGS:
        upgrade_plan = 'professional'

    title = str(data.get('upgrade_title') or DEFAULT_REVIEW_GROWTH['upgrade_title']).strip()
    message = str(data.get('upgrade_message') or DEFAULT_REVIEW_GROWTH['upgrade_message']).strip()
    if not title:
        title = DEFAULT_REVIEW_GROWTH['upgrade_title']
    if not message:
        message = DEFAULT_REVIEW_GROWTH['upgrade_message']

    return {
        'enabled': _as_bool(data.get('enabled'), True),
        'popup_enabled': _as_bool(data.get('popup_enabled'), True),
        'upgrade_cta_enabled': _as_bool(
            data.get('upgrade_cta_enabled'),
            DEFAULT_REVIEW_GROWTH['upgrade_cta_enabled'],
        ),
        'starter_unlock_enabled': _as_bool(
            data.get('starter_unlock_enabled'),
            DEFAULT_REVIEW_GROWTH['starter_unlock_enabled'],
        ),
        'popup_delay_ms': _as_int(data.get('popup_delay_ms'), 2500, 1500, 5000),
        'min_reviews': _as_int(data.get('min_reviews'), 3, 1, 50),
        'eligible_plans': eligible,
        'unlock_feature_slugs': unlock or list(DEFAULT_UNLOCK_FEATURES),
        'upgrade_plan': upgrade_plan,
        'upgrade_title': title[:160],
        'upgrade_message': message[:800],
        'upgrade_price_enabled': _as_bool(
            data.get('upgrade_price_enabled'),
            DEFAULT_REVIEW_GROWTH['upgrade_price_enabled'],
        ),
        'upgrade_promo_price': _as_int(
            data.get('upgrade_promo_price'),
            DEFAULT_REVIEW_GROWTH['upgrade_promo_price'],
            minimum=0,
        ),
        'upgrade_full_price': _as_int(
            data.get('upgrade_full_price'),
            DEFAULT_REVIEW_GROWTH['upgrade_full_price'],
            minimum=0,
        ),
        'upgrade_show_full_price': _as_bool(
            data.get('upgrade_show_full_price'),
            DEFAULT_REVIEW_GROWTH['upgrade_show_full_price'],
        ),
        'review_scroll_delay_ms': _as_int(
            data.get('review_scroll_delay_ms'), 3000, 2000, 5000
        ),
        'visibility_section_enabled': _as_bool(
            data.get('visibility_section_enabled'), True
        ),
    }


def gst_inclusive(excl_gst_amount):
    """Return GST-inclusive rupee total from ex-GST base."""
    base = round(float(excl_gst_amount or 0))
    return base + round(base * 0.18, 0)


def get_review_upgrade_pricing(agent):
    """
    Review-growth upgrade amounts for dashboard CTA and checkout.
    Returns None when custom pricing is off or agent is not eligible.
    """
    cfg = get_review_growth_config()
    if not cfg.get('enabled') or not cfg.get('upgrade_price_enabled', True):
        return None
    if not should_show_upgrade_cta(agent):
        return None

    promo_excl = cfg['upgrade_promo_price']
    full_excl = cfg['upgrade_full_price']
    promo_incl = gst_inclusive(promo_excl)
    full_incl = gst_inclusive(full_excl)

    return {
        'promo_excl_gst': promo_excl,
        'full_excl_gst': full_excl,
        'promo_incl_gst': promo_incl,
        'full_incl_gst': full_incl,
        'show_full_price': bool(cfg.get('upgrade_show_full_price', True)),
        'checkout_base_excl_gst': promo_excl,
        'checkout_total_incl_gst': promo_incl,
    }


def should_use_review_upgrade_pricing(agent):
    return get_review_upgrade_pricing(agent) is not None


def get_qr_config():
    try:
        return sanitize_qr_config(SiteSetting.get_value('qr_service_config', DEFAULT_QR_CONFIG))
    except Exception:
        logger.exception('Failed to load qr_service_config')
        return dict(DEFAULT_QR_CONFIG)


def get_review_growth_config():
    try:
        return sanitize_review_growth_config(
            SiteSetting.get_value('review_growth_config', DEFAULT_REVIEW_GROWTH)
        )
    except Exception:
        logger.exception('Failed to load review_growth_config')
        return dict(DEFAULT_REVIEW_GROWTH)


def is_qr_enabled():
    return bool(get_qr_config().get('enabled'))


def qr_plan_controls_active(features_config=None):
    """True once QR rows have been saved on at least one plan in the feature grid."""
    source = features_config if features_config is not None else (SiteSetting.get_value('plan_features_config') or {})
    if not isinstance(source, dict):
        return False
    for feats in source.values():
        if isinstance(feats, (list, tuple)) and (
            'qr_codes' in feats or 'qr_poster_download' in feats
        ):
            return True
    return False


def qr_access_for_plan(agent_plan, download=False, features_config=None):
    """
    Whether this plan can use QR pages (or poster download).

    Until admin saves the QR feature rows, the global qr_service_config
    remains the source of truth so existing sites keep working.
    """
    cfg = get_qr_config()
    if not cfg.get('enabled'):
        return False
    source = features_config if features_config is not None else (SiteSetting.get_value('plan_features_config') or {})
    if qr_plan_controls_active(source):
        if not plan_shows_feature(agent_plan, 'show_qr_codes', False):
            return False
        if download:
            return plan_shows_feature(agent_plan, 'show_qr_poster_download', False)
        return True
    if download:
        return bool(cfg.get('allow_download'))
    return True


def agent_review_count(agent):
    """Approved review count — always query DB for accuracy."""
    if agent is None:
        return 0
    agent_id = getattr(agent, 'pk', None) or getattr(agent, 'id', None)
    if not agent_id:
        return 0
    try:
        from apps.agents.models import AgentReview
        return AgentReview.objects.filter(agent_id=agent_id, is_approved=True).count()
    except Exception:
        try:
            return int(getattr(agent, 'review_count', 0) or 0)
        except (TypeError, ValueError):
            return 0


def _plan_slug(agent):
    return normalize_plan_slug(getattr(agent, 'plan_type', '') or '')


def should_show_popup(agent):
    cfg = get_review_growth_config()
    if not cfg.get('enabled') or not cfg.get('popup_enabled'):
        return False
    return agent_review_count(agent) < cfg['min_reviews']


def should_show_upgrade_cta(agent):
    cfg = get_review_growth_config()
    if not cfg.get('enabled') or not cfg.get('upgrade_cta_enabled', True):
        return False
    slug = _plan_slug(agent)
    if slug not in cfg.get('eligible_plans', []):
        return False
    if slug == cfg.get('upgrade_plan'):
        return False
    return agent_review_count(agent) >= cfg['min_reviews']


def should_show_upgrade_progress(agent):
    """Starter agents below threshold — show progress toward upgrade unlock."""
    cfg = get_review_growth_config()
    if not cfg.get('enabled') or not cfg.get('upgrade_cta_enabled', True):
        return False
    slug = _plan_slug(agent)
    if slug not in cfg.get('eligible_plans', []):
        return False
    if slug == cfg.get('upgrade_plan'):
        return False
    count = agent_review_count(agent)
    return count < cfg['min_reviews']


def get_review_growth_status(agent):
    """Dashboard / API snapshot for review-growth UI."""
    cfg = get_review_growth_config()
    count = agent_review_count(agent)
    min_reviews = cfg.get('min_reviews', 3)
    slug = _plan_slug(agent)
    eligible = slug in cfg.get('eligible_plans', [])
    enabled = bool(cfg.get('enabled'))
    upgrade_cta = bool(cfg.get('upgrade_cta_enabled', True))
    on_upgrade_plan = slug == cfg.get('upgrade_plan')
    show_cta = should_show_upgrade_cta(agent)
    show_progress = should_show_upgrade_progress(agent)
    remaining = max(min_reviews - count, 0)
    return {
        'enabled': enabled,
        'upgrade_cta_enabled': upgrade_cta,
        'eligible_plan': eligible,
        'plan_slug': slug,
        'review_count': count,
        'min_reviews': min_reviews,
        'remaining_reviews': remaining,
        'upgrade_ready': show_cta,
        'show_upgrade_cta': show_cta,
        'show_upgrade_progress': show_progress,
        'progress_percent': min(100, int(round((count / min_reviews) * 100))) if min_reviews else 0,
    }


def review_threshold_just_crossed(previous_count, new_count):
    """True when approved review count crosses min_reviews this submission."""
    cfg = get_review_growth_config()
    if not cfg.get('enabled') or not cfg.get('upgrade_cta_enabled', True):
        return False
    threshold = cfg['min_reviews']
    try:
        previous_count = int(previous_count or 0)
        new_count = int(new_count or 0)
    except (TypeError, ValueError):
        return False
    return previous_count < threshold <= new_count


def extra_unlock_attrs(agent):
    """show_* attribute names to ADD when review threshold is met."""
    cfg = get_review_growth_config()
    if not cfg.get('enabled') or not cfg.get('starter_unlock_enabled', True) or agent is None:
        return set()
    slug = _plan_slug(agent)
    if slug not in cfg.get('eligible_plans', []):
        return set()
    if agent_review_count(agent) < cfg['min_reviews']:
        return set()
    attrs = set()
    for feat in cfg.get('unlock_feature_slugs') or []:
        attrs.update(FEATURE_ATTR_MAP.get(feat, []))
    return attrs


DASHBOARD_UPGRADE_SECTIONS = (
    ('show_recent_leads', 'Leads Management'),
    ('show_lead_status', 'Lead Status'),
    ('show_profile_section', 'Profile Section Visibility'),
    ('show_lead_preferences', 'Lead Preferences'),
    ('show_new_business_leads', 'New Business Leads'),
    ('show_career_timeline', 'Career Timeline'),
    ('show_portfolio', 'Product Portfolio'),
    ('show_achievement', 'Gallery / Achievements'),
    ('show_review_management', 'Review Management'),
    ('show_agent_certificate', 'Certifications'),
    ('show_professional_bio', 'Professional Bio'),
    ('show_social_media', 'Social Media'),
    ('show_claim_support', 'Claims & Settled Stats'),
    ('show_visibility_aio', 'AIO Visibility'),
    ('show_visibility_geo', 'GEO Visibility'),
    ('show_visibility_seo', 'SEO Visibility'),
    ('show_visibility_priority_ranking', 'Priority Ranking'),
    ('show_lead_portfolio_analysis', 'Portfolio Analysis Leads'),
    ('show_lead_claims_support', 'Claims Support Leads'),
)


def build_review_unlock_summary(agent, starter_plan, professional_plan):
    """Sections unlocked by reviews vs still locked until Professional upgrade."""
    if not should_show_upgrade_cta(agent):
        return None
    cfg = get_review_growth_config()

    unlocked = []
    seen = set()
    unlocked_attrs = set()
    for feat in cfg.get('unlock_feature_slugs') or []:
        attrs = FEATURE_ATTR_MAP.get(feat, [])
        if not any(plan_shows_feature(starter_plan, attr, default=False) for attr in attrs):
            continue
        unlocked_attrs.update(attrs)
        label = FEATURE_LABELS.get(feat, feat.replace('_', ' ').title())
        if label not in seen:
            seen.add(label)
            unlocked.append({'slug': feat, 'label': label})

    still_locked = []
    seen_locked = set()
    for attr, label in DASHBOARD_UPGRADE_SECTIONS:
        if attr in unlocked_attrs or label in seen:
            continue
        if plan_shows_feature(starter_plan, attr, default=False):
            continue
        if not plan_shows_feature(professional_plan, attr, default=True):
            continue
        if label in seen_locked:
            continue
        seen_locked.add(label)
        still_locked.append({'attr': attr, 'label': label})

    unlocked_preview = unlocked[:4]
    locked_preview = still_locked[:5]
    return {
        'unlocked': unlocked,
        'still_locked': still_locked,
        'unlocked_preview': unlocked_preview,
        'locked_preview': locked_preview,
        'unlocked_more': max(0, len(unlocked) - len(unlocked_preview)),
        'locked_more': max(0, len(still_locked) - len(locked_preview)),
        'title': 'Review condition complete!',
        'message': 'Your review goal is done. A few sections are open — upgrade to Professional for the rest.',
    }


def build_review_growth_hints(agent):
    """Remaining-condition fragments for features this config would unlock."""
    cfg = get_review_growth_config()
    if not cfg.get('enabled') or not cfg.get('starter_unlock_enabled', True) or agent is None:
        return {}
    slug = _plan_slug(agent)
    if slug not in cfg.get('eligible_plans', []):
        return {}
    count = agent_review_count(agent)
    needed = cfg['min_reviews']
    if count >= needed:
        return {}
    fragment = f'{needed} reviews ({count}/{needed})'
    hints = {}
    for feat in cfg.get('unlock_feature_slugs') or []:
        if feat not in hints:
            hints[feat] = fragment
        for attr in FEATURE_ATTR_MAP.get(feat, []):
            if attr not in hints:
                hints[attr] = fragment
    return hints
