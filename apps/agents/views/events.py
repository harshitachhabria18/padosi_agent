"""
Public Event Registration Funnel — port of
App\\Http\\Controllers\\User\\EventRegistrationController (Laravel).

Flow:
  GET  /events/register/        → registration form
  POST /events/register/        → saves Agent + EventRegistration (step 1)
  GET  /events/plans/           → choose plan (step 2)
  POST /events/plans/           → select plan, persist subscription draft
  GET  /events/payment/         → Razorpay checkout (step 3)
  POST /events/payment/success/ → verify signature + amount, complete registration
  POST /events/payment/failure/ → mark failed
  GET  /events/success/         → success page (auto-login after payment)
  POST /events/verify-promo/    → AJAX promo verification for Professional's Plan
"""

import logging
import random
import string
import time

from django.contrib import messages
from django.contrib.auth import login
from django.core.cache import cache
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

from apps.agents.models import (
    Agent, AgentInsuranceSegment, AgentProfile, AgentSubscription,
    PromoCode, Event, EventRegistration,
)
from apps.agents.views.registration import create_or_link_django_user
from apps.agents.services.feature_unlock import PLAN_LABELS
from padosi_agent.razorpay_env import USER_PAYMENT_UNAVAILABLE

logger = logging.getLogger(__name__)

# ─── Pricing (matches Laravel getPricing) ────────────────────────────────────
PROFESSIONAL_BASE = 9999.00
BASIC_BASE = 1999.00
GST_RATE = 0.18

PLAN_NAMES = {'professional': PLAN_LABELS['professional'], 'basic': PLAN_LABELS['starter']}


def get_pricing(promo_code_str=None):
    prof_base = PROFESSIONAL_BASE
    if promo_code_str:
        try:
            promo = PromoCode.objects.filter(code=promo_code_str).first()
            if promo and promo.is_valid():
                prof_base = max(0, prof_base - promo.calculate_discount(prof_base))
        except Exception:
            pass
    prof_gst = round(prof_base * GST_RATE, 2)
    prof_total = round(prof_base + prof_gst, 2)
    basic_gst = round(BASIC_BASE * GST_RATE, 2)
    basic_total = round(BASIC_BASE + basic_gst, 2)
    return {
        'professional': {'name': PLAN_NAMES['professional'], 'base': prof_base, 'gst': prof_gst, 'total': prof_total},
        'basic': {'name': PLAN_NAMES['basic'], 'base': BASIC_BASE, 'gst': basic_gst, 'total': basic_total},
    }


def _session_flow_ids(request):
    return (
        request.session.get('current_agent_id'),
        request.session.get('current_event_registration_id'),
    )


def _clear_flow_session(request):
    for key in ('current_agent_id', 'current_event_registration_id'):
        request.session.pop(key, None)


def _password_cache_key(email):
    import hashlib
    return 'event_reg_pw_' + hashlib.md5(email.encode('utf-8')).hexdigest()


def _verify_razorpay_signature(order_id, payment_id, signature):
    import hashlib
    import hmac as hmac_module
    from django.conf import settings

    if not signature:
        return False
    secret = settings.RAZORPAY_SECRET
    if not secret:
        return False
    expected = hmac_module.new(
        secret.encode('utf-8'),
        f"{order_id}|{payment_id}".encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()
    return hmac_module.compare_digest(expected, signature)


def _get_first_event():
    return Event.objects.order_by('event_date').first()


def _get_or_create_agent(event_id, **agent_data):
    agent = Agent.objects.filter(email=agent_data['email']).first()
    if agent:
        for key, value in agent_data.items():
            setattr(agent, key, value)
        agent.save()
    else:
        agent = Agent.objects.create(**agent_data)
    return agent


# ─── Step 1: Form ────────────────────────────────────────────────────────────

def show_form(request):
    if request.user.is_authenticated:
        # Agents should not re-register
        try:
            if request.user.agent_set.exists() or Agent.objects.filter(user=request.user).exists():
                return redirect('agents:agent_dashboard')
        except Exception:
            pass

    verified_email = request.session.get('verified_email', '')
    is_verified = bool(request.session.get('email_verified') and verified_email)
    agent_id = request.session.get('current_agent_id')
    if not is_verified and agent_id:
        try:
            agent = Agent.objects.get(pk=agent_id)
            if agent.email_verified_at:
                is_verified = True
                verified_email = agent.email
        except Agent.DoesNotExist:
            pass

    return render(request, 'events/register.html', {
        'is_verified': is_verified,
        'verified_email': verified_email,
        'request': request,
        'pincode': (request.GET.get('pincode') or '').strip(),
    })


@require_POST
@csrf_protect
def register(request):
    if request.user.is_authenticated:
        try:
            if Agent.objects.filter(user=request.user).exists():
                messages.info(request, 'You already have an agent account. No re-registration needed.')
                return redirect('agents:agent_dashboard')
        except Exception:
            pass

    fullname = (request.POST.get('fullname') or '').strip()
    email = (request.POST.get('email') or '').strip().lower()
    mobile = (request.POST.get('mobile') or '').strip()
    segments = request.POST.getlist('insurance_segments') or request.POST.getlist('insurance_segments[]')
    pincode = (request.POST.get('pincode') or '').strip()
    experience = (request.POST.get('experience') or '').strip()
    promocode = (request.POST.get('promocode') or '').strip().upper()

    import re as _re
    if not fullname or not email or not mobile:
        messages.error(request, 'Please fill in all required fields.')
        return redirect('events:register.form')
    if not _re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
        messages.error(request, 'Please enter a valid email address.')
        return redirect('events:register.form')
    if not segments or len(segments) > 4:
        messages.error(request, 'Please select at least one insurance segment (max 4).')
        return redirect('events:register.form')
    if pincode and not _re.match(r'^[1-9]\d{5}$', pincode):
        messages.error(request, 'Please enter a valid 6-digit pincode.')
        return redirect('events:register.form')

    clean_mobile = _re.sub(r'[^0-9]', '', mobile)
    if len(clean_mobile) == 12 and clean_mobile.startswith('91'):
        clean_mobile = clean_mobile[2:]
    if len(clean_mobile) == 11 and clean_mobile.startswith('0'):
        clean_mobile = clean_mobile[1:]
    clean_mobile = clean_mobile[-10:]
    if not _re.match(r'^[6-9]\d{9}$', clean_mobile):
        messages.error(request, 'Please enter a valid 10-digit Indian mobile number.')
        return redirect('events:register.form')

    event = _get_first_event()
    if not event:
        messages.error(request, 'No event is currently available for registration.')
        return redirect('events:register.form')

    if Agent.objects.filter(email=email, status__in=['active', 'pending_approval', 'pending_payment', 'pending']).exists():
        messages.error(request, 'This email is already associated with an active Agent account. Please login to access your dashboard.')
        return redirect('events:register.form')

    existing_agent = Agent.objects.filter(email=email).first()
    email_verified_at = existing_agent.email_verified_at if (existing_agent and existing_agent.email_verified_at) else timezone.now()

    agent = _get_or_create_agent(
        event.id,
        event_id=event.id,
        fullname=fullname,
        email=email,
        mobile=clean_mobile,
        agent_pincode=pincode,
        experience_range=experience,
        referred_by_code=promocode,
        registration_step=1,
        status='incomplete',
        email_verified_at=email_verified_at,
    )

    profile, _created = AgentProfile.objects.get_or_create(
        agent=agent,
        defaults={'address': f'Pincode: {pincode}' if pincode else ''},
    )
    if pincode and not profile.address:
        profile.address = f'Pincode: {pincode}'
        profile.save()

    agent.insuranceSegments.all().delete()
    for segment in segments:
        AgentInsuranceSegment.objects.create(agent=agent, segment_type=_segment_label(segment))

    event_registration = EventRegistration.objects.filter(email=email).order_by('-created_at').first()
    registration_data = {
        'event_id': event.id,
        'fullname': fullname,
        'email': email,
        'mobile': clean_mobile,
        'insurance_segments': [seg for seg in segments],
        'pincode': pincode or None,
        'experience': experience or None,
        'promocode': promocode or None,
        'current_step': 1,
        'status': 'incomplete',
        'payment_status': 'pending',
        'selected_plan': None,
    }
    if event_registration:
        for key, value in registration_data.items():
            setattr(event_registration, key, value)
        event_registration.save()
    else:
        event_registration = EventRegistration.objects.create(**registration_data)

    request.session['current_agent_id'] = agent.id
    request.session['current_event_registration_id'] = event_registration.id
    request.session.pop('email_verified', None)
    request.session.pop('verified_email', None)

    return redirect('events:plans')


def _segment_label(value):
    label_map = {'health': 'Health', 'life': 'Life', 'motor': 'Motor', 'sme': 'SME'}
    return label_map.get(str(value).lower(), str(value).title())


# ─── Step 2: Plans ───────────────────────────────────────────────────────────

def show_plans(request):
    agent_id, event_reg_id = _session_flow_ids(request)
    if not agent_id and not event_reg_id:
        messages.error(request, 'Please fill in the registration details first.')
        return redirect('events:register.form')

    event_registration = EventRegistration.objects.filter(pk=event_reg_id).first() if event_reg_id else None
    if agent_id and not event_registration:
        _clear_flow_session(request)
        messages.error(request, 'Your session expired or your registration was cancelled.')
        return redirect('events:register.form')

    if event_registration and event_registration.status == 'completed':
        messages.success(request, 'Registration already completed.')
        return redirect('events:register.form')

    promo_code_str = event_registration.promocode if event_registration else None
    pricing = get_pricing(promo_code_str)

    event_registration = _ensure_event_registration(event_registration, agent_id)

    return _render_plans(request, event_registration, pricing, promo_code_str)


def _ensure_event_registration(event_registration, agent_id):
    if event_registration:
        return event_registration
    if agent_id:
        try:
            agent = Agent.objects.get(pk=agent_id)
        except Agent.DoesNotExist:
            return None
        event = agent.event_id and Event.objects.filter(pk=agent.event_id).first() or _get_first_event()
        if event:
            event_registration, _ = EventRegistration.objects.get_or_create(
                email=agent.email,
                defaults={
                    'event_id': event.id,
                    'fullname': agent.fullname,
                    'email': agent.email,
                    'mobile': agent.mobile,
                    'insurance_segments': [s.segment_type for s in agent.insuranceSegments.all()],
                    'pincode': agent.agent_pincode or None,
                    'experience': agent.experience_range or None,
                    'promocode': agent.referred_by_code or None,
                    'current_step': 1,
                },
            )
            return event_registration
    return None


def _render_plans(request, event_registration, pricing, promo_code_str):
    selected_plan = None
    razorpay_order_id = None
    key = None

    selected_plan_key = event_registration.selected_plan if event_registration else None
    if selected_plan_key and selected_plan_key in pricing:
        selected_plan = {**pricing[selected_plan_key], 'total_cents': int(round(pricing[selected_plan_key]['total'] * 100))}

        if event_registration and event_registration.razorpay_order_id:
            razorpay_order_id = event_registration.razorpay_order_id
            key = _razorpay_key()
        else:
            key = _razorpay_key()
            razorpay_order_id = _create_razorpay_order(
                receipt=f'evt_{event_registration.id}_{int(time.time())}',
                amount_paise=round(selected_plan['total'] * 100),
                event_registration=event_registration,
            )

        agent_id = _session_flow_ids(request)[0]
        if agent_id and event_registration:
            try:
                agent = Agent.objects.get(pk=agent_id)
                agent.registration_step = 2
                agent.status = 'pending_payment'
                agent.save()
                subscription = AgentSubscription.objects.filter(agent=agent).order_by('-created_at').first()
                if subscription:
                    subscription.razorpay_order_id = razorpay_order_id
                    subscription.save()
            except Agent.DoesNotExist:
                pass

    from apps.home.models import SiteSetting
    from apps.agents.views.registration import _exclusive_base_price

    # Fetch Gamification Config
    exclusive_config = SiteSetting.get_value('exclusive_plan_config') or {}
    is_exclusive_active = exclusive_config.get('is_active', False)
    draft_id = event_registration.id if event_registration else 'event'
    session_key = f'followed_platforms_{draft_id}'
    followed = request.session.get(session_key, [])
    follow_count = len(followed)
    discount_unlocked = follow_count > 0

    exc_strikeout = float(exclusive_config.get('strikeout_price', 9999))
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

    return render(request, 'events/plans.html', {
        'event_registration': event_registration,
        'draft': event_registration,
        'pricing': pricing,
        'selected_plan': selected_plan,
        'selected_plan_key': selected_plan_key,
        'razorpay_order_id': razorpay_order_id,
        'razorpay_key': key,
        'promo_code': promo_code_str or '',
        'promo_discount_amount': round(PROFESSIONAL_BASE - pricing['professional']['base'], 2),
        'base_minus_6999': round(PROFESSIONAL_BASE - pricing['professional']['base'], 2),  # kept for backward compat
        'base_minus_9999': round(PROFESSIONAL_BASE - pricing['professional']['base'], 2),
        'selected_professional': selected_plan_key == 'professional',
        'selected_basic': selected_plan_key == 'basic',

        'exclusive_config': exclusive_config,
        'is_exclusive_active': is_exclusive_active,
        'discount_unlocked': discount_unlocked,
        'premiumFeatures': premium_features,
        'spots_left': spots_left,
        'urgency_line_1': urgency_line_1,
        'urgency_line_2': urgency_line_2,
    })


@require_POST
@csrf_protect
def select_plan(request):
    plan_type = request.POST.get('plan_type')
    if plan_type not in ('professional', 'basic'):
        messages.error(request, 'Invalid plan selected.')
        return redirect('events:plans')

    agent_id, event_reg_id = _session_flow_ids(request)
    if not agent_id and not event_reg_id:
        messages.error(request, 'Session expired. Please fill in your details again.')
        return redirect('events:register.form')

    promo_code_str = None
    if event_reg_id:
        event_reg = EventRegistration.objects.filter(pk=event_reg_id).first()
        if event_reg:
            promo_code_str = event_reg.promocode

    pricing = get_pricing(promo_code_str)
    selected_plan = pricing[plan_type]

    if event_reg_id:
        EventRegistration.objects.filter(pk=event_reg_id).update(
            selected_plan=plan_type,
            current_step=2,
            razorpay_order_id=None,
        )

    if agent_id:
        try:
            agent = Agent.objects.get(pk=agent_id)
            agent.registration_step = 2
            agent.plan_type = plan_type
            agent.save()

            subscription = AgentSubscription.objects.filter(agent=agent).order_by('-created_at').first()
            if subscription:
                subscription.selected_plan = selected_plan['name']
                subscription.registration_amount = selected_plan['total']
                subscription.payment_status = 'pending'
                subscription.status = 'inactive'
                subscription.promo_code = promo_code_str or None
                subscription.save()
            else:
                AgentSubscription.objects.create(
                    agent=agent,
                    selected_plan=selected_plan['name'],
                    registration_amount=selected_plan['total'],
                    payment_status='pending',
                    status='inactive',
                    promo_code=promo_code_str or None,
                )
        except Agent.DoesNotExist:
            pass

    return redirect('events:plans')


# ─── Step 3: Payment ─────────────────────────────────────────────────────────

def show_payment(request):
    agent_id, event_reg_id = _session_flow_ids(request)
    if not agent_id and not event_reg_id:
        messages.error(request, 'Session expired. Please fill in your details again.')
        return redirect('events:register.form')

    event_registration = EventRegistration.objects.filter(pk=event_reg_id).first() if event_reg_id else None
    if not event_registration:
        _clear_flow_session(request)
        messages.error(request, 'Your session expired or your registration was cancelled.')
        return redirect('events:register.form')

    if not event_registration.selected_plan:
        messages.error(request, 'Please choose a plan first.')
        return redirect('events:plans')

    pricing = get_pricing(event_registration.promocode)
    plan_key = event_registration.selected_plan
    selected_plan = pricing.get(plan_key, pricing['professional'])

    key = _razorpay_key()
    secret = _razorpay_secret()
    razorpay_order_id = event_registration.razorpay_order_id

    if not razorpay_order_id:
        if not key or not secret or key.startswith('your_'):
            messages.error(request, USER_PAYMENT_UNAVAILABLE)
            return redirect('events:plans')
        razorpay_order_id = _create_razorpay_order(
            receipt=f'evt_{event_registration.id}_{int(time.time())}',
            amount_paise=round(selected_plan['total'] * 100),
            event_registration=event_registration,
        )
        if not razorpay_order_id:
            messages.error(request, USER_PAYMENT_UNAVAILABLE)
            return redirect('events:plans')

    if agent_id:
        try:
            agent = Agent.objects.get(pk=agent_id)
            agent.registration_step = 2
            agent.status = 'pending_payment'
            agent.save()
            subscription = AgentSubscription.objects.filter(agent=agent).order_by('-created_at').first()
            if subscription:
                subscription.razorpay_order_id = razorpay_order_id
                subscription.save()
        except Agent.DoesNotExist:
            pass

    return render(request, 'events/payment.html', {
        'event_registration': event_registration,
        'selected_plan': {
            'key': plan_key,
            **selected_plan,
            'total_cents': int(round(selected_plan['total'] * 100)),
        },
        'razorpay_order_id': razorpay_order_id,
        'razorpay_key': key,
    })


class _EventAlreadyPaid(Exception):
    """Raised inside the payment transaction when a parallel request finished first."""


@require_POST
@csrf_protect
def payment_success(request):
    payment_id = request.POST.get('razorpay_payment_id') or ''
    order_id = request.POST.get('razorpay_order_id') or ''
    signature = request.POST.get('razorpay_signature') or ''

    if not payment_id or not order_id:
        return JsonResponse({'success': False, 'message': 'Payment details missing.'}, status=400)

    if not _verify_razorpay_signature(order_id, payment_id, signature):
        logger.warning(f"EVENT REGISTRATION - Invalid signature. order={order_id} payment={payment_id}")
        return JsonResponse({'success': False, 'message': 'Payment verification failed. Please contact support.'}, status=422)

    event_reg_id = request.session.get('current_event_registration_id')
    event_registration = EventRegistration.objects.filter(pk=event_reg_id).first() if event_reg_id else None

    if not event_registration:
        verified_email = request.session.get('verified_email')
        if verified_email:
            event_registration = EventRegistration.objects.filter(
                razorpay_order_id=order_id, email=verified_email
            ).first()

    if not event_registration:
        logger.error(f"EVENT REGISTRATION PAYMENT SUCCESS - record not found for order {order_id}")
        return JsonResponse({'success': False, 'message': 'Event registration record not found.'}, status=404)

    if event_registration.payment_status == 'success':
        return JsonResponse({
            'success': True,
            'message': 'Already registered successfully.',
            'redirect_url': '/events/success/',
        })

    # One captured payment must never complete more than one registration.
    # An order that belongs to ANOTHER registration is rejected; a stale order of
    # this same registration (plan re-selected in another tab) is still accepted
    # because the payment id is unique and the amount is verified below.
    if (event_registration.razorpay_order_id or '') != order_id:
        if EventRegistration.objects.filter(razorpay_order_id=order_id).exclude(pk=event_registration.pk).exists():
            logger.critical(
                'EVENT REGISTRATION - order mismatch: reg=%s has order=%s, payment claims order=%s of another registration',
                event_registration.pk, event_registration.razorpay_order_id, order_id,
            )
            return JsonResponse({'success': False, 'message': 'Payment verification failed. Please contact support.'}, status=422)
        logger.warning(
            'EVENT REGISTRATION - reg=%s paid stale order %s (current order %s); accepted after payment/amount checks.',
            event_registration.pk, order_id, event_registration.razorpay_order_id,
        )
    if EventRegistration.objects.filter(razorpay_payment_id=payment_id).exclude(pk=event_registration.pk).exists():
        logger.critical('EVENT REGISTRATION - payment %s already used by another registration', payment_id)
        return JsonResponse({'success': False, 'message': 'Payment verification failed. Please contact support.'}, status=422)

    # Verify payment against Razorpay API (amount + status)
    import razorpay
    from django.conf import settings

    key, secret = _razorpay_key(), _razorpay_secret()
    if not key or not secret:
        logger.error('EVENT REGISTRATION - Razorpay keys not configured.')
        return JsonResponse({'success': False, 'message': 'Payment verification failed. Please contact support.'}, status=400)

    try:
        client = razorpay.Client(auth=(key, secret))
        rzp_payment = client.payment.fetch(payment_id)
        if rzp_payment.get('status') not in ('authorized', 'captured'):
            return JsonResponse({'success': False, 'message': 'Payment is not completed.'}, status=400)

        pricing = get_pricing(event_registration.promocode)
        plan_key = event_registration.selected_plan or 'professional'
        plan_data = pricing.get(plan_key, pricing['professional'])
        expected_paise = int(round(plan_data['total'] * 100))
        if int(rzp_payment.get('amount', 0)) != expected_paise:
            logger.critical(f"EVENT REGISTRATION - Amount mismatch. Paid={rzp_payment.get('amount')}, Expected={expected_paise}")
            return JsonResponse({'success': False, 'message': 'Payment amount mismatch.'}, status=400)
    except Exception as exc:
        logger.error(f"EVENT REGISTRATION PAYMENT SUCCESS - verification failed: {exc}")
        return JsonResponse({'success': False, 'message': 'Payment verification failed. Please contact support.'}, status=400)

    generated_password = ''.join(random.choices(string.ascii_letters + string.digits, k=12))

    try:
        with transaction.atomic():
            locked = EventRegistration.objects.select_for_update().get(pk=event_registration.pk)
            if locked.payment_status == 'success':
                # Completed concurrently: don't regenerate password/invoice/email.
                raise _EventAlreadyPaid()

            locked.status = 'completed'
            locked.payment_status = 'success'
            locked.current_step = 3
            locked.razorpay_payment_id = payment_id
            locked.razorpay_order_id = order_id
            locked.save()

            agent = Agent.objects.select_for_update().filter(email=locked.email).first()
            if not agent:
                raise ValueError('No agent found for email: ' + locked.email)

            pricing = get_pricing(locked.promocode)
            plan_key_agent = agent.plan_type or locked.selected_plan or 'professional'
            plan_data = pricing.get(plan_key_agent, pricing['professional'])

            agent.status = 'pending_approval'
            agent.registration_step = 3
            agent.plan_type = plan_key_agent
            agent.save()

            subscription = AgentSubscription.objects.filter(agent=agent).order_by('-created_at').first()
            if not subscription:
                subscription = AgentSubscription.objects.create(
                    agent=agent,
                    selected_plan=plan_data['name'],
                    registration_amount=plan_data['total'],
                    payment_status='completed',
                    status='active',
                    promo_code=locked.promocode or None,
                )
            subscription.selected_plan = plan_data['name']
            subscription.registration_amount = plan_data['total']
            subscription.payment_status = 'completed'
            subscription.status = 'active'
            subscription.promo_code = locked.promocode or None
            subscription.razorpay_payment_id = payment_id
            subscription.razorpay_order_id = order_id
            subscription.razorpay_signature = signature or None
            subscription.starts_at = timezone.now()
            subscription.expires_at = timezone.now() + timezone.timedelta(days=365)
            subscription.save()

            from django.contrib.auth.models import User as AuthUser
            is_new_user = not AuthUser.objects.filter(email=agent.email).exists()
            user = create_or_link_django_user(agent, plain_password=generated_password if is_new_user else None)

        # Post-transaction (best effort): cache password, promo usage, invoice + welcome email
        if is_new_user:
            cache.set(_password_cache_key(agent.email), generated_password, timeout=600)
        request.session['registration_success_email'] = agent.email
        _clear_flow_session(request)

        if locked.promocode:
            try:
                from django.db.models import F
                PromoCode.objects.filter(code=locked.promocode).update(
                    times_used=F('times_used') + 1
                )
            except Exception:
                pass

        try:
            from apps.agents.services.brevo import email_service
            from apps.agents.services.invoice import invoice_service
            invoice = invoice_service.generate_from_subscription(agent, subscription)
            pdf_path = None
            if invoice and invoice.pdf_path:
                import os
                from django.conf import settings as _s
                pdf_path = os.path.join(_s.MEDIA_ROOT, 'app', 'private', invoice.pdf_path)
            email_service.send_welcome(
                to_email=agent.email,
                to_name=agent.fullname,
                temp_password=generated_password,
                plan_name=subscription.selected_plan,
                attachment_path=pdf_path,
            )
        except Exception as mail_err:
            logger.error(f"EVENT REGISTRATION - post-payment invoice/email failed: {mail_err}")

        if not request.user.is_authenticated:
            try:
                login(request, user, backend='django.contrib.auth.backends.ModelBackend')
                request.session.save()
            except Exception as login_err:
                logger.warning(f"EVENT REGISTRATION - auto-login failed: {login_err}")

        return JsonResponse({
            'success': True,
            'message': 'Payment validated and registration completed successfully!',
            'redirect_url': '/events/success/',
        })

    except _EventAlreadyPaid:
        return JsonResponse({
            'success': True,
            'message': 'Already registered successfully.',
            'redirect_url': '/events/success/',
        })
    except Exception as exc:
        logger.error(f"EVENT REGISTRATION PAYMENT SUCCESS - processing failed: {exc}")
        return JsonResponse({'success': False, 'message': 'Could not complete registration. Please contact support.'}, status=500)


@require_POST
@csrf_protect
def payment_failure(request):
    event_reg_id = request.session.get('current_event_registration_id')
    event_registration = EventRegistration.objects.filter(pk=event_reg_id).first() if event_reg_id else None

    order_id = request.POST.get('razorpay_order_id') or ''
    if not event_registration and order_id:
        event_registration = EventRegistration.objects.filter(razorpay_order_id=order_id).first()

    if event_registration and event_registration.payment_status != 'success':
        event_registration.payment_status = 'failed'
        event_registration.save(update_fields=['payment_status', 'updated_at'])

    return JsonResponse({'success': True, 'message': 'Transaction failure logged successfully.'})


def show_success(request):
    event_registration = None

    if request.user.is_authenticated:
        event_registration = EventRegistration.objects.filter(
            email=request.user.email, payment_status='success'
        ).order_by('-created_at').first()

    if not event_registration:
        email = request.session.get('registration_success_email')
        if email:
            event_registration = EventRegistration.objects.filter(
                email=email, payment_status='success'
            ).order_by('-created_at').first()

    if not event_registration:
        messages.error(request, 'No completed registration found. Please complete payment first.')
        return redirect('events:register.form')

    temp_password = None
    try:
        temp_password = cache.get(_password_cache_key(event_registration.email))
    except Exception:
        pass

    return render(request, 'events/success.html', {
        'event_registration': event_registration,
        'temp_password': temp_password,
    })


# ─── AJAX Promo verification ─────────────────────────────────────────────────

@require_POST
@csrf_protect
def verify_promo_code(request):
    code = (request.POST.get('promo_code') or '').strip().upper()
    if not code:
        return JsonResponse({'success': False, 'message': 'Please enter a promo code.'}, status=400)

    promo = PromoCode.objects.filter(code=code).first()
    if not promo or not promo.is_valid():
        return JsonResponse({'success': False, 'message': 'Invalid or expired promo code.'})

    discount = promo.calculate_discount(PROFESSIONAL_BASE)
    if promo.discount_type == 'percentage':
        discount_formatted = f"{promo.discount_value:.0f}% (₹{discount:,.0f} off)"
    else:
        discount_formatted = f"₹{discount:,.0f}"

    return JsonResponse({
        'success': True,
        'message': f"Promo code applied! You save {discount_formatted} on Professional's Plan.",
        'discount_type': promo.discount_type,
        'discount_value': float(promo.discount_value),
        'discount_amount': float(discount),
        'professional_only': True,
    })


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _razorpay_key():
    from django.conf import settings
    return getattr(settings, 'RAZORPAY_KEY', '')


def _razorpay_secret():
    from django.conf import settings
    return getattr(settings, 'RAZORPAY_SECRET', '')


def _create_razorpay_order(receipt, amount_paise, event_registration):
    import razorpay

    key = _razorpay_key()
    secret = _razorpay_secret()
    if not key or not secret or key.startswith('your_'):
        return None
    try:
        client = razorpay.Client(auth=(key, secret))
        order = client.order.create({
            'receipt': receipt,
            'amount': amount_paise,
            'currency': 'INR',
            'payment_capture': 1,
        })
        order_id = order.get('id')
        if order_id and event_registration:
            EventRegistration.objects.filter(pk=event_registration.pk).update(razorpay_order_id=order_id)
        return order_id
    except Exception as exc:
        logger.error(f"EVENT REGISTRATION - Razorpay order creation failed: {exc}")
        return None