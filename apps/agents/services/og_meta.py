"""Open Graph context for agent profile / card share pages."""
from apps.agents.services.og_urls import agent_og_image_absolute_url, build_og_absolute_url


def profile_og_context(request, agent, *, display_name=None):
    """
    WhatsApp / Facebook need non-empty og:title and og:description.
    Never use zero-width or empty description — that breaks image previews.
    """
    name = (display_name or getattr(agent, 'fullname', None) or 'Insurance Advisor').strip()
    title = f'{name} | PadosiAgent'
    description = (
        f'Connect with {name}, a licensed Insurance & Financial Advisor on PadosiAgent. '
        'View services, ratings, and contact options.'
    )
    return {
        'og_share_title': title,
        'og_share_description': description,
        'og_image_absolute_url': agent_og_image_absolute_url(request, agent.id),
        'og_page_absolute_url': build_og_absolute_url(request, request.get_full_path()),
    }
