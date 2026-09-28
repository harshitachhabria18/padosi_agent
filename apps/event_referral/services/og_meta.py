from apps.event_referral.constants import (
    PALDI_OG_DESCRIPTION,
    PALDI_OG_HEIGHT,
    PALDI_OG_STATIC_PATH,
    PALDI_OG_TITLE,
    PALDI_OG_WIDTH,
)


def paldi_og_context(request, *, referring_agent_name=None):
    """Open Graph fields for Paldi event page and EV- referral join links."""
    title = PALDI_OG_TITLE
    if referring_agent_name:
        title = f'48 HR Championship — Invited by {referring_agent_name} | PadosiAgent'
    return {
        'use_paldi_og': True,
        'paldi_og_image_url': request.build_absolute_uri(PALDI_OG_STATIC_PATH),
        'paldi_og_title': title,
        'paldi_og_description': PALDI_OG_DESCRIPTION,
        'paldi_og_width': PALDI_OG_WIDTH,
        'paldi_og_height': PALDI_OG_HEIGHT,
    }
