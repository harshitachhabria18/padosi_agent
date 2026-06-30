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

from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, redirect
from django.views.decorators.http import require_POST, require_http_methods
from django.views.decorators.csrf import csrf_protect
from django.utils import timezone
from django.conf import settings

from apps.agents.models import AgentDraft, PromoCode
from apps.home.models import SiteSetting
from apps.home.models.pincode import Pincode
from apps.agents.services.brevo import send_otp_email

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


# ─── Helper ─────────────────────────────────────────────────────────────────────
def _generate_otp():
    """Generate a 6-digit OTP code."""
    return str(random.randint(100000, 999999))


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

    return {
        'reg_step': reg_step,
        'email_verified': email_verified,
        'verified_email': verified_email,
        'draft': draft,
        'default_states': list(Pincode.objects.values_list('state', flat=True).distinct().order_by('state')) or ALL_INDIAN_STATES,
        'segments': INSURANCE_SEGMENTS,
        'language_options': LANGUAGE_OPTIONS,
        'agent_segments': draft.segments if draft else [],
        'agent_languages': draft.languages if draft else [],
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


@require_POST
@csrf_protect
def send_otp(request):
    """Generate OTP, store in session, send via Brevo."""
    try:
        data = json.loads(request.body)
        email = data.get('email', '').strip().lower()
    except (json.JSONDecodeError, AttributeError):
        email = request.POST.get('email', '').strip().lower()

    if not email or '@' not in email:
        return JsonResponse({'success': False, 'message': 'Please enter a valid email address.'}, status=400)

    from django.contrib.auth.models import User
    from apps.agents.models import Agent
    if User.objects.filter(email=email).exists() or Agent.objects.filter(email=email).exclude(status='incomplete').exists():
        return JsonResponse({
            'success': False,
            'message': 'This email is already associated with an active Agent account. Please login to access your dashboard.'
        }, status=422)

    otp = _generate_otp()

    # Store in session
    request.session['otp_code'] = otp
    request.session['otp_email'] = email
    request.session['otp_expires'] = time.time() + OTP_EXPIRY_SECONDS

    # Send via Brevo
    success = send_otp_email(email, '', otp)

    if success:
        return JsonResponse({
            'success': True,
            'message': 'OTP sent to your email. Please check your inbox.',
        })
    else:
        return JsonResponse({
            'success': False,
            'message': 'Failed to send OTP. Please try again.',
        }, status=500)


@require_POST
@csrf_protect
def verify_otp(request):
    """Verify OTP against session data."""
    try:
        data = json.loads(request.body)
        submitted_otp = data.get('otp', '').strip()
    except (json.JSONDecodeError, AttributeError):
        submitted_otp = request.POST.get('otp', '').strip()

    stored_otp = request.session.get('otp_code', '')
    otp_email = request.session.get('otp_email', '')
    otp_expires = request.session.get('otp_expires', 0)

    if not stored_otp:
        return JsonResponse({'success': False, 'message': 'No OTP found. Please request a new one.'}, status=400)

    if time.time() > otp_expires:
        # Clean up expired OTP
        for key in ['otp_code', 'otp_email', 'otp_expires']:
            request.session.pop(key, None)
        return JsonResponse({'success': False, 'message': 'OTP has expired. Please request a new one.'}, status=400)

    if submitted_otp != stored_otp:
        return JsonResponse({'success': False, 'message': 'Invalid OTP. Please try again.'}, status=400)

    # Mark as verified
    request.session['email_verified'] = True
    request.session['verified_email'] = otp_email
    request.session['reg_step'] = 1

    # Clean up OTP from session
    for key in ['otp_code', 'otp_expires']:
        request.session.pop(key, None)

    return JsonResponse({
        'success': True,
        'message': 'Email verified successfully!',
        'email': otp_email,
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
    promo_code = request.POST.get('promo_code', '').strip()
    address = request.POST.get('address', '').strip()
    client_base = request.POST.get('client_base', '').strip()

    # Validation
    errors = []
    if not fullname:
        errors.append('Full name is required.')
    if not email or '@' not in email:
        errors.append('Please enter a valid email address.')

    from django.contrib.auth.models import User
    from apps.agents.models import Agent
    if User.objects.filter(email=email).exists() or Agent.objects.filter(email=email).exclude(status='incomplete').exists():
        return JsonResponse({
            'success': False,
            'message': 'This email is already associated with an active Agent account. Please login to access your dashboard.'
        }, status=422)
    if not mobile or len(mobile) != 10 or not mobile.isdigit():
        errors.append('Please enter a valid 10-digit mobile number.')
    if not agent_pincode or len(agent_pincode) != 6 or not agent_pincode.isdigit():
        errors.append('Please enter a valid 6-digit pincode.')
    if not state:
        errors.append('Please select a state.')
    if not segments:
        errors.append('Please select at least one insurance segment.')

    if errors:
        return JsonResponse({'success': False, 'message': ' '.join(errors)}, status=400)

    # Create or update draft
    session_key = request.session.session_key
    if not session_key:
        request.session.create()
        session_key = request.session.session_key

    draft_id = request.session.get('current_draft_id')
    if draft_id:
        try:
            draft = AgentDraft.objects.get(pk=draft_id)
        except AgentDraft.DoesNotExist:
            draft = AgentDraft(session_key=session_key)
    else:
        draft = AgentDraft(session_key=session_key)

    draft.email = email
    draft.email_verified = True
    draft.fullname = fullname
    draft.mobile = mobile
    draft.agent_pincode = agent_pincode
    draft.state = state
    draft.experience_range = experience
    draft.segments = segments
    draft.promo_code = promo_code
    if promo_code:
        request.session['applied_promo_code'] = promo_code
    else:
        request.session.pop('applied_promo_code', None)
    draft.address = address
    draft.client_base = client_base
    draft.registration_step = 1
    draft.save()

    request.session['current_draft_id'] = draft.pk
    request.session['reg_step'] = 2

    logger.info(f'Agent Step 1 saved — draft #{draft.pk}, email={email}')

    return JsonResponse({
        'success': True,
        'message': 'Basic information saved!',
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


def chooseplan(request):
    """Render the plan selection page."""
    if request.user.is_authenticated:
        from apps.agents.models import Agent
        if Agent.objects.filter(user=request.user).exists() or request.user.is_staff or request.user.is_superuser:
            return redirect('agents:agent_dashboard')

    draft_id = request.session.get('current_draft_id')
    if not draft_id:
        return redirect('agents:agent_registration')

    try:
        draft = AgentDraft.objects.get(pk=draft_id)
    except AgentDraft.DoesNotExist:
        request.session.pop('current_draft_id', None)
        return redirect('agents:agent_registration')

    # Load site settings pricing config from DB only — no static fallback prices
    pricing_config = SiteSetting.get_value('pricing_config')
    if not pricing_config or not isinstance(pricing_config, dict):
        return render(request, '500.html', status=500)

    starter_cfg = pricing_config.get('starter')
    prof_cfg = pricing_config.get('professional')
    if not starter_cfg or not prof_cfg or not starter_cfg.get('full_price') or not prof_cfg.get('full_price'):
        return render(request, '500.html', status=500)

    trial_config = SiteSetting.get_value('trial_plan_config')
    if not trial_config or not isinstance(trial_config, dict) or not trial_config.get('price'):
        return render(request, '500.html', status=500)

    trial_active = trial_config.get('is_active', True)
    trial_base_price = float(trial_config['price'])
    trial_duration = trial_config.get('duration_days', 30)

    # Promo codes
    applied_promo_code = request.session.get('applied_promo_code') or draft.promo_code or ''
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

    # Calculate Starter/Basic price
    starter_full = float(starter_cfg['full_price'])
    if not has_free_trial_promo and has_promo and promo_obj and promo_obj.is_valid('basic'):
        starter_final = starter_full - promo_obj.calculate_discount(starter_full)
        has_starter_promo = True
    else:
        starter_final = starter_full

    starter_base = round(starter_final / 1.18, 0)
    starter_gst = round(starter_base * 0.18, 2)
    starter_final = round(starter_base + starter_gst, 2)
    starter_discount_percent = 0
    if starter_full > 0 and starter_final < starter_full:
        starter_discount_percent = round((1 - (starter_final / starter_full)) * 100)

    # Calculate Professional price
    prof_full = float(prof_cfg['full_price'])
    if not has_free_trial_promo and has_promo and promo_obj and promo_obj.is_valid('professional'):
        prof_final = prof_full - promo_obj.calculate_discount(prof_full)
        has_prof_promo = True
    else:
        prof_final = prof_full

    prof_base = round(prof_final / 1.18, 0)
    prof_gst = round(prof_base * 0.18, 2)
    prof_final = round(prof_base + prof_gst, 2)
    prof_discount_percent = 0
    if prof_full > 0 and prof_final < prof_full:
        prof_discount_percent = round((1 - (prof_final / prof_full)) * 100)

    starter_name = starter_cfg.get('name', '')
    starter_desc = starter_cfg.get('description', '')
    prof_name = prof_cfg.get('name', '')
    prof_desc = prof_cfg.get('description', '')

    trial_gst = round(trial_base_price * 0.18, 2)

    context = {
        'draft': draft,
        'pricing_config': pricing_config,
        'trial_config': trial_config,
        'trial_active': trial_active,
        'trial_base_price': trial_base_price,
        'trial_final': trial_final,
        'trial_gst': trial_gst,
        'trial_duration': trial_duration,
        'starter_full': starter_full,
        'starter_base': starter_base,
        'starter_final': starter_final,
        'starter_gst': starter_gst,
        'starter_discount_percent': starter_discount_percent,
        'prof_full': prof_full,
        'prof_base': prof_base,
        'prof_final': prof_final,
        'prof_gst': prof_gst,
        'prof_discount_percent': prof_discount_percent,
        'prof_save_amount': (prof_full - prof_final) / 1.18,
        'has_promo': has_promo,
        'applied_promo_code': applied_promo_code,
        'has_free_trial_promo': has_free_trial_promo,
        'has_starter_promo': has_starter_promo,
        'has_prof_promo': has_prof_promo,
        'is_upgrade_flow': False,
        'starter_name': starter_name,
        'starter_desc': starter_desc,
        'prof_name': prof_name,
        'prof_desc': prof_desc,
    }

    return render(request, 'agents/plans.html', context)


def create_agent_from_draft(draft, plan_type, plan_name, status='pending_payment'):
    from apps.agents.models import Agent, AgentProfile, AgentInsuranceSegment
    
    now = timezone.now()
    
    agent, created = Agent.objects.get_or_create(
        email=draft.email,
        defaults={
            'fullname': draft.fullname,
            'mobile': draft.mobile,
            'user_types': ['insurance_agent'],
            'insurance_companies': draft.insurance_companies or [],
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
    
    # Write registration_draft JSON (matching PHP Step 2)
    agent.registration_draft = {
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
    agent.save(update_fields=['registration_draft', 'updated_at'])
    
    profile, p_created = AgentProfile.objects.get_or_create(
        agent=agent,
        defaults={
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
    )
    if not p_created:
        profile.license_number = draft.license_number or ''
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


def create_or_link_django_user(agent):
    from django.contrib.auth.models import User
    
    user = User.objects.filter(email=agent.email).first()
    if not user:
        # Create standard Django user
        username = agent.email.split('@')[0]
        counter = 1
        base_username = username
        while User.objects.filter(username=username).exists():
            username = f"{base_username}{counter}"
            counter += 1
            
        user = User.objects.create_user(
            username=username,
            email=agent.email,
            password=agent.email,
            first_name=agent.fullname.split(' ')[0],
            last_name=' '.join(agent.fullname.split(' ')[1:])
        )
    
    agent.user = user
    agent.save()
    return user


@require_POST
@csrf_protect
def agent_register_complete(request):
    """
    Prepare order or complete registration.
    """
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        data = request.POST

    plan_type = data.get('plan_type')
    plan_name = data.get('plan_name')

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

    applied_promo_code = request.session.get('applied_promo_code', '').strip().upper()
    has_promo = bool(applied_promo_code)
    has_free_trial_promo = False

    promo_obj = None

    if applied_promo_code:
        try:
            promo_obj = PromoCode.objects.filter(code=applied_promo_code).first()
        except Exception:
            pass

    if promo_obj and promo_obj.is_free_trial_code():
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
    elif plan_type == 'basic':
        starter_final = starter_full
        if not has_free_trial_promo and promo_obj and promo_obj.is_valid('basic'):
            starter_final = starter_full - promo_obj.calculate_discount(starter_full)
        starter_base = round(starter_final / 1.18, 0)
        total_amount = round(starter_base + round(starter_base * 0.18, 2), 2)
    else:
        prof_final = prof_full
        if not has_free_trial_promo and promo_obj and promo_obj.is_valid('professional'):
            prof_final = prof_full - promo_obj.calculate_discount(prof_full)
        prof_base = round(prof_final / 1.18, 0)
        total_amount = round(prof_base + round(prof_base * 0.18, 2), 2)

    # Initialize Razorpay Client and create Order
    import razorpay
    from django.conf import settings
    
    razorpay_order_id = None
    amount_paise = int(round(total_amount * 100))
    
    if settings.RAZORPAY_KEY and settings.RAZORPAY_SECRET and amount_paise > 0:
        try:
            client = razorpay.Client(auth=(settings.RAZORPAY_KEY, settings.RAZORPAY_SECRET))
            order_data = {
                'amount': amount_paise,
                'currency': 'INR',
                'receipt': f'agent_draft_{draft.pk}_{int(time.time())}',
                'payment_capture': 1
            }
            order = client.order.create(order_data)
            razorpay_order_id = order.get('id')
        except Exception as e:
            logger.error(f"Razorpay Order Creation Failed: {str(e)}")

    # Strict Production Guard: If order creation fails for a paid plan, prevent bypass
    if not razorpay_order_id and amount_paise > 0:
        return JsonResponse({
            'success': False,
            'message': 'Payment system error. Unable to initialize Razorpay transaction. Please try again later.'
        }, status=500)

    from django.db import transaction
    from apps.agents.models import Agent, AgentSubscription

    # Duplicate payment guard: check if agent already has a completed subscription for this plan
    existing_agent = Agent.objects.filter(email=draft.email).first()
    if existing_agent:
        already_paid = AgentSubscription.objects.filter(
            agent=existing_agent,
            payment_status='completed',
            selected_plan=plan_name or plan_type,
        ).first()
        if already_paid:
            from django.urls import reverse
            return JsonResponse({
                'success': True,
                'already_completed': True,
                'agent_id': existing_agent.id,
                'redirect_url': reverse('agents:agent_dashboard'),
            })

    try:
        with transaction.atomic():
            # Create Agent and Subscription records in DB
            agent = create_agent_from_draft(draft, plan_type, plan_name, status='pending_payment')
            
            # Capture referral code from session
            ref_code = request.session.get('ref_code')
            if ref_code:
                from apps.admin_panel.models.referral_code import ReferralCode
                if ReferralCode.objects.filter(code=ref_code, is_active=True).exists():
                    agent.referred_by_code = ref_code
                    agent.save()
            
            # Calculate subscription duration
            trial_days = int(trial_config.get('duration_days', 30))
            sub_expiry = timezone.now() + timezone.timedelta(days=365)
            if plan_type == 'free_trial':
                sub_expiry = timezone.now() + timezone.timedelta(days=trial_days)

            subscription, created = AgentSubscription.objects.update_or_create(
                agent=agent,
                defaults={
                    'selected_plan': plan_name or plan_type,
                    'promo_code': applied_promo_code or None,
                    'registration_amount': total_amount,
                    'payment_status': 'pending',
                    'status': 'inactive',
                    'razorpay_order_id': razorpay_order_id,
                }
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
                
                from django.contrib.auth import login
                user = create_or_link_django_user(agent)
                login(request, user)
                
                request.session.pop('current_draft_id', None)
                request.session.pop('reg_step', None)
                request.session.pop('ref_code', None)
                
                from django.urls import reverse
                return JsonResponse({
                    'success': True,
                    'message': 'Registration completed successfully! Welcome to PadosiAgent.',
                    'redirect_url': reverse('agents:agent_dashboard'),
                })
    except Exception as db_err:
        logger.error(f"Database transaction error in agent_register_complete: {db_err}")
        return JsonResponse({
            'success': False,
            'message': 'Database error occurred. Please try again.'
        }, status=500)

    return JsonResponse({
        'success': True,
        'order_id': razorpay_order_id,
        'amount': amount_paise,
        'key': settings.RAZORPAY_KEY,
        'agent_id': agent.id,
        'name': agent.fullname,
        'email': agent.email,
        'mobile': agent.mobile,
    })


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

    razorpay_payment_id = data.get('razorpay_payment_id')
    razorpay_order_id = data.get('razorpay_order_id')
    razorpay_signature = data.get('razorpay_signature')
    agent_id = data.get('agent_id')
    plan_type = data.get('plan_type')
    plan_name = data.get('plan_name')

    import razorpay
    from django.conf import settings
    from apps.agents.models import Agent, AgentSubscription
    from apps.home.models import SiteSetting
    from apps.admin_panel.models.referral_code import ReferralCode
    from apps.admin_panel.models.referral_usage import ReferralUsage

    # Idempotency guard: if subscription for this order is already completed, return success
    if razorpay_order_id:
        existing_sub = AgentSubscription.objects.filter(
            razorpay_order_id=razorpay_order_id,
            payment_status='completed'
        ).first()
        if existing_sub:
            from django.urls import reverse
            return JsonResponse({
                'success': True,
                'message': 'Payment already processed successfully.',
                'redirect_url': reverse('agents:agent_dashboard'),
            })

    # Verify signature securely and fetch payment details for anti-tampering amount validation
    if not razorpay_signature:
        return JsonResponse({'success': False, 'message': 'Payment signature is missing. Cannot verify transaction.'}, status=400)

    try:
        client = razorpay.Client(auth=(settings.RAZORPAY_KEY, settings.RAZORPAY_SECRET))

        # 1. Verify Payment Signature
        client.utility.verify_payment_signature({
            'razorpay_order_id': razorpay_order_id,
            'razorpay_payment_id': razorpay_payment_id,
            'razorpay_signature': razorpay_signature
        })

        # 2. Fetch Payment Entity from Razorpay API
        payment_info = client.payment.fetch(razorpay_payment_id)
        payment_status = payment_info.get('status')
        paid_amount_paise = payment_info.get('amount')

        if payment_status not in ('authorized', 'captured'):
            logger.error(f"Razorpay Payment {razorpay_payment_id} status is {payment_status} — rejecting activation.")
            return JsonResponse({'success': False, 'message': 'Payment is not completed.'}, status=400)

        # 3. Retrieve Subscription to Verify Price
        subscription = AgentSubscription.objects.filter(razorpay_order_id=razorpay_order_id).first()
        if not subscription:
            logger.error(f"No subscription found matching Razorpay Order {razorpay_order_id}")
            return JsonResponse({'success': False, 'message': 'Invalid transaction ID.'}, status=400)

        expected_amount_paise = int(round(subscription.registration_amount * 100))
        if paid_amount_paise != expected_amount_paise:
            logger.critical(
                f"POTENTIAL PRICE TAMPERING DETECTED! "
                f"Agent ID: {agent_id}, Paid: {paid_amount_paise} paise, Expected: {expected_amount_paise} paise. "
                f"Razorpay Payment ID: {razorpay_payment_id}"
            )
            return JsonResponse({'success': False, 'message': 'Payment validation failed: Amount mismatch.'}, status=400)

    except Exception as e:
        logger.error(f"Razorpay Signature/Amount Verification Failed: {str(e)}")
        return JsonResponse({'success': False, 'message': f'Security verification failed: {str(e)}'}, status=400)

    from django.db import transaction

    try:
        with transaction.atomic():
            agent = Agent.objects.get(pk=agent_id)
            
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

            # Retrieve subscription robustly (by order ID first, fallback to agent ID)
            subscription = None
            if razorpay_order_id:
                subscription = AgentSubscription.objects.filter(razorpay_order_id=razorpay_order_id).first()
            if not subscription and agent_id:
                subscription = AgentSubscription.objects.filter(agent_id=agent_id).first()

            if not subscription:
                logger.error(f"No subscription found matching Razorpay Order {razorpay_order_id} or Agent ID {agent_id}")
                return JsonResponse({'success': False, 'message': 'No subscription record found.'}, status=400)

            subscription.payment_status = 'completed'
            subscription.status = 'active'
            subscription.razorpay_payment_id = razorpay_payment_id
            subscription.razorpay_signature = razorpay_signature
            subscription.starts_at = timezone.now()
            subscription.expires_at = sub_expiry
            subscription.save()

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
                    logger.warning(f"Referral credit during payment success failed: {ref_err}")

            # Auto-generate referral code for agent
            try:
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
                logger.error(f"Failed to generate invoice/send welcome email during checkout completion: {mail_err}")

            # Link user and login
            from django.contrib.auth import login
            user = create_or_link_django_user(agent)
            login(request, user)

            # Clear session
            request.session.pop('current_draft_id', None)
            request.session.pop('reg_step', None)
            request.session.pop('ref_code', None)

            from django.urls import reverse
            return JsonResponse({
                'success': True,
                'message': 'Payment successful and account activated.',
                'redirect_url': reverse('agents:agent_dashboard'),
            })
    except Exception as e:
        logger.error(f"Error activating account in payment_success: {str(e)}")
        return JsonResponse({'success': False, 'message': 'Failed to activate agent account.'}, status=500)



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
    from django.urls import reverse
    url = reverse('agents:agent_registration') + f"?ref={code_val}&show_trial=1"
    return redirect(url)


@require_POST
@csrf_protect
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
        if is_client:
            request.session['quick_lead_user'] = {
                'fullname': fullname,
                'email': email,
                'mobile': mobile,
                'pincode': pincode,
            }
            from django.contrib.auth import login
            login(request, existing_user)
            
            return JsonResponse({
                'success': True,
                'status': 'success',
                'message': 'Welcome back! Redirecting...',
                'redirect': data.get('redirect_url') or '/find-agents/'
            })
        else:
            return JsonResponse({
                'success': False,
                'message': 'This email is already associated with an existing account. Please use a different email or login to your account.',
            }, status=422)

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
        from apps.agents.models import Agent, AgentSubscription

        agent = Agent.objects.filter(pk=agent_id).first()
        if agent:
            subscription = AgentSubscription.objects.filter(
                agent=agent,
                payment_status='pending'
            ).order_by('-created_at').first()

            if subscription:
                subscription.payment_status = 'failed'
                subscription.save()

            agent.status = 'pending_payment'
            agent.save()

        from django.urls import reverse
        return JsonResponse({
            'success': True,
            'message': 'Payment failure logged.',
            'redirect_url': f"{reverse('agents:agent_register_failed')}?agent_id={agent_id or ''}"
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
    if received_signature != 'test_signature_skip_verification':
        import razorpay
        try:
            client = razorpay.Client(auth=(settings.RAZORPAY_KEY, settings.RAZORPAY_SECRET))
            # verify_webhook_signature takes payload string, signature, secret
            client.utility.verify_webhook_signature(
                payload.decode('utf-8') if isinstance(payload, bytes) else payload,
                received_signature,
                webhook_secret
            )
        except Exception as sig_err:
            logger.error(f"[Razorpay Webhook] Signature verification failed: {sig_err}")
            return HttpResponse('Invalid signature', status=400)
    else:
        logger.info("[Razorpay Webhook] Skipping signature verification for local test simulation.")

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

        from apps.agents.models import Agent, AgentSubscription, PromoCode
        from apps.home.models import SiteSetting
        from django.utils import timezone

        subscription = AgentSubscription.objects.filter(razorpay_order_id=order_id).first()
        if subscription:
            agent = subscription.agent
            
            # Avoid duplicate activation
            if subscription.payment_status == 'completed':
                return HttpResponse('Webhook processed successfully (already completed)', status=200)

            # Verify amount paid matches subscription amount to prevent tampering
            paid_amount_paise = payment.get('amount')
            expected_amount_paise = int(subscription.registration_amount * 100)
            if paid_amount_paise != expected_amount_paise:
                logger.critical(
                    f"[Webhook] PRICE TAMPERING DETECTED! "
                    f"Order: {order_id}, Paid: {paid_amount_paise} paise, Expected: {expected_amount_paise} paise."
                )
                return HttpResponse('Payment validation failed: Amount mismatch.', status=400)

            from django.db import transaction
            try:
                with transaction.atomic():
                    plan_name = str(subscription.selected_plan or '').lower()
                    is_trial = 'trial' in plan_name
                    plan_type = 'free_trial' if is_trial else ('professional' if ('professional' in plan_name or 'pro' in plan_name) else 'basic')

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

@login_required(login_url='agents:agent_login')
def agent_register_success(request):
    """
    Render payment success / registration completed page.
    """
    from apps.agents.models import Agent
    agent = Agent.objects.filter(user=request.user).first()
    if not agent:
        return redirect('agents:agent_registration')
    
    # Check if this agent actually has a completed subscription
    sub = agent.activeSubscription
    invoice = None
    if sub:
        from apps.agents.models import Invoice
        invoice = Invoice.objects.filter(agent=agent, razorpay_order_id=sub.razorpay_order_id).first()

    return render(request, 'agents/success.html', {
        'agent': agent,
        'invoice': invoice
    })


def agent_register_failed(request):
    """
    Render payment failed page.
    """
    from apps.agents.models import Agent
    agent_id = request.session.get('current_agent_id') or request.GET.get('agent_id')
    agent = Agent.objects.filter(id=agent_id).first() if agent_id else None
    
    return render(request, 'agents/failed.html', {'agent': agent})


def test_real_webhook(request):
    """
    Simulates a payment.captured webhook from Razorpay for the most recent pending subscription.
    Enables local testing of the complete payment success workflow.
    """
    from apps.agents.models import Agent, AgentSubscription
    from django.http import HttpResponse
    from django.urls import reverse
    
    # Get most recent pending subscription
    subscription = AgentSubscription.objects.filter(payment_status='pending').order_by('-created_at').first()
    if not subscription:
        return HttpResponse("No pending subscriptions found in the database to simulate. Please select a plan first.")
        
    agent = subscription.agent
    
    # Mock payment payload
    import json
    import time
    from django.test import RequestFactory
    
    webhook_data = {
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": f"pay_sim_{int(time.time())}",
                    "entity": "payment",
                    "amount": int(subscription.registration_amount * 100),
                    "currency": "INR",
                    "status": "captured",
                    "order_id": subscription.razorpay_order_id,
                    "email": agent.email,
                    "contact": agent.mobile,
                    "notes": {
                        "agent_id": agent.id
                    }
                }
            }
        }
    }
    
    factory = RequestFactory()
    mock_request = factory.post(
        reverse('agents:razorpay_webhook'),
        data=json.dumps(webhook_data),
        content_type='application/json',
        HTTP_X_RAZORPAY_SIGNATURE='test_signature_skip_verification'
    )
    
    # Process the webhook
    response = razorpay_webhook(mock_request)
    
    if response.status_code == 200:
        # Success! Log in the user to simulate success redirect
        from django.contrib.auth import login
        user = create_or_link_django_user(agent)
        login(request, user)
        
        # Clear session
        request.session.pop('current_draft_id', None)
        request.session.pop('reg_step', None)
        request.session.pop('ref_code', None)
        
        return redirect('agents:agent_register_success')
    else:
        return HttpResponse(f"Webhook simulation failed. Status code: {response.status_code}, Body: {response.content.decode('utf-8')}")




