import json
from django.core.cache import cache
from apps.home.models.site_setting import SiteSetting

def footer_settings(request):
    """
    Exposes footer settings globally, cached using Django's caching framework.
    """
    cached_data = cache.get('footer_settings_data')
    if cached_data is None:
        keys = ['contact_email', 'contact_address', 'social_links', 'site_logo', 'site_name']
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
