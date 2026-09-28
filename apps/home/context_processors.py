import json
from django.core.cache import cache
from apps.home.models.site_setting import SiteSetting

def footer_settings(request):
    """
    Exposes footer settings globally, cached using Django's caching framework.
    """
    cached_data = cache.get('footer_settings_data')
    if cached_data is None:
        keys = ['contact_email', 'contact_phone', 'contact_address', 'social_links', 'site_logo', 'site_name']
        settings_qs = SiteSetting.objects.filter(key__in=keys)
        settings_dict = {s.key: s.value for s in settings_qs}

        # Decode social links (since they are json dumps)
        social_links = settings_dict.get('social_links')
        if isinstance(social_links, str) and social_links.strip().startswith(('{', '[')):
            try:
                social_links = json.loads(social_links)
            except json.JSONDecodeError:
                social_links = {}
        elif not isinstance(social_links, dict):
            social_links = {}

        # Fill defaults if missing or empty
        cached_data = {
            'contact_email': settings_dict.get('contact_email') or 'support@padosiagent.com',
            'contact_phone': settings_dict.get('contact_phone') or '+91 80000 00000',
            'contact_address': settings_dict.get('contact_address') or 'Ahmedabad - 380009 Gujarat, India',
            'social_links': {
                'facebook': social_links.get('facebook') or '',
                'twitter': social_links.get('twitter') or '',
                'instagram': social_links.get('instagram') or '',
                'linkedin': social_links.get('linkedin') or '',
            },
            'site_logo': settings_dict.get('site_logo') or '',
            'site_name': settings_dict.get('site_name') or 'PadosiAgent',
        }
        cache.set('footer_settings_data', cached_data, timeout=None)

    return {
        'footer_settings': cached_data,
        'site_name': cached_data.get('site_name'),  # for backwards compatibility in base.html
    }

def seo_context(request):
    """
    Provides default SEO context variables across all pages.
    """
    from apps.agents.services.og_urls import build_og_absolute_url, get_public_site_base

    return {
        'default_canonical_url': build_og_absolute_url(request, request.path),
        'default_meta_title': 'PadosiAgent — Expert & Trusted Insurance Agent',
        'default_meta_description': 'Find trusted & verified insurance experts in your neighbourhood. Connect with your local PadosiAgent.',
        'default_og_image': build_og_absolute_url(request, '/static/img/logo.png'),
        'public_site_base': get_public_site_base(request),
    }


def calculator_nav(request):
    """Show Calculators in header/footer only when at least one is live."""
    from apps.home.models.calculator import Calculator, NAV_CACHE_KEY

    cached = cache.get(NAV_CACHE_KEY)
    if cached is None:
        try:
            cached = Calculator.objects.filter(is_active=True, engine_ready=True).exists()
        except Exception:
            cached = False
        cache.set(NAV_CACHE_KEY, cached, timeout=None)
    return {'show_calculators_nav': bool(cached)}

