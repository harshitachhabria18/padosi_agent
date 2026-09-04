"""Agent QR preview/download and public card landing."""
import logging
import re

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET

from apps.agents.models import Agent
from apps.agents.services.qr_branded import get_or_create_qr_png
from apps.agents.services.review_growth import QR_TYPE_LABELS, QR_TYPES, is_qr_enabled, qr_access_for_plan
from apps.agents.views.dashboard import _resolve_agent_plan

logger = logging.getLogger(__name__)


def _resolve_agent_by_slug(slug):
    agent = Agent.objects.filter(profile__slug=slug).first()
    if not agent and str(slug).isdigit():
        agent = Agent.objects.filter(id=int(slug)).first()
    return agent


def _logged_in_agent(request):
    from apps.agents.services.account_auth import resolve_agent_for_user
    return resolve_agent_for_user(request.user)


def _png_response(png_bytes, filename, download=False):
    response = HttpResponse(png_bytes, content_type='image/png')
    disposition = 'attachment' if download else 'inline'
    safe_name = re.sub(r'[^A-Za-z0-9._-]+', '-', filename).strip('-') or 'qr.png'
    response['Content-Disposition'] = f'{disposition}; filename="{safe_name}"'
    response['Cache-Control'] = 'public, max-age=3600' if not download else 'private, no-store'
    return response


@login_required(login_url='agents:agent_login')
@require_GET
def agent_qr_image(request, qr_type):
    if qr_type not in QR_TYPES or not is_qr_enabled():
        raise Http404('QR service is not available')
    agent = _logged_in_agent(request)
    if not agent:
        raise Http404('Agent not found')
    plan = _resolve_agent_plan(agent.plan_type, agent=agent)
    if not qr_access_for_plan(plan):
        raise Http404('QR service is not available')
    png = get_or_create_qr_png(request, agent, qr_type)
    if not png:
        raise Http404('Could not generate QR code')
    slug = getattr(agent, 'agent_slug', None) or str(agent.id)
    return _png_response(png, f'PadosiAgent-{slug}-{qr_type}.png')


@login_required(login_url='agents:agent_login')
@require_GET
def agent_qr_download(request, qr_type):
    if qr_type not in QR_TYPES:
        raise Http404('QR download is not available')
    agent = _logged_in_agent(request)
    if not agent:
        raise Http404('Agent not found')
    plan = _resolve_agent_plan(agent.plan_type, agent=agent)
    if not qr_access_for_plan(plan, download=True):
        raise Http404('QR download is not available')
    png = get_or_create_qr_png(request, agent, qr_type)
    if not png:
        raise Http404('Could not generate QR code')
    slug = getattr(agent, 'agent_slug', None) or str(agent.id)
    return _png_response(png, f'PadosiAgent-{slug}-{qr_type}.png', download=True)


@require_GET
def public_qr_image(request, slug, qr_type):
    if qr_type not in QR_TYPES or not is_qr_enabled():
        raise Http404('QR service is not available')
    agent = _resolve_agent_by_slug(slug)
    if not agent:
        raise Http404('Agent not found')
    plan = _resolve_agent_plan(agent.plan_type, agent=agent)
    if not qr_access_for_plan(plan):
        raise Http404('QR service is not available')
    png = get_or_create_qr_png(request, agent, qr_type)
    if not png:
        raise Http404('Could not generate QR code')
    return _png_response(png, f'PadosiAgent-{slug}-{qr_type}.png')


@require_GET
def public_agent_card(request, slug):
    from django.http import Http404 as _Http404

    agent = _resolve_agent_by_slug(slug)
    if not agent:
        raise _Http404('Agent not found')
    profile = agent.get_primary_profile()
    if profile is None:
        raise _Http404('Agent profile not found')

    is_visible = bool(getattr(profile, 'is_profile_visible', False) or getattr(profile, 'is_card_visible', False))
    if agent.status in ('inactive', 'suspended', 'deleted') or not is_visible:
        return render(request, 'agents/profile_unavailable.html', {
            'agent': agent,
            'profile': profile,
        }, status=404)

    agent_plan = _resolve_agent_plan(agent.plan_type, agent=agent)
    display_name = (profile.display_name if profile else '') or agent.fullname or 'Agent'
    return render(request, 'agents/public_agent_card.html', {
        'agent': agent,
        'profile': profile,
        'agent_plan': agent_plan,
        'agentDisplayName': display_name,
        'qr_type_label': QR_TYPE_LABELS['card'],
    })


def _brand_logo_url():
    from django.templatetags.static import static
    from apps.home.models import SiteSetting

    logo = str(SiteSetting.get_value('site_logo', '') or '').strip()
    if logo.startswith('http://') or logo.startswith('https://') or logo.startswith('/'):
        return logo
    if logo:
        return logo if logo.startswith('static/') else f'/static/{logo.lstrip("/")}'
    return static('img/logo.png')


def advisor_review_context(request, agent):
    profile = agent.get_primary_profile() if hasattr(agent, 'get_primary_profile') else None
    slug = (getattr(profile, 'slug', None) if profile else None) or getattr(agent, 'agent_slug', None) or str(agent.id)
    name = (getattr(profile, 'display_name', None) if profile else None) or agent.fullname or 'Insurance Advisor'
    photo = ''
    if profile:
        photo = getattr(profile, 'profile_photo_url', '') or ''
    if not photo:
        from django.templatetags.static import static as static_url
        photo = static_url('img/avatar-icon.jpg')
    designation = 'Insurance Advisor'
    if profile and getattr(profile, 'agency_name', None):
        designation = f"Insurance Advisor · {profile.agency_name}"
    review_url = request.build_absolute_uri(
        reverse('agents:agent_public_review', kwargs={'slug': slug})
    )
    display_host = review_url.replace('https://', '').replace('http://', '').rstrip('/')
    return {
        'agent': agent,
        'profile': profile,
        'advisor_name': name,
        'advisor_designation': designation,
        'advisor_image': photo,
        'advisor_slug': slug,
        'review_url': review_url,
        'review_url_display': display_host,
        'brand_logo_url': _brand_logo_url(),
        'hide_header': True,
        'hide_footer': True,
    }


@require_GET
def public_review_page(request, slug):
    agent = _resolve_agent_by_slug(slug)
    if not agent:
        raise Http404('Agent not found')
    profile = agent.get_primary_profile()
    if profile is None:
        raise Http404('Agent profile not found')
    is_visible = bool(getattr(profile, 'is_profile_visible', False) or getattr(profile, 'is_card_visible', False))
    if agent.status in ('inactive', 'suspended', 'deleted') or not is_visible:
        return render(request, 'agents/profile_unavailable.html', {
            'agent': agent,
            'profile': profile,
        }, status=404)

    context = advisor_review_context(request, agent)
    context.update({
        'hide_header': False,
        'hide_footer': False,
        'review_post_url': reverse('agents:agent_store_review', kwargs={'slug': context['advisor_slug']}),
        'is_guest': not request.user.is_authenticated,
    })
    return render(request, 'agents/public_review.html', context)


@require_GET
def public_review_card(request, slug):
    agent = _resolve_agent_by_slug(slug)
    if not agent:
        raise Http404('Agent not found')
    profile = agent.get_primary_profile()
    if profile is None:
        raise Http404('Agent profile not found')
    is_visible = bool(getattr(profile, 'is_profile_visible', False) or getattr(profile, 'is_card_visible', False))
    owner = _logged_in_agent(request)
    is_owner = bool(owner and owner.id == agent.id)
    if not is_owner and (agent.status in ('inactive', 'suspended', 'deleted') or not is_visible):
        return render(request, 'agents/profile_unavailable.html', {
            'agent': agent,
            'profile': profile,
        }, status=404)
    context = advisor_review_context(request, agent)
    context['is_owner'] = is_owner
    return render(request, 'agents/review_card.html', context)


@login_required(login_url='agents:agent_login')
@require_GET
def agent_review_card_redirect(request):
    from django.shortcuts import redirect
    from django.urls import reverse

    agent = _logged_in_agent(request)
    if not agent:
        raise Http404('Agent not found')
    slug = getattr(agent, 'agent_slug', None) or str(agent.id)
    return redirect(reverse('agents:agent_review_card', kwargs={'slug': slug}))
