"""Absolute HTTPS URLs for Open Graph / WhatsApp link previews."""
import os

from django.conf import settings
from django.urls import reverse


def get_public_site_base(request) -> str:
    """
    Canonical site origin for social crawlers (always https on production domain).
    """
    base = (os.environ.get('APP_URL') or getattr(settings, 'APP_URL', '') or '').strip().rstrip('/')
    if not base:
        base = request.build_absolute_uri('/').rstrip('/')

    host = (request.get_host() or '').lower()
    if host.endswith('padosiagent.com') or 'padosiagent.com' in base:
        if base.startswith('http://'):
            base = 'https://' + base[len('http://') :]
        elif base.startswith('https://'):
            pass
        else:
            base = 'https://padosiagent.com'
    elif not settings.DEBUG and base.startswith('http://'):
        # Production behind TLS terminator — prefer https for og:image
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
