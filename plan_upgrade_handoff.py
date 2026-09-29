"""One-time app-to-website plan upgrade links.

Shared by FastAPI (issues the link) and Django (consumes it). No framework imports.
The raw token is never stored; callers persist only the SHA-256 hash.
"""
import hashlib
import secrets
from datetime import datetime, timedelta
from urllib.parse import quote

HANDOFF_TTL_SECONDS = 180
ALLOWED_UPGRADE_SLUGS = ('starter', 'professional')
PLAN_RANK = {
    '': 0,
    'free_trial': 0,
    'starter': 1,
    'professional': 2,
    'exclusive': 3,
}

_SLUG_ALIASES = {
    'basic': 'starter',
    'standard': 'starter',
    'pro': 'professional',
}


def normalize_upgrade_slug(raw):
    slug = str(raw or '').strip().lower().replace(' ', '_').replace('-', '_')
    return _SLUG_ALIASES.get(slug, slug)


def plan_rank(slug):
    return PLAN_RANK.get(normalize_upgrade_slug(slug), 0)


def upgrade_target_allowed(current_plan, target_slug):
    """True when target is a paid plan strictly above the agent's current plan."""
    target = normalize_upgrade_slug(target_slug)
    if target not in ALLOWED_UPGRADE_SLUGS:
        return False
    return plan_rank(current_plan) < plan_rank(target)


def new_handoff_token():
    return secrets.token_urlsafe(32)


def hash_handoff_token(token):
    return hashlib.sha256(str(token or '').encode('utf-8')).hexdigest()


def handoff_expiry(now=None):
    now = now or datetime.now()
    return now + timedelta(seconds=HANDOFF_TTL_SECONDS)


def build_handoff_url(base_url, token):
    base = (base_url or '').rstrip('/')
    return f"{base}/agent/app-upgrade/?token={quote(str(token or ''), safe='')}"
