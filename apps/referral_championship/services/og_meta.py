from apps.agents.services.og_urls import build_og_absolute_url

CHAMPIONSHIP_OG_STATIC_PATH = '/static/img/championship_og.jpg'
CHAMPIONSHIP_OG_WIDTH = 1024
CHAMPIONSHIP_OG_HEIGHT = 384
CHAMPIONSHIP_OG_SHARE_TITLE = 'Agent Championship | PadosiAgent'
CHAMPIONSHIP_OG_DESCRIPTION = (
    'Join the PadosiAgent Championship — refer agents, unlock rewards, and win prizes.'
)


def championship_og_context(request, *, referring_agent_name=None):
    """Open Graph fields for PA- links and /agent/championship/ landing pages."""
    title = CHAMPIONSHIP_OG_SHARE_TITLE
    if referring_agent_name:
        title = f'Agent Championship — Invited by {referring_agent_name} | PadosiAgent'
    image_url = build_og_absolute_url(request, CHAMPIONSHIP_OG_STATIC_PATH)
    return {
        'use_championship_og': True,
        'championship_og_image_url': image_url,
        'og_image_absolute_url': image_url,
        'championship_og_title': title,
        'championship_og_share_title': CHAMPIONSHIP_OG_SHARE_TITLE,
        'championship_og_description': CHAMPIONSHIP_OG_DESCRIPTION,
        'championship_og_width': CHAMPIONSHIP_OG_WIDTH,
        'championship_og_height': CHAMPIONSHIP_OG_HEIGHT,
        'og_share_title': CHAMPIONSHIP_OG_SHARE_TITLE,
    }
