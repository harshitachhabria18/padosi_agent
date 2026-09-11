"""
Agent Registration Views — session-driven multi-step registration.

Flow:
  1. GET  /agent-registration/     → renders the page (OTP → Step1 → Step2)
  2. POST /agent-send-otp/         → generates OTP, sends via Brevo, stores in session
  3. POST /agent-verify-otp/       → verifies OTP, marks email verified in session
  4. POST /agent-register-step1/   → saves basic info to AgentDraft, advances to step 2
  5. POST /agent-register-step2/   → saves profile details, redirects to plans
"""

import json
import random
import time
import logging
import re
from decimal import Decimal, ROUND_HALF_UP

from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST, require_http_methods
from django.views.decorators.csrf import csrf_protect, csrf_exempt
from django.utils import timezone
from django.conf import settings

from apps.agents.models import Agent, AgentDraft, PromoCode
from apps.home.models import SiteSetting
from apps.home.models.pincode import Pincode
from apps.agents.services.brevo import send_otp_email
from apps.agents.services.feature_unlock import (
    resolve_checkout_plan_slug,
    plan_slug_from_name,
)
from apps.agents.services.razorpay_checkout import (
    MOCK_SIGNATURE,
    checkout_payload,
    create_checkout_order,
    gateway_failure_message,
    is_mock_payment,
    login_agent_user,
    mock_payment_id,
    razorpay_client,
)

logger = logging.getLogger(__name__)

# ─── Constants ──────────────────────────────────────────────────────────────────
OTP_EXPIRY_SECONDS = 600  # 10 minutes
ALL_INDIAN_STATES = [
    'Andhra Pradesh', 'Arunachal Pradesh', 'Assam', 'Bihar', 'Chhattisgarh',
    'Goa', 'Gujarat', 'Haryana', 'Himachal Pradesh', 'Jharkhand',
    'Karnataka', 'Kerala', 'Madhya Pradesh', 'Maharashtra', 'Manipur',
    'Meghalaya', 'Mizoram', 'Nagaland', 'Odisha', 'Punjab',
    'Rajasthan', 'Sikkim', 'Tamil Nadu', 'Telangana', 'Tripura',
    'Uttar Pradesh', 'Uttarakhand', 'West Bengal',
    'Andaman and Nicobar Islands', 'Chandigarh',
    'Dadra and Nagar Haveli and Daman and Diu',
    'Delhi', 'Jammu and Kashmir', 'Ladakh', 'Lakshadweep', 'Puducherry',
]

INSURANCE_SEGMENTS = [
    {'id': 'health', 'label': 'Health',  'icon': 'fas fa-heartbeat'},
    {'id': 'life',   'label': 'Life',    'icon': 'fas fa-user-shield'},
    {'id': 'motor',  'label': 'Motor',   'icon': 'fas fa-car'},
    {'id': 'sme',    'label': 'SME',     'icon': 'fas fa-building'},
]

LANGUAGE_OPTIONS = [
    'Hindi', 'English', 'Gujarati', 'Marathi', 'Tamil',
    'Telugu', 'Kannada', 'Bengali', 'Punjabi', 'Malayalam',
    'Odia', 'Urdu', 'Assamese', 'Rajasthani',
]

_DEFAULT_PRICING = {
    'scratch_card_enabled': True,
    'social_discount_active': True,
    'social_discount_amount': 200,
    'starter': {
        'name': "Starter's Plan",
        'full_price': 1999,
        'promo_price': 1499,
        'scratch_price': 1299,
        'description': 'Perfect for New Agents',
        'badge': 'STANDARD',
        'scratch_enabled': True,
    },
    'professional': {
        'name': "Professional's Plan",
        'full_price': 6999,
        'promo_price': 4999,
        'scratch_price': 4799,
        'description': 'For Established Professionals',
        'badge': 'RECOMMENDED',
        'scratch_enabled': True,
    },
    'promo_discount_label': 'Partner Promo Applied! Once in a lifetime offer!',
    'standard_label': 'Get started with our standard partner plans',
    'social_links': [
        {'platform': 'Instagram', 'url': 'https://instagram.com/padosiagent', 'icon': 'fa-instagram'},
        {'platform': 'Facebook', 'url': 'https://facebook.com/padosiagent', 'icon': 'fa-facebook'},
        {'platform': 'YouTube', 'url': 'https://youtube.com/@padosiagent', 'icon': 'fa-youtube'},
        {'platform': 'LinkedIn', 'url': 'https://linkedin.com/company/padosiagent', 'icon': 'fa-linkedin'},
    ],
    'follow_tiers': [
        {'follows': 1, 'discount_amount': 100, 'starter_price': 1399, 'prof_price': 4899},
        {'follows': 2, 'discount_amount': 200, 'starter_price': 1299, 'prof_price': 4799},
        {'follows': 3, 'discount_amount': 300, 'starter_price': 1199, 'prof_price': 4699},
        {'follows': 4, 'discount_amount': 500, 'starter_price': 999, 'prof_price': 4499},
    ],
}


def _get_tier_prices(pricing_config, follow_count):
    """Compute tier pricing and discounts based on the number of accounts followed."""
    if not isinstance(pricing_config, dict):
        pricing_config = dict(_DEFAULT_PRICING)

    starter_cfg = pricing_config.get('starter', _DEFAULT_PRICING['starter'])
    prof_cfg = pricing_config.get('professional', _DEFAULT_PRICING['professional'])

    starter_full = float(starter_cfg.get('full_price', 1999) or 1999)
    starter_promo = float(starter_cfg.get('promo_price', 1499) or 1499)
    starter_scratch = float(starter_cfg.get('scratch_price', starter_promo) or starter_promo)
    starter_scratch_enabled = _is_scratch_enabled(starter_cfg)

    prof_full = float(prof_cfg.get('full_price', 6999) or 6999)
    prof_promo = float(prof_cfg.get('promo_price', 4999) or 4999)
    prof_scratch = float(prof_cfg.get('scratch_price', prof_promo) or prof_promo)
    prof_scratch_enabled = _is_scratch_enabled(prof_cfg)

    starter_initial = starter_scratch if starter_scratch_enabled else starter_promo
    prof_initial = prof_scratch if prof_scratch_enabled else prof_promo

    social_active = pricing_config.get('social_discount_active', True)
    default_discount = float(pricing_config.get('social_discount_amount', 200) or 200)
    follow_tiers = [t for t in (pricing_config.get('follow_tiers') or []) if isinstance(t, dict)]

    starter_price = starter_initial
    prof_price = prof_initial
    applied_discount = 0.0

    if social_active and follow_count > 0:
        if follow_tiers:
            sorted_tiers = sorted(follow_tiers, key=_tier_follow_count, reverse=True)
            matched = False
            for tier in sorted_tiers:
                if follow_count >= _tier_follow_count(tier):
                    if tier.get('starter_price') and float(tier.get('starter_price')) > 0:
                        starter_price = float(tier.get('starter_price'))
                    elif tier.get('discount_amount'):
                        starter_price = max(0.0, starter_initial - float(tier.get('discount_amount')))
                    else:
                        starter_price = max(0.0, starter_initial - default_discount)

                    if tier.get('prof_price') and float(tier.get('prof_price')) > 0:
                        prof_price = float(tier.get('prof_price'))
                    elif tier.get('discount_amount'):
                        prof_price = max(0.0, prof_initial - float(tier.get('discount_amount')))
                    else:
                        prof_price = max(0.0, prof_initial - default_discount)

                    applied_discount = float(tier.get('discount_amount', default_discount) or default_discount)
                    matched = True
                    break
            if not matched:
                starter_price = max(0.0, starter_initial - default_discount)
                prof_price = max(0.0, prof_initial - default_discount)
                applied_discount = default_discount
        else:
            starter_price = max(0.0, starter_initial - default_discount)
            prof_price = max(0.0, prof_initial - default_discount)
            applied_discount = default_discount

    starter_base = int(round(starter_price))
    starter_gst = round(starter_base * 0.18, 2)
    starter_total = int(round(starter_base + starter_gst))

    prof_base = int(round(prof_price))
    prof_gst = round(prof_base * 0.18, 2)
    prof_total = int(round(prof_base + prof_gst))

    return {
        'starter_full': starter_full,
        'starter_price': starter_price,
        'starter_base': starter_base,
        'starter_gst': starter_gst,
        'starter_total': starter_total,
        'starter_scratch_price': starter_scratch,
        'prof_full': prof_full,
        'prof_price': prof_price,
        'prof_base': prof_base,
        'prof_gst': prof_gst,
        'prof_total': prof_total,
        'prof_scratch_price': prof_scratch,
        'applied_discount': applied_discount,
        'follow_count': follow_count,
    }


from django.core.cache import cache


def _exclusive_base_price(exclusive_config, follow_count=0, discount_unlocked=False):
    """Price shown/charged for the exclusive plan. Matches social-follow + discount-status."""
    config = exclusive_config or {}
    base_price = float(config.get('base_price', 0) or 0)
    follow_tiers = list(config.get('follow_tiers') or [])
    if follow_tiers:
        follow_tiers.sort(key=lambda t: int(t.get('follows', 0) or 0), reverse=True)
        for tier in follow_tiers:
            if follow_count >= int(tier.get('follows', 0) or 0):
                return float(tier.get('price', base_price) or base_price)
        if discount_unlocked:
            easiest = follow_tiers[-1]
            return float(easiest.get('price', config.get('discounted_price', base_price)) or base_price)
        return base_price
    if discount_unlocked:
        return float(config.get('discounted_price', base_price) or base_price)
    return base_price


def _to_money(value):
    return Decimal(str(value or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _to_paise(value):
    return int((_to_money(value) * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def _gst_total_from_inclusive(final_inclusive):
    base = int(round(float(final_inclusive) / 1.18, 0))
    gst = round(base * 0.18, 2)
    total = int(round(base + gst, 0))
    return base, gst, total


def _gst_bundle_from_base(base_amount):
    """GST-exclusive base → (base_rupees, gst, gst_inclusive_total). Matches chooseplan display."""
    base = int(round(float(base_amount or 0)))
    gst = round(base * 0.18, 2)
    total = int(round(base + gst, 0))
    return base, gst, total


def _tier_follow_count(tier):
    try:
        return int((tier or {}).get('follows', 0) or 0)
    except (TypeError, ValueError, AttributeError):
        return 0


def _session_follow_count(request, draft_id):
    followed = request.session.get(f'followed_platforms_{draft_id}') or []
    if isinstance(followed, (list, tuple, set)):
        return len(followed)
    return 0


def _scratch_session_key(plan_type):
    return f'scratch_revealed_{plan_type}'


def _parse_json_flag(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value == 1
    return str(value or '').strip().lower() in ('1', 'true', 'yes', 'on')


def _parse_displayed_total(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_scratch_enabled(cfg, default=True):
    if not isinstance(cfg, dict) or 'scratch_enabled' not in cfg:
        return default
    return _parse_json_flag(cfg.get('scratch_enabled'))


def _amounts_match(left, right, tolerance=1):
    try:
        return abs(float(left) - float(right)) <= tolerance
    except (TypeError, ValueError):
        return False


def _clear_scratch_reveal_session(request):
    """Plans page always starts at full price until the ribbon is scratched again."""
    changed = False
    for plan_type in ('starter', 'professional'):
        key = _scratch_session_key(plan_type)
        if key in request.session:
            request.session.pop(key, None)
            changed = True
    if changed:
        request.session.modified = True


def _scratch_revealed_for_checkout(request, data, plan_type, full_total, discounted_total=None):
    """
    Apply the scratch discount only when this page actually revealed it
    and the order summary is showing that discounted total.
    """
    displayed = _parse_displayed_total((data or {}).get('displayed_total'))
    if displayed is not None and full_total and _amounts_match(displayed, full_total):
        return False
    session_revealed = bool(request.session.get(_scratch_session_key(plan_type)))
    client_revealed = _parse_json_flag((data or {}).get('scratch_revealed'))
    if not (session_revealed and client_revealed):
        return False
    if discounted_total is not None and displayed is not None:
        return _amounts_match(displayed, discounted_total)
    return True


def _plan_payable_total(pricing_config, follow_count, plan_type, scratch_revealed=False, promo_obj=None):
    """
    Charge the amount shown on the card.
    Scratch-enabled plans stay at full_price + GST until the ribbon is revealed.
    """
    if not isinstance(pricing_config, dict):
        pricing_config = dict(_DEFAULT_PRICING)
    starter_cfg = pricing_config.get('starter') or _DEFAULT_PRICING['starter']
    prof_cfg = pricing_config.get('professional') or _DEFAULT_PRICING['professional']
    starter_full = float(starter_cfg.get('full_price', 1999) or 1999)
    prof_full = float(prof_cfg.get('full_price', 6999) or 6999)
    tier_info = _get_tier_prices(pricing_config, follow_count)

    if plan_type == 'starter':
        if promo_obj and not promo_obj.is_free_trial_code() and promo_obj.is_valid('basic'):
            base = max(0.0, starter_full - promo_obj.calculate_discount(starter_full))
            return _gst_bundle_from_base(base)[2]
        if _is_scratch_enabled(starter_cfg) and not scratch_revealed:
            return _gst_bundle_from_base(starter_full)[2]
        return tier_info['starter_total']

    if plan_type == 'professional':
        if promo_obj and not promo_obj.is_free_trial_code() and promo_obj.is_valid('professional'):
            base = max(0.0, prof_full - promo_obj.calculate_discount(prof_full))
            return _gst_bundle_from_base(base)[2]
        if _is_scratch_enabled(prof_cfg) and not scratch_revealed:
            return _gst_bundle_from_base(prof_full)[2]
        return tier_info['prof_total']

    return 0


def _checkout_total_for_plan(pricing_config, follow_count, plan_type, request, data, promo_obj=None):
    """Razorpay amount must match the on-screen order summary."""
    revealed_total = _plan_payable_total(
        pricing_config, follow_count, plan_type, scratch_revealed=True, promo_obj=promo_obj,
    )
    unrevealed_total = _plan_payable_total(
        pricing_config, follow_count, plan_type, scratch_revealed=False, promo_obj=promo_obj,
    )
    cfg_key = 'starter' if plan_type == 'starter' else 'professional'
    default_full = 1999 if plan_type == 'starter' else 6999
    full = float((pricing_config.get(cfg_key) or {}).get('full_price', default_full) or default_full)
    full_total = _gst_bundle_from_base(full)[2]
    if _scratch_revealed_for_checkout(request, data, plan_type, full_total, revealed_total):
        return revealed_total
    return unrevealed_total


def _paise_amounts_match(paid, expected, tolerance=100):
    """Allow ₹1 GST rounding difference between order amount and stored fee."""
    try:
        return abs(int(paid) - int(expected)) <= tolerance
    except (TypeError, ValueError):
        return False


def _is_in_progress_razorpay_error(error):
    """Netbanking/UPI redirects fire payment.failed before the bank returns."""
    if not isinstance(error, dict):
        return False
    step = str(error.get('step') or '').strip().lower()
    return step in ('payment_authentication', 'payment_capture')


def _recover_pending_razorpay_checkout(request, payload=None, retry=False):
    """
    After netbanking the browser often reloads /chooseplan/ instead of
    calling verify-payment. If Razorpay already captured the payment, finish it.
    """
    pending = request.session.get('pending_checkout') or {}
    payload = payload or {}
    agent_id = payload.get('agent_id') or pending.get('agent_id')
    order_id = payload.get('razorpay_order_id') or pending.get('order_id')
    from apps.agents.models import Agent, AgentSubscription

    agent = Agent.objects.filter(pk=agent_id).first() if agent_id else None
    if not agent and order_id:
        sub = AgentSubscription.objects.filter(razorpay_order_id=order_id).first()
        if sub:
            agent = sub.agent
    if not agent:
        return None
    if not verify_and_activate_pending_payment(agent):
        if not retry:
            return None
        time.sleep(1)
        if not verify_and_activate_pending_payment(agent):
            return None
    try:
        user = create_or_link_django_user(agent)
        login_agent_user(request, user)
    except Exception as login_err:
        logger.error('Pending checkout login failed for agent %s: %s', getattr(agent, 'id', None), login_err)

    request.session.pop('current_draft_id', None)
    request.session.pop('reg_step', None)
    request.session.pop('ref_code', None)
    request.session.pop('pending_checkout', None)

    from apps.distributors.views.dashboard import is_distributor
    if request.user.is_authenticated and is_distributor(request.user):
        return reverse('distributors:agents_index')
    return reverse('agents:agent_dashboard')


def _razorpay_callback_payload(request):
    data = {}
    if request.method == 'POST':
        content_type = (request.content_type or '').lower()
        if 'json' in content_type:
            try:
                data = json.loads(request.body or '{}')
            except json.JSONDecodeError:
                data = request.POST.dict()
        else:
            data = request.POST.dict()
    else:
        data = request.GET.dict()
    pending = request.session.get('pending_checkout') or {}
    return {
        'razorpay_payment_id': data.get('razorpay_payment_id'),
        'razorpay_order_id': data.get('razorpay_order_id') or pending.get('order_id'),
        'razorpay_signature': data.get('razorpay_signature'),
        'agent_id': data.get('agent_id') or pending.get('agent_id'),
        'plan_type': data.get('plan_type') or pending.get('plan_type'),
        'plan_name': data.get('plan_name') or pending.get('plan_name'),
        'error': data.get('error') or {
            'code': data.get('error[code]') or data.get('error_code'),
            'description': data.get('error[description]') or data.get('error_description'),
            'step': data.get('error[step]'),
            'reason': data.get('error[reason]'),
        },
    }


def _expected_amount_paise(registration_amount):
    return _to_paise(registration_amount)


def _get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '')

# ─── Helper ─────────────────────────────────────────────────────────────────────


def _get_registration_context(request):
    """Build the template context based on current session state."""
    session = request.session
    reg_step = session.get('reg_step', 0)
    email_verified = session.get('email_verified', False)
    verified_email = session.get('verified_email', '')

    # Load draft if exists
    draft = None
    draft_id = session.get('current_draft_id')
    if draft_id:
        try:
            draft = AgentDraft.objects.get(pk=draft_id)
        except AgentDraft.DoesNotExist:
            pass

    from apps.distributors.views.dashboard import is_distributor
    layout_template = 'base.html'
    if request.user.is_authenticated and is_distributor(request.user):
        layout_template = 'distributors/layout.html'

    from apps.agents.models import InvestmentType
    active_investment_types = InvestmentType.objects.filter(is_active=True)

    prefilled_promo = request.GET.get('promo') or request.GET.get('ref') or request.session.get('ref_code', '')
    prefilled_name = request.GET.get('name', '').strip()
    prefilled_phone = request.GET.get('phone', '').strip()
    prefilled_email = request.GET.get('email', '').strip()
    prefilled_pincode = request.GET.get('pincode', '').strip()
    prefilled_company = request.GET.get('company', '').strip()
    prefilled_source = request.GET.get('source', '').strip()
    prefilled_city = request.GET.get('city', '').strip()
    prefilled_state = request.GET.get('state', '').strip()
    prefilled_member_id = request.GET.get('member_id', '').strip()

    if prefilled_source:
        session['reg_source'] = prefilled_source
    if prefilled_company:
        session['reg_company'] = prefilled_company
    if prefilled_member_id:
        session['reg_member_id'] = prefilled_member_id

    return {
        'layout_template': layout_template,
        'reg_step': reg_step,
        'email_verified': email_verified,
        'verified_email': verified_email,
        'draft': draft,
        'default_states': list(Pincode.objects.values_list('state', flat=True).distinct().order_by('state')) or ALL_INDIAN_STATES,
        'segments': INSURANCE_SEGMENTS,
        'language_options': LANGUAGE_OPTIONS,
        'agent_segments': draft.segments if draft else [],
        'agent_languages': draft.languages if draft else [],
        'active_investment_types': active_investment_types,
        'prefilledPromo': prefilled_promo,
        'prefilledName': prefilled_name,
        'prefilledPhone': prefilled_phone,
        'prefilledEmail': prefilled_email,
        'prefilledPincode': prefilled_pincode,
        'prefilledCompany': prefilled_company or session.get('reg_company', ''),
        'prefilledSource': prefilled_source or session.get('reg_source', ''),
        'prefilledCity': prefilled_city,
        'prefilledState': prefilled_state,
        'prefilledMemberId': prefilled_member_id or session.get('reg_member_id', ''),
        'registration_swipe_enabled': False,
        'registration_swipe_slides': [],
        'preview_auto_advance_ms': 2000,
        'hide_site_nav': True,
        'hide_footer': True,
        'hide_chatbot': True,
    }


# ─── Views ──────────────────────────────────────────────────────────────────────

@require_http_methods(["GET"])
def agent_registration(request):
    """Render the registration page. Shows OTP, Step 1, or Step 2 based on session."""
    if request.user.is_authenticated:
        from apps.agents.models import Agent
        if Agent.objects.filter(user=request.user).exists() or request.user.is_staff or request.user.is_superuser:
            return redirect('agents:agent_dashboard')

    context = _get_registration_context(request)
    return render(request, 'agents/registration.html', context)



def _int_or_zero(value):
    try:
        digits = re.sub(r'\D', '', str(value or ''))
        return int(digits) if digits else 0
    except (TypeError, ValueError):
        return 0


def _unique_profile_slug(desired, exclude_pk=None):
    from django.utils.text import slugify
    from apps.agents.models import AgentProfile

    base = slugify(desired or '') or 'agent'
    slug = base
    n = 1
    while True:
        qs = AgentProfile.objects.filter(slug=slug)
        if exclude_pk:
            qs = qs.exclude(pk=exclude_pk)
        if not qs.exists():
            return slug
        slug = f'{base}-{n}'
        n += 1


def _public_profile_path(agent):
    slug = ''
    try:
        profile = getattr(agent, 'profile', None)
        slug = (profile.slug or '') if profile else ''
    except Exception:
        slug = ''
    if not slug:
        slug = getattr(agent, 'agent_slug', '') or ''
    if not slug:
        return reverse('agents:agent_dashboard')
    return reverse('agents:agent_public_profile', kwargs={'slug': slug})


def _activation_success_payload(request, agent, message='Payment successful and account activated.'):
    from apps.distributors.views.dashboard import is_distributor

    redirect_url = reverse('agents:agent_dashboard')
    try:
        if request.user.is_authenticated and is_distributor(request.user):
            redirect_url = reverse('distributors:agents_index')
    except Exception:
        pass
    profile_path = _public_profile_path(agent)
    return {
        'success': True,
        'message': message,
        'redirect_url': redirect_url,
        'agent_name': (getattr(agent, 'fullname', '') or '').strip(),
        'profile_url': request.build_absolute_uri(profile_path),
    }


def _assign_step1_draft_fields(draft, request, extra=None):
    extra = extra or {}
    draft.fullname = extra.get('fullname', request.POST.get('fullname', '').strip())
    draft.mobile = extra.get('mobile', request.POST.get('mobile', '').strip())
    draft.agent_pincode = extra.get('agent_pincode', request.POST.get('agent_pincode', '').strip())
    draft.state = extra.get('state', request.POST.get('state', '').strip())
    draft.experience_range = extra.get('experience', request.POST.get('experience_range', ''))
    draft.segments = extra.get('segments', request.POST.getlist('segments[]') or request.POST.getlist('segments'))
    draft.investment_types = extra.get(
        'investment_types',
        request.POST.getlist('investment_types[]') or request.POST.getlist('investment_types'),
    )
    draft.promo_code = extra.get('promo_code', request.POST.get('promo_code', '').strip())
    draft.address = extra.get('address', request.POST.get('address', '').strip())
    draft.client_base = extra.get('client_base', request.POST.get('client_base', '').strip())
    draft.slug = extra.get('slug', request.POST.get('slug', '').strip())
    draft.whatsapp = extra.get('whatsapp', request.POST.get('whatsapp', '').strip())
    draft.pan_number = extra.get('pan_number', request.POST.get('pan_number', '').strip().upper())
    draft.claims_settled = extra.get('claims_settled', _int_or_zero(request.POST.get('claims_settled')))
    draft.claim_amount = extra.get('claim_amount', request.POST.get('claim_amount', '').strip())
    company = extra.get('company', request.POST.get('company', '').strip()) or getattr(request, 'session', {}).get('reg_company', '')
    if company:
        draft.insurance_companies = [company]
    member_id = extra.get('member_id', request.POST.get('member_id', '').strip()) or getattr(request, 'session', {}).get('reg_member_id', '')
    if member_id and not draft.license_number:
        draft.license_number = member_id
    photo = request.FILES.get('photo')
    if photo:
        draft.photo = photo
    return draft
@require_http_methods(["GET"])
def check_slug_availability(request):
    """Check if a custom slug is available for an agent profile."""
    from django.utils.text import slugify
    from apps.agents.models import AgentProfile
    
    raw_slug = request.GET.get('slug', '').strip()
    if not raw_slug:
        return JsonResponse({'success': False, 'message': 'Slug is required.'})
        
    slug = slugify(raw_slug)
    
    # Check if slug exists in AgentProfile
    exists = AgentProfile.objects.filter(slug=slug).exists()
    
    if exists:
        return JsonResponse({
            'success': True,
            'available': False,
            'slug': slug,
            'message': 'This URL is already taken.'
        })
    else:
        return JsonResponse({
            'success': True,
            'available': True,
            'slug': slug,
            'message': 'URL is available!'
        })


@require_POST
@csrf_protect
def register_step1(request):
    """Save Step 1 (basic info) → create/update AgentDraft."""
    # Extract form data
    fullname = request.POST.get('fullname', '').strip()
    email = request.POST.get('email', '').strip().lower()
    mobile = request.POST.get('mobile', '').strip()
    agent_pincode = request.POST.get('agent_pincode', '').strip()
    state = request.POST.get('state', '').strip()
    experience = request.POST.get('experience_range', '')
    segments = request.POST.getlist('segments[]') or request.POST.getlist('segments')
    investment_types = request.POST.getlist('investment_types[]') or request.POST.getlist('investment_types')
    promo_code = request.POST.get('promo_code', '').strip()
    address = request.POST.get('address', '').strip()
    client_base = request.POST.get('client_base', '').strip()
    slug = request.POST.get('slug', '').strip()

    distributor_id = None
    from apps.distributors.views.dashboard import is_distributor
    if request.user.is_authenticated and is_distributor(request.user):
        from apps.admin_panel.models import User as LaravelUser
        l_user = LaravelUser.objects.filter(email=request.user.email).first()
        distributor_id = l_user.id if l_user else request.user.id
        request.session['distributor_id'] = distributor_id

    # Validation
    errors = []
    if not fullname:
        errors.append('Full name is required.')
    if not email or '@' not in email:
        errors.append('Please enter a valid email address.')
    if not mobile or len(mobile) != 10 or not mobile.isdigit():
        errors.append('Please enter a valid 10-digit mobile number.')
    if not agent_pincode or len(agent_pincode) != 6 or not agent_pincode.isdigit():
        errors.append('Please enter a valid 6-digit pincode.')
    if not state:
        errors.append('Please select a state.')
    if not segments and not investment_types:
        errors.append('Please select at least one insurance segment or investment type.')

    if errors:
        return JsonResponse({'success': False, 'message': ' '.join(errors)}, status=400)

    from django.contrib.auth.models import User
    from apps.agents.models import Agent, Invoice, AgentDraft

    # Check if a paid invoice exists matching this email (or user exists)
    if User.objects.filter(email=email).exists() or Invoice.objects.filter(agent_email=email, payment_status='paid').exists():
        return JsonResponse({
            'success': False,
            'message': f'You are already registered with {email}. Please login to access your dashboard.',
            'redirect': '/agent-login/'
        }, status=422)

    # Check if an Agent record already exists for the email but has NO paid invoice
    existing_agent = Agent.objects.filter(email=email).first()
    if existing_agent:
        # Case 4 (network lost): try to verify Razorpay payment directly first!
        if verify_and_activate_pending_payment(existing_agent):
            return JsonResponse({
                'success': True,
                'message': 'Payment verified successfully! Redirecting to dashboard...',
                'redirect': reverse('agents:agent_dashboard'),
            })

        is_claim = (request.POST.get('is_claim') == '1') or (request.POST.get('action') == 'claim')
        target_step = 2 if is_claim else 1

        # Reuse existing registration (Agent and AgentDraft)
        draft = AgentDraft.objects.filter(email=email).first()
        if not draft:
            session_key = request.session.session_key
            if not session_key:
                request.session.create()
                session_key = request.session.session_key
            draft = AgentDraft(session_key=session_key, email=email)

        _assign_step1_draft_fields(draft, request)
        draft.email = email
        draft.email_verified = True
        draft.registration_step = target_step
        if draft.promo_code:
            request.session['applied_promo_code'] = draft.promo_code
        elif not request.session.get('distributor_led_registration') and not request.session.get('distributor_id'):
            request.session.pop('applied_promo_code', None)
        draft.save()

        request.session['current_draft_id'] = draft.pk
        request.session['reg_step'] = 2

        # Update the existing Agent record to prevent stale data
        existing_agent.fullname = fullname
        existing_agent.mobile = mobile
        existing_agent.agent_pincode = agent_pincode
        existing_agent.experience_range = experience
        existing_agent.client_base = client_base
        existing_agent.save()

        logger.info(f'Agent Step 1 reused & updated — draft #{draft.pk}, email={email}, step={target_step}')

        return JsonResponse({
            'success': True,
            'message': 'Basic information updated!',
            'draft_id': draft.pk,
            'redirect': '/chooseplan/',
        })

    is_claim = (request.POST.get('is_claim') == '1') or (request.POST.get('action') == 'claim')
    target_step = 2 if is_claim else 1

    # Create or update draft
    session_key = request.session.session_key
    if not session_key:
        request.session.create()
        session_key = request.session.session_key

    draft_id = request.session.get('current_draft_id')
    draft = None
    if draft_id:
        try:
            existing = AgentDraft.objects.get(pk=draft_id)
            if existing.email and existing.email.strip().lower() == email:
                draft = existing
        except AgentDraft.DoesNotExist:
            pass

    if not draft:
        draft = AgentDraft.objects.filter(email=email).first() or AgentDraft(session_key=session_key, email=email)

    draft.email = email
    _assign_step1_draft_fields(draft, request)
    draft.email_verified = True
    draft.registration_step = target_step
    if draft.promo_code:
        request.session['applied_promo_code'] = draft.promo_code
    elif not request.session.get('distributor_led_registration') and not request.session.get('distributor_id'):
        request.session.pop('applied_promo_code', None)
    draft.save()

    request.session['current_draft_id'] = draft.pk
    request.session['reg_step'] = 2

    logger.info(f'Agent Step 1 saved — draft #{draft.pk}, email={email}, step={target_step}')

    return JsonResponse({
        'success': True,
        'message': 'Basic information saved!',
        'draft_id': draft.pk,
        'redirect': '/chooseplan/',
    })


@require_POST
@csrf_protect
def register_step2(request):
    """Save Step 2 (profile details) → advance to plan selection."""
    draft_id = request.session.get('current_draft_id')
    if not draft_id:
        return JsonResponse({'success': False, 'message': 'Registration session not found. Please start over.'}, status=400)

    try:
        draft = AgentDraft.objects.get(pk=draft_id)
    except AgentDraft.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Registration data not found.'}, status=400)

    # Extract form data
    about = request.POST.get('about', '').strip()
    languages = request.POST.getlist('languages[]') or request.POST.getlist('languages')
    certifications = request.POST.get('certifications', '').strip()

    # Handle photo upload
    photo = request.FILES.get('photo')
    if photo:
        draft.photo = photo

    draft.about = about
    draft.languages = languages
    draft.certifications = certifications
    draft.registration_step = 2
    draft.save()

    request.session['reg_step'] = 3  # Ready for payment/plans

    logger.info(f'Agent Step 2 saved — draft #{draft.pk}')

    return JsonResponse({
        'success': True,
        'message': 'Profile saved! Redirecting to plans...',
        'redirect': '/chooseplan/',
    })


@require_POST
def record_social_follow(request):
    """Record that the user successfully followed social accounts and compute plan discounts."""
    import json
    try:
        data = json.loads(request.body)
        platform = (data.get('platform') or '').lower()
        agent_id = data.get('agent_id')  # draft_id
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': 'Invalid JSON.'}, status=400)

    if not agent_id or not platform:
        return JsonResponse({'success': False, 'message': 'Missing data.'}, status=400)

    from apps.home.models import SiteSetting
    pricing_config = SiteSetting.get_value('pricing_config', _DEFAULT_PRICING)

    session_key = f'followed_platforms_{agent_id}'
    followed = request.session.get(session_key, [])
    if platform not in followed:
        followed.append(platform)
        request.session[session_key] = followed
        if hasattr(request.session, 'modified'):
            request.session.modified = True

    follow_count = len(followed)
    tier_info = _get_tier_prices(pricing_config, follow_count)

    return JsonResponse({
        'success': True,
        'message': 'Follow recorded successfully!',
        'discount_unlocked': follow_count > 0,
        'follow_count': follow_count,
        'applied_discount': tier_info['applied_discount'],
        'starter_price': tier_info['starter_price'],
        'starter_base': tier_info['starter_base'],
        'starter_total': tier_info['starter_total'],
        'prof_price': tier_info['prof_price'],
        'prof_base': tier_info['prof_base'],
        'prof_total': tier_info['prof_total'],
        'followed_platforms': followed,
    })


@require_POST
@csrf_protect
def record_scratch_reveal(request):
    """Persist that the user revealed the starter/professional scratch price."""
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        data = request.POST
    plan_type = resolve_checkout_plan_slug(data.get('plan_type'))
    if plan_type not in ('starter', 'professional'):
        return JsonResponse({'success': False, 'message': 'Invalid plan.'}, status=400)
    request.session[_scratch_session_key(plan_type)] = True
    request.session.modified = True
    return JsonResponse({'success': True, 'plan_type': plan_type})


def exclusive_discount_status(request):
    """Get the current discount status and followed platforms."""
    agent_id = request.GET.get('agent_id')
    if not agent_id:
        return JsonResponse({'success': False, 'message': 'Missing agent_id'}, status=400)
    
    session_key = f'followed_platforms_{agent_id}'
    followed = request.session.get(session_key, [])
    discount_unlocked = len(followed) > 0
    
    from apps.home.models import SiteSetting
    exclusive_config = SiteSetting.get_value('exclusive_plan_config') or {}
    
    follow_count = len(followed)
    current_price = _exclusive_base_price(exclusive_config, follow_count, discount_unlocked)
        
    if discount_unlocked:
        
        # Sync session state to database to heal any mismatched states
        from apps.agents.models import AgentDraft, UserPlanProgress
        try:
            draft = AgentDraft.objects.get(pk=agent_id)
            progress, _ = UserPlanProgress.objects.get_or_create(draft=draft, plan_key='exclusive_gamified')
            progress.discount_unlocked = True
            progress.save()
            logger.info(f"Healed and saved discount_unlocked=True for draft {draft.id}")
        except Exception as e:
            logger.error(f"Failed to heal UserPlanProgress in discount_status: {e}")

    return JsonResponse({
        'success': True,
        'discount_unlocked': discount_unlocked,
        'current_price': current_price,
        'followed_platforms': followed
    })



def chooseplan(request):
    """Render the plan selection page."""
    if request.user.is_authenticated:
        from apps.agents.services.account_auth import resolve_agent_for_user
        try:
            logged_in_agent = resolve_agent_for_user(request.user)
        except Exception:
            logged_in_agent = None
        if logged_in_agent:
            if logged_in_agent.status not in (
                'pending_payment', 'incomplete', 'pending_accounts_payment'
            ):
                return redirect('agents:agent_dashboard')
        elif request.user.is_staff or request.user.is_superuser:
            return redirect('agents:agent_dashboard')

    recovered_url = _recover_pending_razorpay_checkout(request)
    if recovered_url:
        return redirect(recovered_url)

    draft_id = request.session.get('current_draft_id')
    if not draft_id:
        return redirect('agents:agent_registration')

    try:
        from apps.agents.models import AgentDraft
        agent = AgentDraft.objects.get(pk=draft_id)
        if agent.registration_step < 2:
            agent.registration_step = 2
            agent.save(update_fields=['registration_step', 'updated_at'])
    except AgentDraft.DoesNotExist:
        request.session.pop('current_draft_id', None)
        return redirect('agents:agent_registration')

    _clear_scratch_reveal_session(request)

    # Load site settings pricing config from DB only
    pricing_config = SiteSetting.get_value('pricing_config', _DEFAULT_PRICING)
    if not isinstance(pricing_config, dict):
        pricing_config = dict(_DEFAULT_PRICING)

    starter_cfg = pricing_config.get('starter', _DEFAULT_PRICING['starter'])
    prof_cfg = pricing_config.get('professional', _DEFAULT_PRICING['professional'])
    if not starter_cfg or not prof_cfg:
        return render(request, '500.html', status=500)

    trial_config = SiteSetting.get_value('trial_plan_config')
    if not trial_config or not isinstance(trial_config, dict) or not trial_config.get('price'):
        trial_config = {'price': 1, 'is_active': True, 'duration_days': 30}

    trial_active = trial_config.get('is_active', True)
    trial_base_price = float(trial_config.get('price', 1))
    trial_duration = trial_config.get('duration_days', 30)

    # Promo codes
    applied_promo_code = request.session.get('applied_promo_code') or ''
    applied_promo_code = applied_promo_code.strip().upper()

    has_promo = False
    has_free_trial_promo = False
    has_starter_promo = False
    has_prof_promo = False

    promo_obj = None

    if applied_promo_code:
        try:
            promo_obj = PromoCode.objects.filter(code=applied_promo_code).first()
            if promo_obj and promo_obj.is_valid():
                has_promo = True
            else:
                promo_obj = None
        except Exception:
            pass

    if has_promo and promo_obj and promo_obj.is_free_trial_code():
        has_free_trial_promo = True

    # Calculate Trial plan price
    if has_free_trial_promo and promo_obj:
        if promo_obj.trial_price_override is not None:
            trial_base_price = float(promo_obj.trial_price_override)
        if float(promo_obj.discount_value) > 0:
            discount = promo_obj.calculate_discount(trial_base_price)
            trial_base_price = max(0.0, trial_base_price - discount)
        if promo_obj.trial_duration_days:
            trial_duration = promo_obj.trial_duration_days

    trial_final = trial_base_price + (trial_base_price * 0.18)

    # Scratch & Social Discounts
    starter_scratch_enabled = _is_scratch_enabled(starter_cfg)
    prof_scratch_enabled = _is_scratch_enabled(prof_cfg)
    scratch_card_enabled = starter_scratch_enabled or prof_scratch_enabled
    social_discount_active = pricing_config.get('social_discount_active', True)
    social_discount_amount = float(pricing_config.get('social_discount_amount', 200) or 200)
    social_links = pricing_config.get('social_links', _DEFAULT_PRICING['social_links'])
    follow_tiers = pricing_config.get('follow_tiers', _DEFAULT_PRICING['follow_tiers'])

    session_key = f'followed_platforms_{draft_id}'
    followed = request.session.get(session_key, [])
    follow_count = len(followed)
    has_social_discount = social_discount_active and follow_count > 0

    tier_info = _get_tier_prices(pricing_config, follow_count)
    starter_full = tier_info['starter_full']
    starter_discounted = tier_info['starter_price']
    starter_base = tier_info['starter_base']
    starter_gst = tier_info['starter_gst']
    starter_final = tier_info['starter_total']

    if not has_free_trial_promo and has_promo and promo_obj and promo_obj.is_valid('basic'):
        starter_base = int(round(max(0.0, starter_full - promo_obj.calculate_discount(starter_full))))
        starter_gst = round(starter_base * 0.18, 2)
        starter_final = int(round(starter_base + starter_gst))
        has_starter_promo = True

    starter_discount_percent = 0
    if starter_full > 0 and starter_base < starter_full:
        starter_discount_percent = round((1 - (starter_base / starter_full)) * 100)

    prof_full = tier_info['prof_full']
    prof_discounted = tier_info['prof_price']
    prof_base = tier_info['prof_base']
    prof_gst = tier_info['prof_gst']
    prof_final = tier_info['prof_total']

    if not has_free_trial_promo and has_promo and promo_obj and promo_obj.is_valid('professional'):
        prof_base = int(round(max(0.0, prof_full - promo_obj.calculate_discount(prof_full))))
        prof_gst = round(prof_base * 0.18, 2)
        prof_final = int(round(prof_base + prof_gst))
        has_prof_promo = True

    prof_discount_percent = 0
    if prof_full > 0 and prof_base < prof_full:
        prof_discount_percent = round((1 - (prof_base / prof_full)) * 100)

    starter_name = starter_cfg.get('name', "Starter's Plan")
    starter_desc = starter_cfg.get('description', 'Perfect for New Agents')
    prof_name = prof_cfg.get('name', "Professional's Plan")
    prof_desc = prof_cfg.get('description', 'For Established Professionals')

    trial_gst = round(trial_base_price * 0.18, 2)

    # Fetch Gamification Config
    exclusive_config = SiteSetting.get_value('exclusive_plan_config') or {}
    is_exclusive_active = exclusive_config.get('is_active', False)
    session_key = f'followed_platforms_{draft_id}'
    followed = request.session.get(session_key, [])
    follow_count = len(followed)
    discount_unlocked = follow_count > 0
    
    exc_strikeout = float(exclusive_config.get('strikeout_price', 6999))
    exc_base = float(exclusive_config.get('base_price', 1999))
    exc_discounted = _exclusive_base_price(exclusive_config, follow_count, discount_unlocked)
    
    if exc_strikeout > 0 and exc_base < exc_strikeout:
        exclusive_config['before_discount_val'] = f"{int(round((exc_strikeout - exc_base) / exc_strikeout * 100))}%"
    else:
        exclusive_config['before_discount_val'] = "0%"
        
    if exc_base > 0 and exc_discounted < exc_base:
        exclusive_config['after_discount_val'] = f"{int(round((exc_base - exc_discounted) / exc_base * 100))}%"
    else:
        exclusive_config['after_discount_val'] = "0%"

    # Prepare Gamification UI Context Variables
    default_features = [
        {'name': 'Permanent<br>Website', 'icon': 'fa-globe', 'color': '#16a34a', 'bg_color': '#f0fdf4'},
        {'name': 'Digital<br>Card', 'icon': 'fa-id-card-clip', 'color': '#6d28d9', 'bg_color': '#f3e8ff'},
        {'name': 'Licensed<br>Badge', 'icon': 'fa-shield-halved', 'color': '#f59e0b', 'bg_color': '#fffbeb'},
        {'name': 'Call &<br>WhatsApp', 'icon': 'fa-phone', 'color': '#16a34a', 'bg_color': '#f0fdf4'},
        {'name': 'Customer<br>Reviews', 'icon': 'fa-star', 'color': '#6d28d9', 'bg_color': '#f3e8ff'},
        {'name': 'Product<br>Showcase', 'icon': 'fa-store', 'color': '#3b82f6', 'bg_color': '#eff6ff'}
    ]
    premium_features = exclusive_config.get('premium_features', None)
    if premium_features is None:
        premium_features = default_features
        
    social_links = exclusive_config.get('social_links', [])
    social_labels = {
        'instagram': 'Instagram',
        'facebook': 'Facebook',
        'x': 'X',
        'twitter': 'X',
        'linkedin': 'LinkedIn',
        'youtube': 'YouTube',
        'whatsapp': 'WhatsApp',
    }
    for link in social_links:
        platform = (link.get('platform') or '').lower()
        link['platform_key'] = platform
        link['label'] = social_labels.get(platform, (link.get('platform') or '').title())
        user_icon = (link.get('icon') or '').strip()
        if user_icon.startswith('fa-'):
            link['iconClass'] = user_icon
        elif platform in ('x', 'twitter'):
            link['iconClass'] = 'fa-x-twitter'
        elif platform == 'linkedin':
            link['iconClass'] = 'fa-linkedin-in'
        elif platform == 'facebook':
            link['iconClass'] = 'fa-facebook-f'
        elif platform == 'youtube':
            link['iconClass'] = 'fa-youtube'
        else:
            link['iconClass'] = 'fa-instagram'

    checkout_label = (exclusive_config.get('checkout_btn_text') or 'Claim Now').strip()
    if checkout_label.upper() in ('BUY', 'CLAIM OFFER'):
        checkout_label = 'Claim Now'
    exclusive_config['checkout_btn_text'] = checkout_label

    title_prefix = (exclusive_config.get('title_prefix') or 'Surprise!!!!').strip()
    if title_prefix in ('Surprise!', 'Surprise'):
        title_prefix = 'Surprise!!!!'
    exclusive_config['title_prefix'] = title_prefix

    gift_subtitle = (exclusive_config.get('gift_subtitle') or '').strip()
    if gift_subtitle in (
        '',
        'For a limited time, get our best deal.',
        'Follow our social handles to reveal your secret discounted price.',
    ):
        exclusive_config['gift_subtitle'] = 'Follow us on Social Media...'

    try:
        total_seats = int(exclusive_config.get('total_seats') or 10000)
    except (TypeError, ValueError):
        total_seats = 10000
    try:
        claimed_seats = int(exclusive_config.get('base_claimed_seats') or 0)
    except (TypeError, ValueError):
        claimed_seats = 0
    spots_left = max(0, total_seats - claimed_seats)

    def _format_urgency(template, fallback):
        text = template or fallback
        try:
            return text.format(
                total_seats=total_seats,
                claimed_seats=claimed_seats,
                spots_left=spots_left,
            )
        except (KeyError, ValueError, IndexError):
            return text

    urgency_line_1 = _format_urgency(
        exclusive_config.get('urgency_line_1'),
        '🔥 Hurry! Offer valid only for the first {total_seats} users!',
    )
    urgency_line_2 = _format_urgency(
        exclusive_config.get('urgency_line_2'),
        '🔥 {claimed_seats}/{total_seats} Claimed',
    )

    context = {
        'draft': agent,  # Pass agent as draft to avoid template changes
        'agent': agent,
        'pricing_config': pricing_config,
        'scratch_card_enabled': scratch_card_enabled,
        'starter_scratch_enabled': starter_scratch_enabled,
        'prof_scratch_enabled': prof_scratch_enabled,
        'starter_scratch_revealed': False,
        'prof_scratch_revealed': False,
        'starter_full_total': _gst_bundle_from_base(starter_full)[2],
        'prof_full_total': _gst_bundle_from_base(prof_full)[2],
        'social_discount_active': social_discount_active,
        'social_discount_amount': social_discount_amount,
        'social_links': social_links,
        'follow_tiers': follow_tiers,
        'follow_tiers_json': json.dumps(follow_tiers),
        'has_social_discount': has_social_discount,
        'followed_platforms': followed,
        'trial_config': trial_config,
        'trial_active': trial_active,
        'trial_base_price': trial_base_price,
        'trial_gst': trial_gst,
        'trial_final': trial_final,
        'trial_duration': trial_duration,
        
        'starter_name': starter_name,
        'starter_desc': starter_desc,
        'starter_full': starter_full,
        'starter_discounted': starter_discounted,
        'starter_final': starter_final,
        'starter_gst': starter_gst,
        'starter_base': starter_base,
        'starter_scratch_price': tier_info['starter_scratch_price'],
        'starter_discount_percent': starter_discount_percent,
        
        'prof_name': prof_name,
        'prof_desc': prof_desc,
        'prof_full': prof_full,
        'prof_discounted': prof_discounted,
        'prof_final': prof_final,
        'prof_gst': prof_gst,
        'prof_base': prof_base,
        'prof_scratch_price': tier_info['prof_scratch_price'],
        'prof_discount_percent': prof_discount_percent,

        'applied_promo_code': applied_promo_code,
        'has_promo': has_promo,
        'has_free_trial_promo': has_free_trial_promo,
        'has_starter_promo': has_starter_promo,
        'has_prof_promo': has_prof_promo,

        'is_upgrade_flow': False,
        'exclusive_config': exclusive_config,
        'is_exclusive_active': is_exclusive_active,
        'discount_unlocked': discount_unlocked,
        'premiumFeatures': premium_features,
        'spots_left': spots_left,
        'urgency_line_1': urgency_line_1,
        'urgency_line_2': urgency_line_2,
    }

    return render(request, 'agents/plans.html', context)



def create_agent_from_draft(draft, plan_type, plan_name, status='pending_payment'):
    from apps.agents.models import Agent, AgentProfile, AgentInsuranceSegment
    
    now = timezone.now()

    profession = 'LIC Agent'
    company_str = str(draft.insurance_companies or '').lower()
    promo_str = str(draft.promo_code or '').upper()
    if 'liafi' in company_str or promo_str == 'LIAFI':
        profession = 'LIAFI Agent'
    elif 'lic' in company_str or promo_str == 'BIMASAKHI':
        profession = 'LIC Agent'
    
    agent, created = Agent.objects.get_or_create(
        email=draft.email,
        defaults={
            'fullname': draft.fullname,
            'mobile': draft.mobile,
            'user_types': ['insurance_agent'],
            'insurance_companies': draft.insurance_companies or [],
            'profession': profession,
            'experience_range': draft.experience_range or '',
            'client_base': draft.client_base or '',
            'registration_step': 2,
            'status': status,
            'plan_type': plan_type,
            'agent_pincode': draft.agent_pincode,
            'email_verified_at': now,
        }
    )
    
    if not created:
        agent.fullname = draft.fullname
        agent.mobile = draft.mobile
        agent.insurance_companies = draft.insurance_companies or []
        agent.profession = profession
        agent.experience_range = draft.experience_range or ''
        agent.client_base = draft.client_base or ''
        agent.status = status
        agent.plan_type = plan_type
        agent.agent_pincode = draft.agent_pincode
        agent.email_verified_at = now
        agent.save()
    
    # Create insurance segments (delete + insert like PHP)
    AgentInsuranceSegment.objects.filter(agent=agent).delete()
    for seg in (draft.segments or []):
        AgentInsuranceSegment.objects.create(agent=agent, segment_type=seg)
    
    is_liafi = (profession == 'LIAFI Agent') or ('liafi' in company_str) or (promo_str == 'LIAFI')
    member_id = draft.license_number or ''
    if is_liafi and member_id and 'LIAFI Member ID' not in (agent.admin_notes or ''):
        agent.admin_notes = (str(agent.admin_notes or '') + f"\nLIAFI Member ID: {member_id}").strip()

    # Write registration_draft JSON (matching PHP Step 2)
    agent.registration_draft = {
        'member_id': member_id if is_liafi else '',
        'license_number': draft.license_number or '',
        'pan_number': draft.pan_number or '',
        'software_name': draft.software_name or '',
        'portfolio_breakdown': {
            'life_insurance': draft.life_insurance or 0,
            'health_insurance': draft.health_insurance or 0,
            'general_insurance': draft.general_insurance or 0,
            'motor': draft.motor or 0,
        },
        'desired_services': draft.desired_services or [],
    }
    agent.save(update_fields=['admin_notes', 'registration_draft', 'updated_at'])
    
    profile, p_created = AgentProfile.objects.get_or_create(
        agent=agent,
        defaults={
            'license_number': draft.license_number or '',
            'license_valid_till': draft.license_valid_till,
            'arn_number': draft.arn_number or '',
            'euin_number': draft.euin_number or '',
            'investment_valid_till': draft.investment_valid_till,
            'investment_types': draft.investment_types or [],
            'pan_number': draft.pan_number or '',
            'software_name': draft.software_name or '',
            'portfolio_breakdown': {
                'life_insurance': draft.life_insurance or 0,
                'health_insurance': draft.health_insurance or 0,
                'general_insurance': draft.general_insurance or 0,
                'motor': draft.motor or 0,
            },
            'desired_services': draft.desired_services or [],
        }
    )
    if not p_created:
        profile.license_number = draft.license_number or ''
        profile.license_valid_till = draft.license_valid_till
        profile.arn_number = draft.arn_number or ''
        profile.euin_number = draft.euin_number or ''
        profile.investment_valid_till = draft.investment_valid_till
        profile.investment_types = draft.investment_types or []
        profile.pan_number = draft.pan_number or ''
        profile.software_name = draft.software_name or ''
        profile.portfolio_breakdown = {
            'life_insurance': draft.life_insurance or 0,
            'health_insurance': draft.health_insurance or 0,
            'general_insurance': draft.general_insurance or 0,
            'motor': draft.motor or 0,
        }
        profile.desired_services = draft.desired_services or []
        profile.save()
    
    # Clear registration_draft after committing to profile (matching PHP)
    agent.registration_draft = None
    agent.save(update_fields=['registration_draft', 'updated_at'])
    
    return agent


def create_or_link_django_user(agent, plain_password=None):
    from apps.agents.services.account_auth import create_or_link_django_user as _create_or_link
    return _create_or_link(agent, plain_password=plain_password)


def verify_and_activate_pending_payment(agent):
    """
    Directly query Razorpay to verify if the pending order has a captured/authorized payment,
    and activate the subscription/registration atomically and idempotently.
    """
    from django.utils import timezone
    from django.db import transaction
    from apps.agents.models import AgentSubscription, Invoice, PromoCode
    from apps.home.models import SiteSetting

    if Invoice.objects.filter(agent_email=agent.email, payment_status='paid').exists():
        logger.info(f"[verify_and_activate_pending_payment] Active invoice exists for {agent.email}. Already active.")
        return True

    subscription = AgentSubscription.objects.filter(
        agent=agent,
        payment_status__in=['pending', 'failed'],
    ).order_by('-created_at').first()
    if not subscription or not subscription.razorpay_order_id:
        logger.info(f"[verify_and_activate_pending_payment] No pending/failed subscription or Razorpay Order ID for {agent.email}")
        return False

    try:
        client = razorpay_client()
        if client is None:
            logger.error("[verify_and_activate_pending_payment] Razorpay keys not configured.")
            return False
        payments = client.order.payments(subscription.razorpay_order_id)
    except Exception as err:
        logger.error(f"[verify_and_activate_pending_payment] Razorpay API call failed: {err}")
        return False

    successful_payment = None
    if payments and 'items' in payments:
        for item in payments['items']:
            if item.get('status') in ('captured', 'authorized'):
                successful_payment = item
                break

    if not successful_payment:
        logger.info(f"[verify_and_activate_pending_payment] No captured/authorized payments found for Order {subscription.razorpay_order_id}")
        return False

    paid_amount_paise = successful_payment.get('amount')
    expected_amount_paise = _expected_amount_paise(subscription.registration_amount)
    if not _paise_amounts_match(paid_amount_paise, expected_amount_paise):
        logger.critical(
            f"[verify_and_activate_pending_payment] Price tampering check failed! "
            f"Paid: {paid_amount_paise}, Expected: {expected_amount_paise}"
        )
        return False

    try:
        with transaction.atomic():
            # Locked subscription retrieve
            subscription = AgentSubscription.objects.select_for_update().get(pk=subscription.pk)
            if subscription.payment_status == 'completed':
                return True

            plan_type = plan_slug_from_name(subscription.selected_plan) or 'professional'
            is_trial = plan_type == 'free_trial'

            trial_config = SiteSetting.get_value('trial_plan_config', {'duration_days': 30})
            trial_days = int(trial_config.get('duration_days', 30))
            sub_expiry = timezone.now() + timezone.timedelta(days=365)

            if is_trial:
                agent.status = 'active'
                agent.plan_type = 'free_trial'
                agent.trial_ends_at = timezone.now() + timezone.timedelta(days=trial_days)
                upgrade_discount = SiteSetting.get_value('trial_upgrade_discount', 20)
                agent.upgrade_discount_percent = int(upgrade_discount)
                sub_expiry = timezone.now() + timezone.timedelta(days=trial_days)
            else:
                agent.status = 'pending_approval'
                agent.plan_type = plan_type

            agent.registration_step = 2
            agent.save()

            subscription.payment_status = 'completed'
            subscription.status = 'active'
            subscription.razorpay_payment_id = successful_payment.get('id')
            subscription.razorpay_signature = successful_payment.get('signature') or 'direct_verification'
            subscription.starts_at = timezone.now()
            subscription.expires_at = sub_expiry
            subscription.save()

            # Increment used count of Promo Code
            if subscription.promo_code:
                try:
                    promo = PromoCode.objects.filter(code=subscription.promo_code).first()
                    if promo:
                        promo.times_used += 1
                        promo.save(update_fields=['times_used'])
                except Exception:
                    pass

            # Referral credit conversion
            if agent.referred_by_code:
                try:
                    from apps.admin_panel.models.referral_code import ReferralCode
                    from apps.admin_panel.models.referral_usage import ReferralUsage
                    ref_code_obj = ReferralCode.objects.filter(code=agent.referred_by_code).first()
                    if ref_code_obj:
                        usage, u_created = ReferralUsage.objects.get_or_create(
                            referral_code=ref_code_obj,
                            referred_agent_id=agent.id,
                            defaults={'status': 'converted', 'signed_up_at': timezone.now()}
                        )
                        if not u_created and usage.status != 'converted':
                            usage.status = 'converted'
                            usage.save()

                        actual_conversions = ReferralUsage.objects.filter(
                            referral_code=ref_code_obj,
                            status='converted'
                        ).count()
                        ref_code_obj.total_referrals = actual_conversions
                        ref_code_obj.save()

                        if actual_conversions >= 5:
                            referring_agent = Agent.objects.filter(pk=ref_code_obj.agent_id).first()
                            if referring_agent and referring_agent.plan_type == 'free_trial':
                                referring_agent.referral_reward_type = 'pro_plan_1rs'
                                referring_agent.referral_reward_earned_at = timezone.now()
                                referring_agent.save()
                except Exception as ref_err:
                    logger.warning(f"[verify_and_activate_pending_payment] Referral credit conversion failed: {ref_err}")

            # Auto-generate referral code for agent
            try:
                from apps.admin_panel.models.referral_code import ReferralCode
                if not ReferralCode.objects.filter(agent=agent).exists():
                    ReferralCode.generateForAgent(agent)
            except Exception:
                pass

            # Link user
            user = create_or_link_django_user(agent)

            # Generate Invoice and send welcome credentials email
            try:
                import os
                from apps.agents.services.invoice import invoice_service
                from apps.agents.services.brevo import email_service

                invoice = invoice_service.generate_from_subscription(agent, subscription)
                pdf_path = None
                if invoice and invoice.pdf_path:
                     pdf_path = os.path.join(settings.MEDIA_ROOT, 'app', 'private', invoice.pdf_path)

                email_service.send_welcome(
                    to_email=agent.email,
                    to_name=agent.fullname,
                    temp_password=agent.email,
                    plan_name=subscription.selected_plan,
                    attachment_path=pdf_path
                )
            except Exception as mail_err:
                logger.error(f"[verify_and_activate_pending_payment] Failed to generate invoice/send welcome email: {mail_err}")

            logger.info(f"[verify_and_activate_pending_payment] Successfully activated agent {agent.email} via direct Razorpay query.")
            return True
    except Exception as db_err:
        logger.error(f"[verify_and_activate_pending_payment] Database activation transaction failed: {db_err}")
        return False



@require_POST
@csrf_protect
def agent_register_complete(request):
    """
    Prepare order or complete registration.
    """
    try:
        return _agent_register_complete_impl(request)
    except Exception:
        logger.exception('agent_register_complete failed')
        return JsonResponse({
            'success': False,
            'message': 'Unable to start payment right now. Please try again.',
        })


def _agent_register_complete_impl(request):
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        data = request.POST

    raw_plan_type = data.get('plan_type')
    plan_name = data.get('plan_name')
    plan_type = resolve_checkout_plan_slug(raw_plan_type, plan_name)
    if not plan_type:
        logger.error(f"Invalid plan selected. plan_type received: {repr(raw_plan_type)}")
        return JsonResponse({'success': False, 'message': 'Invalid plan selected.'}, status=400)

    draft_id = request.session.get('current_draft_id')
    if not draft_id:
        return JsonResponse({'success': False, 'message': 'Session expired. Please start over.'}, status=400)

    try:
        draft = AgentDraft.objects.get(pk=draft_id)
    except AgentDraft.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Registration record not found.'}, status=404)

    # Calculate pricing from DB only — no static fallback
    pricing_config = SiteSetting.get_value('pricing_config')
    if not pricing_config or not isinstance(pricing_config, dict):
        return JsonResponse({'success': False, 'message': 'Server configuration error.'}, status=500)

    starter_cfg = pricing_config.get('starter')
    prof_cfg = pricing_config.get('professional')
    if not starter_cfg or not prof_cfg or not starter_cfg.get('full_price') or not prof_cfg.get('full_price'):
        return JsonResponse({'success': False, 'message': 'Server configuration error.'}, status=500)

    trial_config = SiteSetting.get_value('trial_plan_config')
    if not trial_config or not isinstance(trial_config, dict) or not trial_config.get('price'):
        return JsonResponse({'success': False, 'message': 'Server configuration error.'}, status=500)

    applied_promo_code = (request.session.get('applied_promo_code') or '').strip().upper()
    has_promo = bool(applied_promo_code)
    has_free_trial_promo = False

    promo_obj = None

    if applied_promo_code:
        try:
            promo_obj = PromoCode.objects.filter(code=applied_promo_code).first()
        except Exception:
            pass

    if promo_obj and promo_obj.is_free_trial_code() and promo_obj.is_valid():
        has_free_trial_promo = True

    trial_base_price = float(trial_config['price'])
    starter_full = float(starter_cfg['full_price'])
    prof_full = float(prof_cfg['full_price'])
    
    if plan_type == 'free_trial':
        if has_free_trial_promo and promo_obj:
            if promo_obj.trial_price_override is not None:
                trial_base_price = float(promo_obj.trial_price_override)
            if float(promo_obj.discount_value) > 0:
                trial_base_price = max(0.0, trial_base_price - promo_obj.calculate_discount(trial_base_price))
        total_amount = trial_base_price + (trial_base_price * 0.18)
        plan_name = plan_name or f"Trial Plan ({trial_config.get('duration_days', 30)} Days)"
    elif plan_type == 'exclusive':
        exclusive_config = SiteSetting.get_value('exclusive_plan_config') or {}
        
        from apps.agents.models import UserPlanProgress
        session_key = f'followed_platforms_{draft_id}'
        followed = request.session.get(session_key, [])
        follow_count = len(followed)
        discount_unlocked = follow_count > 0
        progress = UserPlanProgress.objects.filter(draft=draft, plan_key='exclusive_gamified').first()
        if progress and progress.discount_unlocked:
            discount_unlocked = True
            
        base_price = _exclusive_base_price(exclusive_config, follow_count, discount_unlocked)
        total_amount = round(base_price + round(base_price * 0.18, 2), 2)
        plan_name = plan_name or exclusive_config.get('name') or 'Exclusive Plan'
        logger.info(f"Exclusive Checkout: discount_unlocked={discount_unlocked}, follow_count={follow_count}, base_price={base_price}, total_amount={total_amount}")
    elif plan_type == 'starter':
        session_key = f'followed_platforms_{draft_id}'
        followed = request.session.get(session_key, [])
        follow_count = len(followed)
        checkout_promo = promo_obj if (not has_free_trial_promo and has_promo) else None
        total_amount = _checkout_total_for_plan(
            pricing_config, follow_count, 'starter', request, data, checkout_promo,
        )
        plan_name = plan_name or starter_cfg.get('name') or "Starter's Plan"
        logger.info(
            'Starter checkout: full=%s displayed=%s follow=%s total=%s',
            starter_full, data.get('displayed_total'), follow_count, total_amount,
        )
    else:
        session_key = f'followed_platforms_{draft_id}'
        followed = request.session.get(session_key, [])
        follow_count = len(followed)
        checkout_promo = promo_obj if (not has_free_trial_promo and has_promo) else None
        total_amount = _checkout_total_for_plan(
            pricing_config, follow_count, 'professional', request, data, checkout_promo,
        )
        plan_name = plan_name or prof_cfg.get('name') or "Professional's Plan"
        logger.info(
            'Professional checkout: full=%s displayed=%s follow=%s total=%s',
            prof_full, data.get('displayed_total'), follow_count, total_amount,
        )

    total_amount = _to_money(total_amount)
    amount_paise = _to_paise(total_amount)
    razorpay_order_id, mock_checkout = create_checkout_order(
        amount_paise,
        f'agent_draft_{draft.pk}_{int(time.time())}',
        request,
    )

    # Strict Production Guard: If order creation fails for a paid plan, prevent bypass
    if not razorpay_order_id and amount_paise > 0:
        return JsonResponse({
            'success': False,
            'message': gateway_failure_message(),
        })

    from django.db import transaction
    from apps.agents.models import Agent, AgentSubscription, Invoice

    instant_complete = False
    try:
        with transaction.atomic():
            # Create/get Agent record from DB
            agent = create_agent_from_draft(draft, plan_type, plan_name, status='pending_payment')
            
            # Capture distributor/referral binding
            dist_id_from_session = request.session.get('distributor_id')
            if dist_id_from_session:
                agent.distributor_id = dist_id_from_session
                from apps.admin_panel.models.referral_code import ReferralCode
                ref_obj = ReferralCode.objects.filter(distributor_id=dist_id_from_session, is_active=True).first()
                if ref_obj:
                    agent.referred_by_code = ref_obj.code
                agent.save()
            else:
                ref_code = request.session.get('ref_code') or request.session.get('applied_promo_code')
                if ref_code:
                    from apps.admin_panel.models.referral_code import ReferralCode
                    ref_obj = ReferralCode.objects.filter(code=ref_code, is_active=True).first()
                    if ref_obj:
                        agent.referred_by_code = ref_code
                        if ref_obj.distributor_id:
                            agent.distributor_id = ref_obj.distributor_id
                        agent.save()
            
            # Calculate subscription duration
            trial_days = int(trial_config.get('duration_days', 30))
            sub_expiry = timezone.now() + timezone.timedelta(days=365)
            if plan_type == 'free_trial':
                sub_expiry = timezone.now() + timezone.timedelta(days=trial_days)

            # Find or create a pending subscription to prevent MultipleObjectsReturned
            subscription = AgentSubscription.objects.filter(agent=agent, payment_status='pending').order_by('-created_at').first()
            if subscription:
                subscription.selected_plan = plan_name or plan_type
                subscription.promo_code = applied_promo_code or None
                subscription.registration_amount = total_amount
                subscription.razorpay_order_id = razorpay_order_id
                subscription.status = 'inactive'
                subscription.save()
            else:
                subscription = AgentSubscription.objects.create(
                    agent=agent,
                    selected_plan=plan_name or plan_type,
                    promo_code=applied_promo_code or None,
                    registration_amount=total_amount,
                    payment_status='pending',
                    status='inactive',
                    razorpay_order_id=razorpay_order_id
                )

            # If 0 amount: complete instantly
            if amount_paise == 0:
                subscription.payment_status = 'completed'
                subscription.status = 'active'
                subscription.starts_at = timezone.now()
                subscription.expires_at = sub_expiry
                subscription.save()
                
                agent.status = 'active'
                if plan_type == 'free_trial':
                    agent.trial_ends_at = timezone.now() + timezone.timedelta(days=trial_days)
                    upgrade_discount = SiteSetting.get_value('trial_upgrade_discount', 20)
                    agent.upgrade_discount_percent = int(upgrade_discount)
                agent.save()

                # Handle referral credit
                if agent.referred_by_code:
                    try:
                        from apps.admin_panel.models.referral_code import ReferralCode
                        from apps.admin_panel.models.referral_usage import ReferralUsage
                        
                        ref_code_obj = ReferralCode.objects.filter(code=agent.referred_by_code).first()
                        if ref_code_obj:
                            usage, u_created = ReferralUsage.objects.get_or_create(
                                referral_code=ref_code_obj,
                                referred_agent_id=agent.id,
                                defaults={'status': 'converted', 'signed_up_at': timezone.now()}
                            )
                            if not u_created and usage.status != 'converted':
                                usage.status = 'converted'
                                usage.save()

                            # Recalculate converted count
                            actual_conversions = ReferralUsage.objects.filter(
                                referral_code=ref_code_obj,
                                status='converted'
                            ).count()
                            ref_code_obj.total_referrals = actual_conversions
                            ref_code_obj.save()

                            if actual_conversions >= 5:
                                referring_agent = Agent.objects.filter(pk=ref_code_obj.agent_id).first()
                                if referring_agent and referring_agent.plan_type == 'free_trial':
                                    referring_agent.referral_reward_type = 'pro_plan_1rs'
                                    referring_agent.referral_reward_earned_at = timezone.now()
                                    referring_agent.save()
                    except Exception as ref_err:
                        logger.warning(f"Referral credit during free checkout failed: {ref_err}")

                try:
                    from apps.admin_panel.models.referral_code import ReferralCode
                    if not ReferralCode.objects.filter(agent=agent).exists():
                        ReferralCode.generateForAgent(agent)
                except Exception:
                    pass

                # Generate Invoice and send welcome credentials email with PDF attachment
                try:
                    import os
                    from apps.agents.services.invoice import invoice_service
                    from apps.agents.services.brevo import email_service
                    
                    invoice = invoice_service.generate_from_subscription(agent, subscription)
                    pdf_path = None
                    if invoice and invoice.pdf_path:
                        pdf_path = os.path.join(settings.MEDIA_ROOT, 'app', 'private', invoice.pdf_path)
                    
                    # Send welcome email with credentials and attached invoice
                    email_service.send_welcome(
                        to_email=agent.email,
                        to_name=agent.fullname,
                        temp_password=agent.email,
                        plan_name=subscription.selected_plan,
                        attachment_path=pdf_path
                    )
                except Exception as mail_err:
                    logger.error(f"Failed to generate invoice/send welcome email during instant checkout: {mail_err}")

                instant_complete = True
    except Exception as db_err:
        logger.error(f"Database transaction error in agent_register_complete: {db_err}")
        return JsonResponse({
            'success': False,
            'message': 'Database error occurred. Please try again.'
        }, status=500)

    if instant_complete:
        from apps.distributors.views.dashboard import is_distributor
        try:
            user = create_or_link_django_user(agent)
            login_agent_user(request, user)
        except Exception as login_err:
            logger.error(f"Instant checkout login failed for agent {getattr(agent, 'id', None)}: {login_err}")

        request.session.pop('current_draft_id', None)
        request.session.pop('reg_step', None)
        request.session.pop('ref_code', None)
        request.session.pop('pending_checkout', None)

        redirect_url = reverse('agents:agent_dashboard')
        if request.user.is_authenticated and is_distributor(request.user):
            redirect_url = reverse('distributors:agents_index')

        return JsonResponse({
            'success': True,
            'message': 'Registration completed successfully! Welcome to PadosiAgent.',
            'redirect_url': redirect_url,
        })

    request.session['pending_checkout'] = {
        'agent_id': agent.id,
        'order_id': razorpay_order_id,
        'plan_type': plan_type,
        'plan_name': plan_name,
    }
    request.session.modified = True

    return JsonResponse(checkout_payload(
        razorpay_order_id,
        amount_paise,
        agent,
        is_mock=mock_checkout,
    ))


@require_POST
@csrf_protect
def payment_success(request):
    """
    Handle successful payment webhook/callback.
    """
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        data = request.POST

    pending = request.session.get('pending_checkout') or {}
    razorpay_payment_id = data.get('razorpay_payment_id')
    razorpay_order_id = data.get('razorpay_order_id') or pending.get('order_id')
    razorpay_signature = data.get('razorpay_signature')
    agent_id = data.get('agent_id') or pending.get('agent_id')
    plan_name = data.get('plan_name') or pending.get('plan_name')
    plan_type = resolve_checkout_plan_slug(
        data.get('plan_type') or pending.get('plan_type'),
        plan_name,
    )

    from apps.agents.models import Agent, AgentSubscription, Invoice
    from apps.home.models import SiteSetting
    from apps.admin_panel.models.referral_code import ReferralCode
    from apps.admin_panel.models.referral_usage import ReferralUsage
    from apps.distributors.views.dashboard import is_distributor

    if razorpay_order_id:
        existing_sub = AgentSubscription.objects.filter(
            razorpay_order_id=razorpay_order_id,
            payment_status='completed'
        ).first()
        existing_invoice = Invoice.objects.filter(
            razorpay_order_id=razorpay_order_id,
            payment_status='paid',
        ).first()

        if existing_sub or existing_invoice:
            agent_obj = existing_sub.agent if existing_sub else existing_invoice.agent
            try:
                user = create_or_link_django_user(agent_obj)
                login_agent_user(request, user)
            except Exception as login_err:
                logger.error(f"Idempotent payment login failed: {login_err}")

            request.session.pop('current_draft_id', None)
            request.session.pop('reg_step', None)
            request.session.pop('ref_code', None)
            request.session.pop('pending_checkout', None)

            return JsonResponse({
                'success': True,
                'message': 'Payment already processed successfully.',
                'redirect_url': reverse('agents:agent_dashboard'),
            })

    mock_checkout = is_mock_payment(razorpay_order_id, razorpay_signature)
    if mock_checkout:
        subscription = AgentSubscription.objects.filter(razorpay_order_id=razorpay_order_id).first()
        if not subscription:
            logger.error(f"No subscription found matching mock Razorpay Order {razorpay_order_id}")
            return JsonResponse({'success': False, 'message': 'Invalid transaction ID.'}, status=400)
        if not razorpay_payment_id:
            razorpay_payment_id = mock_payment_id()
        if not razorpay_signature:
            razorpay_signature = MOCK_SIGNATURE
        logger.warning('DEBUG mock payment verify order=%s', razorpay_order_id)
    else:
        if not razorpay_signature:
            return JsonResponse({'success': False, 'message': 'Payment signature is missing. Cannot verify transaction.'}, status=400)

        try:
            client = razorpay_client()
            if client is None:
                return JsonResponse({'success': False, 'message': gateway_failure_message()}, status=400)

            client.utility.verify_payment_signature({
                'razorpay_order_id': razorpay_order_id,
                'razorpay_payment_id': razorpay_payment_id,
                'razorpay_signature': razorpay_signature
            })

            payment_info = client.payment.fetch(razorpay_payment_id)
            payment_status = payment_info.get('status')
            paid_amount_paise = payment_info.get('amount')

            if payment_status not in ('authorized', 'captured'):
                logger.error(f"Razorpay Payment {razorpay_payment_id} status is {payment_status} — rejecting activation.")
                return JsonResponse({'success': False, 'message': 'Payment is not completed.'}, status=400)

            subscription = AgentSubscription.objects.filter(razorpay_order_id=razorpay_order_id).first()
            if not subscription:
                logger.error(f"No subscription found matching Razorpay Order {razorpay_order_id}")
                return JsonResponse({'success': False, 'message': 'Invalid transaction ID.'}, status=400)

            expected_amount_paise = _expected_amount_paise(subscription.registration_amount)
            if not _paise_amounts_match(paid_amount_paise, expected_amount_paise):
                logger.critical(
                    f"POTENTIAL PRICE TAMPERING DETECTED! "
                    f"Agent ID: {agent_id}, Paid: {paid_amount_paise} paise, Expected: {expected_amount_paise} paise. "
                    f"Razorpay Payment ID: {razorpay_payment_id}"
                )
                return JsonResponse({'success': False, 'message': 'Payment validation failed: Amount mismatch.'}, status=400)

        except Exception as e:
            logger.error("Razorpay Signature/Amount Verification Failed: %s", e)
            return JsonResponse({'success': False, 'message': gateway_failure_message()}, status=400)

    from django.db import transaction

    try:
        with transaction.atomic():
            agent = Agent.objects.filter(pk=agent_id).first() if agent_id else None
            if not agent:
                agent = subscription.agent
            if not agent:
                return JsonResponse({'success': False, 'message': 'Agent record not found.'}, status=400)

            if not plan_type:
                plan_type = plan_slug_from_name(subscription.selected_plan or plan_name)

            # For custom plans created via Admin -> Plans: if plan_type is not a
            # known canonical slug, check if it directly matches a SubscriptionPlan slug.
            # This ensures agent.plan_type always matches the SiteSettings key.
            if plan_type:
                known_slugs = ('starter', 'professional', 'free_trial', 'exclusive', 'basic')
                if plan_type not in known_slugs:
                    try:
                        from apps.agents.models import SubscriptionPlan as _SPReg
                        sp = _SPReg.objects.filter(slug=plan_type).first()
                        if not sp:
                            sp = _SPReg.objects.filter(name__iexact=plan_type).first()
                        if sp and sp.slug:
                            plan_type = sp.slug
                    except Exception:
                        pass

            trial_config = SiteSetting.get_value('trial_plan_config', {'duration_days': 30})
            trial_days = int(trial_config.get('duration_days', 30))

            sub_expiry = timezone.now() + timezone.timedelta(days=365)
            if plan_type == 'free_trial':
                agent.status = 'active'
                agent.trial_ends_at = timezone.now() + timezone.timedelta(days=trial_days)
                upgrade_discount = SiteSetting.get_value('trial_upgrade_discount', 20)
                agent.upgrade_discount_percent = int(upgrade_discount)
                sub_expiry = timezone.now() + timezone.timedelta(days=trial_days)
            else:
                agent.status = 'pending_approval'

            if plan_type:
                agent.plan_type = plan_type
            agent.save()

            paid_sub = AgentSubscription.objects.filter(razorpay_order_id=razorpay_order_id).first()
            if not paid_sub and agent_id:
                paid_sub = AgentSubscription.objects.filter(agent_id=agent_id).first()
            if not paid_sub:
                paid_sub = subscription
            if not paid_sub:
                logger.error(f"No subscription found matching Razorpay Order {razorpay_order_id} or Agent ID {agent_id}")
                return JsonResponse({'success': False, 'message': 'No subscription record found.'}, status=400)

            paid_sub.payment_status = 'completed'
            paid_sub.status = 'active'
            paid_sub.razorpay_payment_id = razorpay_payment_id
            paid_sub.razorpay_signature = razorpay_signature
            paid_sub.starts_at = timezone.now()
            paid_sub.expires_at = sub_expiry
            paid_sub.save()
            subscription = paid_sub

            # Increment promo code usage (matching PHP payment_success)
            if subscription.promo_code:
                try:
                    promo = PromoCode.objects.filter(code=subscription.promo_code).first()
                    if promo:
                        promo.times_used += 1
                        promo.save(update_fields=['times_used'])
                except Exception:
                    pass

            # Handle referral credit
            if agent.referred_by_code:
                try:
                    ref_code_obj = ReferralCode.objects.filter(code=agent.referred_by_code).first()
                    if ref_code_obj:
                        usage, u_created = ReferralUsage.objects.get_or_create(
                            referral_code=ref_code_obj,
                            referred_agent_id=agent.id,
                            defaults={'status': 'converted', 'signed_up_at': timezone.now()}
                        )
                        if not u_created and usage.status != 'converted':
                            usage.status = 'converted'
                            usage.save()

                        actual_conversions = ReferralUsage.objects.filter(
                            referral_code=ref_code_obj,
                            status='converted'
                        ).count()
                        ref_code_obj.total_referrals = actual_conversions
                        ref_code_obj.save()

                        if actual_conversions >= 5:
                            referring_agent = Agent.objects.filter(pk=ref_code_obj.agent_id).first()
                            if referring_agent and referring_agent.plan_type == 'free_trial':
                                referring_agent.referral_reward_type = 'pro_plan_1rs'
                                referring_agent.referral_reward_earned_at = timezone.now()
                                referring_agent.save()
                except Exception as ref_err:
                    logger.warning(f"Referral credit during payment success failed: {ref_err}")

            try:
                if not ReferralCode.objects.filter(agent=agent).exists():
                    ReferralCode.generateForAgent(agent)
            except Exception:
                pass

            try:
                import os
                from apps.agents.services.invoice import invoice_service
                from apps.agents.services.brevo import email_service

                invoice = invoice_service.generate_from_subscription(agent, subscription)
                pdf_path = None
                if invoice and invoice.pdf_path:
                    pdf_path = os.path.join(settings.MEDIA_ROOT, 'app', 'private', invoice.pdf_path)

                email_service.send_welcome(
                    to_email=agent.email,
                    to_name=agent.fullname,
                    temp_password=agent.email,
                    plan_name=subscription.selected_plan,
                    attachment_path=pdf_path
                )
            except Exception as mail_err:
                logger.error(f"Failed to generate invoice/send welcome email during checkout completion: {mail_err}")

        try:
            user = create_or_link_django_user(agent)
            login_agent_user(request, user)
        except Exception as login_err:
            logger.error(f"Payment success login failed for agent {getattr(agent, 'id', None)}: {login_err}")

        request.session.pop('current_draft_id', None)
        request.session.pop('reg_step', None)
        request.session.pop('ref_code', None)
        request.session.pop('pending_checkout', None)

        redirect_url = reverse('agents:agent_dashboard')
        if request.user.is_authenticated and is_distributor(request.user):
            redirect_url = reverse('distributors:agents_index')

        return JsonResponse({
            'success': True,
            'message': 'Payment successful and account activated.',
            'redirect_url': redirect_url,
        })
    except Exception as e:
        logger.error(f"Error activating account in payment_success: {str(e)}")
        return JsonResponse({'success': False, 'message': 'Failed to activate agent account.'}, status=500)


@csrf_exempt
@require_http_methods(["GET", "POST"])
def payment_callback(request):
    """
    Razorpay redirect landing page for netbanking/UPI.
    Checkout handler often never runs after the bank redirect.
    """
    payload = _razorpay_callback_payload(request)
    logger.info(
        'Razorpay payment callback order=%s payment=%s has_signature=%s',
        payload.get('razorpay_order_id'),
        payload.get('razorpay_payment_id'),
        bool(payload.get('razorpay_signature')),
    )

    recovered_url = _recover_pending_razorpay_checkout(request, payload, retry=True)
    if recovered_url:
        return redirect(recovered_url)

    if payload.get('razorpay_signature') and payload.get('razorpay_payment_id') and payload.get('razorpay_order_id'):
        if not is_mock_payment(payload.get('razorpay_order_id'), payload.get('razorpay_signature')):
            try:
                client = razorpay_client()
                if client is None:
                    logger.error('Razorpay callback skipped: keys missing')
                    return redirect(f"{reverse('agents:agent_register_failed')}?reason=gateway")
                client.utility.verify_payment_signature({
                    'razorpay_order_id': payload['razorpay_order_id'],
                    'razorpay_payment_id': payload['razorpay_payment_id'],
                    'razorpay_signature': payload['razorpay_signature'],
                })
            except Exception as sig_err:
                logger.error('Razorpay callback signature failed: %s', sig_err)
                return redirect('agents:chooseplan')
        recovered_url = _recover_pending_razorpay_checkout(request, payload, retry=True)
        if recovered_url:
            return redirect(recovered_url)

    logger.warning('Razorpay callback could not complete order=%s', payload.get('razorpay_order_id'))
    return redirect('agents:chooseplan')


@require_POST
@csrf_protect
def agent_verify_promo(request):
    """
    Verify promo code.
    Mirrors Laravel's AgentRegistrationController::verifyPromo.
    """
    try:
        data = json.loads(request.body)
        promo_code = data.get('promo_code', '').strip().upper()
    except (json.JSONDecodeError, AttributeError):
        promo_code = request.POST.get('promo_code', '').strip().upper()

    if not promo_code:
        return JsonResponse({'success': False, 'message': 'Promo code is required.'})

    try:
        promo = PromoCode.objects.get(code=promo_code)
        if promo.is_valid():
            request.session['applied_promo_code'] = promo.code
            return JsonResponse({
                'success': True,
                'message': f'Promo code "{promo.code}" is valid and will be applied at checkout!',
            })
        else:
            return JsonResponse({
                'success': False,
                'message': 'Promo code has expired or is invalid.',
            })
    except PromoCode.DoesNotExist:
        pass
    except Exception:
        pass

    return JsonResponse({
        'success': False,
        'message': 'Invalid or expired promo code.',
    })


def referral_join(request, ref_code):
    """
    Referral link landing - captures ref code in session, increments clicks, and redirects to registration.
    Ported from Laravel route /join/{refCode}.
    """
    from apps.admin_panel.models.referral_code import ReferralCode
    code_val = str(ref_code).strip().upper()
    code = ReferralCode.objects.filter(code=code_val, is_active=True).first()
    if code:
        code.clicks = (code.clicks or 0) + 1
        code.save()
        request.session['ref_code'] = code.code
    
    # Redirect to registration page with query params
    url = reverse('agents:agent_registration') + f"?ref={code_val}&show_trial=1"
    return redirect(url)


@require_POST
@csrf_exempt
def client_quick_register(request):
    """
    Client quick registration view. Replicates Laravel's ClientRegistrationController.quickRegister().
    Validates input, logins existing client, or creates a new client and user account.
    """
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, AttributeError):
        data = request.POST

    fullname = (data.get('fullname') or '').strip()
    email = (data.get('email') or '').strip().lower()
    mobile = (data.get('mobile') or '').strip()
    pincode = (data.get('pincode') or '').strip() or None

    # Validation
    errors = {}
    if not fullname:
        errors['fullname'] = ['Full name is required.']
    elif len(fullname) < 2 or len(fullname) > 100:
        errors['fullname'] = ['Name must be between 2 and 100 characters.']
    elif not re.match(r'^[\w\s.\-\']+$', fullname):
        errors['fullname'] = ['Name may only contain letters, spaces, dots, hyphens or apostrophes.']

    if not email:
        errors['email'] = ['Email is required.']
    elif '@' not in email:
        errors['email'] = ['Please enter a valid email address.']

    if not mobile:
        errors['mobile'] = ['Mobile number is required.']
    elif len(mobile) != 10 or not mobile.isdigit():
        errors['mobile'] = ['Mobile number must be exactly 10 digits.']
    elif not re.match(r'^[6-9][0-9]{9}$', mobile):
        errors['mobile'] = ['Please enter a valid Indian mobile number (starts with 6-9).']

    if pincode and (len(pincode) != 6 or not pincode.isdigit()):
        errors['pincode'] = ['Pincode must be exactly 6 digits.']

    if errors:
        return JsonResponse({
            'success': False,
            'message': 'Please fix the validation errors below.',
            'errors': errors
        }, status=422)

    from django.contrib.auth.models import User
    from apps.agents.models import Client
    
    existing_user = User.objects.filter(email=email).first()
    
    if existing_user:
        # Check if they are a client
        is_client = Client.objects.filter(user=existing_user).exists()
        if not is_client:
            Client.objects.create(
                user=existing_user,
                mobile=mobile,
                pincode=pincode
            )
            
        request.session['quick_lead_user'] = {
            'fullname': fullname,
            'email': email,
            'mobile': mobile,
            'pincode': pincode,
        }
        from django.contrib.auth import login
        from apps.distributors.views.dashboard import is_distributor
        if not (request.user.is_authenticated and is_distributor(request.user)):
            login(request, existing_user)
        
        return JsonResponse({
            'success': True,
            'status': 'success',
            'message': 'Welcome back! Redirecting...',
            'redirect': data.get('redirect_url') or '/find-agents/'
        })

    # Create new client account
    from django.db import transaction
    try:
        with transaction.atomic():
            # Create standard User
            username = email.split('@')[0]
            counter = 1
            base_username = username
            while User.objects.filter(username=username).exists():
                username = f"{base_username}{counter}"
                counter += 1

            user = User.objects.create_user(
                username=username,
                email=email,
                password=email,
                first_name=fullname.split(' ')[0],
                last_name=' '.join(fullname.split(' ')[1:])
            )

            # Create Client record
            Client.objects.create(
                user=user,
                mobile=mobile,
                pincode=pincode
            )

        # Log user in
        from django.contrib.auth import login
        from apps.distributors.views.dashboard import is_distributor
        if not (request.user.is_authenticated and is_distributor(request.user)):
            login(request, user)

        request.session['quick_lead_user'] = {
            'fullname': fullname,
            'email': email,
            'mobile': mobile,
            'pincode': pincode,
        }

        return JsonResponse({
            'success': True,
            'status': 'success',
            'message': 'Registration successful! Redirecting...',
            'redirect': data.get('redirect_url') or '/find-agents/'
        })

    except Exception as e:
        logger.error(f"Client quick registration failed: {e}")
        return JsonResponse({
            'success': False,
            'status': 'error',
            'message': 'Unable to complete registration right now. Please try again.'
        }, status=500)


@require_POST
@csrf_protect
def payment_failure(request):
    """
    Handle failed payment notification.
    """
    try:
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            data = request.POST

        agent_id = data.get('agent_id')
        order_id = data.get('razorpay_order_id')
        from apps.agents.models import Agent, AgentSubscription

        agent = Agent.objects.filter(pk=agent_id).first() if agent_id else None
        subscription = None
        if order_id:
            subscription = AgentSubscription.objects.filter(razorpay_order_id=order_id).first()
            if subscription and not agent:
                agent = subscription.agent
        if not subscription and agent:
            subscription = AgentSubscription.objects.filter(
                agent=agent,
                payment_status='pending'
            ).order_by('-created_at').first()

        if subscription:
            # Netbanking/UPI often fire a client "failed" event while the bank
            # payment is still in progress. Never mark failed in that case.
            error = data.get('error') if isinstance(data.get('error'), dict) else {}
            if _is_in_progress_razorpay_error(error):
                logger.info(
                    'Ignoring in-progress Razorpay failure for order %s step=%s',
                    order_id, error.get('step'),
                )
                return JsonResponse({
                    'success': True,
                    'ignored': True,
                    'message': 'Payment still in progress.',
                })

            agent = agent or subscription.agent
            if agent and verify_and_activate_pending_payment(agent):
                return JsonResponse({
                    'success': True,
                    'already_completed': True,
                    'message': 'Payment already captured.',
                    'redirect_url': reverse('agents:agent_dashboard'),
                })

            if subscription.payment_status != 'completed':
                logger.info(
                    'Razorpay client failure logged for order %s; leaving subscription pending',
                    order_id or subscription.razorpay_order_id,
                )

        if agent and agent.status not in ('active', 'pending_approval'):
            agent.status = 'pending_payment'
            agent.save(update_fields=['status'])
        return JsonResponse({
            'success': True,
            'message': 'Payment failure logged.',
            'redirect_url': f"{reverse('agents:agent_register_failed')}?agent_id={agent.id if agent else ''}"
        })
    except Exception as e:
        logger.error(f"PAYMENT FAILURE LOG ERR: {e}")
        return JsonResponse({'success': False}, status=500)


from django.views.decorators.csrf import csrf_exempt

@csrf_exempt
@require_POST
def razorpay_webhook(request):
    """
    Asynchronous webhook handler to process Razorpay payment events.
    Verifies signature and activates the agent subscription.
    """
    payload = request.body
    received_signature = request.META.get('HTTP_X_RAZORPAY_SIGNATURE') or request.headers.get('X-Razorpay-Signature')
    webhook_secret = getattr(settings, 'RAZORPAY_WEBHOOK_SECRET', '')

    if not webhook_secret:
        logger.error("[Razorpay Webhook] RAZORPAY_WEBHOOK_SECRET is not configured.")
        return HttpResponse('Webhook secret not configured', status=400)

    # Verify signature
    if received_signature == 'test_signature_skip_verification' and settings.DEBUG:
        logger.info("[Razorpay Webhook] Skipping signature verification for local test simulation.")
    else:
        try:
            client = razorpay_client()
            if client is None:
                logger.error("[Razorpay Webhook] Razorpay keys not configured.")
                return HttpResponse('Unable to process webhook.', status=400)
            # verify_webhook_signature takes payload string, signature, secret
            client.utility.verify_webhook_signature(
                payload.decode('utf-8') if isinstance(payload, bytes) else payload,
                received_signature,
                webhook_secret
            )
        except Exception as sig_err:
            logger.error(f"[Razorpay Webhook] Signature verification failed: {sig_err}")
            return HttpResponse('Invalid signature', status=400)

    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return HttpResponse('Invalid JSON payload', status=400)

    event = data.get('event')
    if not event:
        return HttpResponse('Invalid event', status=400)

    if event == 'payment.captured':
        payment = data['payload']['payment']['entity']
        order_id = payment.get('order_id')
        payment_id = payment.get('id')
        signature = received_signature

        from apps.agents.models import Agent, AgentSubscription, PromoCode, Invoice
        from apps.home.models import SiteSetting
        from django.utils import timezone

        subscription = AgentSubscription.objects.filter(razorpay_order_id=order_id).first()
        existing_invoice = Invoice.objects.filter(razorpay_order_id=order_id).first()
        
        if (subscription and subscription.payment_status == 'completed') or existing_invoice:
            return HttpResponse('Webhook processed successfully (already completed)', status=200)

        if subscription:
            agent = subscription.agent
            
            # Avoid duplicate activation
            if subscription.payment_status == 'completed':
                return HttpResponse('Webhook processed successfully (already completed)', status=200)

            # Verify amount paid matches subscription amount to prevent tampering
            paid_amount_paise = payment.get('amount')
            expected_amount_paise = _expected_amount_paise(subscription.registration_amount)
            if not _paise_amounts_match(paid_amount_paise, expected_amount_paise):
                logger.critical(
                    f"[Webhook] PRICE TAMPERING DETECTED! "
                    f"Order: {order_id}, Paid: {paid_amount_paise} paise, Expected: {expected_amount_paise} paise."
                )
                return HttpResponse('Payment validation failed: Amount mismatch.', status=400)

            from django.db import transaction
            try:
                with transaction.atomic():
                    plan_type = plan_slug_from_name(subscription.selected_plan) or 'professional'
                    is_trial = plan_type == 'free_trial'

                    trial_config = SiteSetting.get_value('trial_plan_config', {'duration_days': 30})
                    trial_days = int(trial_config.get('duration_days', 30))
                    sub_expiry = timezone.now() + timezone.timedelta(days=365)
                    if is_trial:
                        sub_expiry = timezone.now() + timezone.timedelta(days=trial_days)

                    # Update subscription status
                    subscription.payment_status = 'completed'
                    subscription.status = 'active'
                    subscription.razorpay_payment_id = payment_id
                    subscription.razorpay_signature = signature
                    subscription.starts_at = timezone.now()
                    subscription.expires_at = sub_expiry
                    subscription.save()

                    # Update Agent status
                    agent.registration_step = 2
                    if is_trial:
                        agent.status = 'active'
                        agent.plan_type = 'free_trial'
                        agent.trial_ends_at = timezone.now() + timezone.timedelta(days=trial_days)
                        upgrade_discount = SiteSetting.get_value('trial_upgrade_discount', 20)
                        agent.upgrade_discount_percent = int(upgrade_discount)
                    else:
                        agent.status = 'pending_approval'
                        agent.plan_type = plan_type
                    agent.save()

                    # Process referral conversion credits
                    if agent.referred_by_code:
                        try:
                            from apps.admin_panel.models.referral_code import ReferralCode
                            from apps.admin_panel.models.referral_usage import ReferralUsage
                            
                            ref_code_obj = ReferralCode.objects.filter(code=agent.referred_by_code).first()
                            if ref_code_obj:
                                usage, u_created = ReferralUsage.objects.get_or_create(
                                    referral_code=ref_code_obj,
                                    referred_agent_id=agent.id,
                                    defaults={'status': 'converted', 'signed_up_at': timezone.now()}
                                )
                                if not u_created and usage.status != 'converted':
                                    usage.status = 'converted'
                                    usage.save()

                                # Recalculate conversions
                                actual_conversions = ReferralUsage.objects.filter(
                                    referral_code=ref_code_obj,
                                    status='converted'
                                ).count()
                                ref_code_obj.total_referrals = actual_conversions
                                ref_code_obj.save()

                                if actual_conversions >= 5:
                                    referring_agent = Agent.objects.filter(pk=ref_code_obj.agent_id).first()
                                    if referring_agent and referring_agent.plan_type == 'free_trial':
                                        referring_agent.referral_reward_type = 'pro_plan_1rs'
                                        referring_agent.referral_reward_earned_at = timezone.now()
                                        referring_agent.save()
                        except Exception as ref_err:
                            logger.warning(f"[Webhook] Referral credit processing failed: {ref_err}")

                    # Auto-generate referral code for agent
                    try:
                        from apps.admin_panel.models.referral_code import ReferralCode
                        if not ReferralCode.objects.filter(agent=agent).exists():
                            ReferralCode.generateForAgent(agent)
                    except Exception:
                        pass

                    # Increment used count of Promo Code
                    if subscription.promo_code:
                        try:
                            promo = PromoCode.objects.filter(code=subscription.promo_code).first()
                            if promo:
                                promo.times_used += 1
                                promo.save(update_fields=['times_used'])
                        except Exception:
                            pass

                    # Link django user
                    user = create_or_link_django_user(agent)

                    # Generate Invoice and send welcome credentials email with PDF attachment
                    try:
                        import os
                        from apps.agents.services.invoice import invoice_service
                        from apps.agents.services.brevo import email_service
                        
                        invoice = invoice_service.generate_from_subscription(agent, subscription)
                        pdf_path = None
                        if invoice and invoice.pdf_path:
                            pdf_path = os.path.join(settings.MEDIA_ROOT, 'app', 'private', invoice.pdf_path)
                        
                        # Send welcome email with credentials and attached invoice
                        email_service.send_welcome(
                            to_email=agent.email,
                            to_name=agent.fullname,
                            temp_password=agent.email,
                            plan_name=subscription.selected_plan,
                            attachment_path=pdf_path
                        )
                    except Exception as mail_err:
                        logger.error(f"[Webhook] Failed to generate invoice or send welcome email: {mail_err}")

            except Exception as db_err:
                logger.error(f"[Webhook] Database transaction failed: {db_err}")
                return HttpResponse('Database transaction failed', status=500)

    return HttpResponse('Webhook processed successfully', status=200)


from django.contrib.auth.decorators import login_required

def agent_register_failed(request):
    """
    Render payment failed page.
    """
    from apps.agents.models import Agent
    agent_id = request.session.get('current_agent_id') or request.GET.get('agent_id')
    agent = Agent.objects.filter(id=agent_id).first() if agent_id else None
    
    return render(request, 'agents/failed.html', {'agent': agent})


def fb_ad_signup(request):
    """
    Dedicated landing page and signup flow for Facebook Ads.
    Mirrors client_quick_register but fixes the password=email security issue,
    adds a transaction guard for concurrent email signups, and blocks agent accounts.
    """
    if request.method == 'GET':
        return render(request, 'public/fb_ad_signup.html')
        
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, AttributeError):
        data = request.POST

    fullname = (data.get('fullname') or '').strip()
    email = (data.get('email') or '').strip().lower()
    mobile = (data.get('mobile') or '').strip()
    pincode = (data.get('pincode') or '').strip()

    # --- Validation ---
    errors = {}
    if not fullname:
        errors['fullname'] = ['Full name is required.']
    elif len(fullname) < 2 or len(fullname) > 100:
        errors['fullname'] = ['Name must be between 2 and 100 characters.']
    elif not re.match(r'^[\w\s.\-\']+$', fullname):
        errors['fullname'] = ['Name may only contain letters, spaces, dots, hyphens or apostrophes.']

    if not email:
        errors['email'] = ['Email is required.']
    elif '@' not in email:
        errors['email'] = ['Please enter a valid email address.']

    if not mobile:
        errors['mobile'] = ['Mobile number is required.']
    elif len(mobile) != 10 or not mobile.isdigit():
        errors['mobile'] = ['Mobile number must be exactly 10 digits.']
    elif not re.match(r'^[6-9][0-9]{9}$', mobile):
        errors['mobile'] = ['Please enter a valid Indian mobile number.']

    if not pincode:
        errors['pincode'] = ['Pincode is required.']
    elif len(pincode) != 6 or not pincode.isdigit():
        errors['pincode'] = ['Pincode must be exactly 6 digits.']

    if errors:
        return JsonResponse({
            'success': False,
            'message': 'Please fix the validation errors below.',
            'errors': errors
        }, status=422)

    from django.contrib.auth.models import User
    from apps.agents.models import Client, Agent
    from django.contrib.auth import login
    from django.db import transaction
    
    try:
        with transaction.atomic():
            # Guard against duplicates via select_for_update if existing, else create carefully
            existing_user = User.objects.select_for_update().filter(email=email).first()
            
            if existing_user:
                # Security Check: Prevent Agents from using this consumer flow
                if Agent.objects.filter(user=existing_user).exists():
                    return JsonResponse({
                        'success': False,
                        'status': 'error',
                        'message': 'This email is already registered as an agent — please use the agent login page.'
                    }, status=403)

                is_client = Client.objects.filter(user=existing_user).exists()
                if not is_client:
                    Client.objects.create(
                        user=existing_user,
                        mobile=mobile,
                        pincode=pincode
                    )
                user_to_login = existing_user
                message = 'Welcome back! Redirecting...'
            else:
                username = email.split('@')[0]
                counter = 1
                base_username = username
                while User.objects.filter(username=username).exists():
                    username = f"{base_username}{counter}"
                    counter += 1

                user_to_login = User.objects.create_user(
                    username=username,
                    email=email,
                    first_name=fullname.split(' ')[0],
                    last_name=' '.join(fullname.split(' ')[1:])
                )
                
                # MODIFICATION 1: Avoid setting password to email for security
                user_to_login.set_unusable_password()
                user_to_login.save()

                Client.objects.create(
                    user=user_to_login,
                    mobile=mobile,
                    pincode=pincode
                )
                message = 'Registration successful! Redirecting...'

    except Exception as e:
        logger.error(f"FB Ad quick registration failed: {e}")
        return JsonResponse({
            'success': False,
            'status': 'error',
            'message': 'Unable to complete registration right now. Please try again.'
        }, status=500)

    # Set session for agent_capture_lead compatibility
    request.session['quick_lead_user'] = {
        'fullname': fullname,
        'email': email,
        'mobile': mobile,
        'pincode': pincode,
    }
    
    login(request, user_to_login)
    
    return JsonResponse({
        'success': True,
        'status': 'success',
        'message': message,
        'redirect': f'/find-agents/?pincode={pincode}'
    })

