"""Absolute HTTPS URLs for Open Graph / WhatsApp link previews."""
import os

from django.conf import settings
from django.urls import reverse


CANONICAL_PADOSI_ORIGIN = 'https://padosiagent.com'


def _normalize_padosi_origin(url: str) -> str:
    url = (url or '').strip().rstrip('/')
    if url.startswith('http://'):
        url = 'https://' + url[len('http://') :]
    url = url.replace('https://www.padosiagent.com', 'https://padosiagent.com')
    url = url.replace('http://www.padosiagent.com', 'https://padosiagent.com')
    return url.rstrip('/')


def get_public_site_base(request) -> str:
    """
    Canonical site origin for social crawlers (always https, non-www on padosiagent.com).
    """
    env_base = (os.environ.get('APP_URL') or getattr(settings, 'APP_URL', '') or '').strip().rstrip('/')
    host = (request.get_host() or '').lower().split(':')[0]

    if host.endswith('padosiagent.com') or (env_base and 'padosiagent.com' in env_base.lower()):
        base = env_base if env_base and 'padosiagent.com' in env_base.lower() else CANONICAL_PADOSI_ORIGIN
        return _normalize_padosi_origin(base)

    base = env_base or request.build_absolute_uri('/').rstrip('/')
    if not settings.DEBUG and base.startswith('http://'):
        base = 'https://' + base[len('http://') :]
    return base.rstrip('/')


def build_og_absolute_url(request, path: str) -> str:
    """Join public site base with a path or pass through absolute URLs (normalized to https when needed)."""
    path = (path or '').strip()
    if not path:
        return get_public_site_base(request)
    if path.startswith('http://') or path.startswith('https://'):
        if 'padosiagent.com' in path and path.startswith('http://'):
            return 'https://' + path[len('http://') :]
        return path
    if not path.startswith('/'):
        path = '/' + path
    return get_public_site_base(request) + path


def agent_og_image_absolute_url(request, agent_id: int) -> str:
    path = reverse('agents:agent_og_image', kwargs={'agent_id': agent_id})
    return build_og_absolute_url(request, path)
