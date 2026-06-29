import logging
import math
import json
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout
from django.contrib import messages
from django.utils import timezone
from django.db.models import Sum, Q, Avg
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_protect, csrf_exempt
from apps.agents.models import Agent, AgentSubscription, AgentLead, AgentProfileView, AgentInsuranceSegment, City, AgentDeviceToken
from apps.home.models import SiteSetting
from apps.admin_panel.models.referral_code import ReferralCode
from apps.admin_panel.models.referral_usage import ReferralUsage

logger = logging.getLogger(__name__)

@login_required(login_url='agents:agent_login')
def agent_dashboard(request):
    """
    Handle rendering the agent dashboard.
    Ported from App\Http\Controllers\Agent\AgentDashboardController@index
    Includes self-healing logic and pricing calculation.
    """
    user = request.user
    agent = Agent.objects.filter(user=user).first()

    # ── Self-Heal 1: Try to find & link an orphaned agent record by email ──
    if not agent:
        agent_by_email = Agent.objects.filter(email__iexact=user.email).order_by('-created_at').first()
        if agent_by_email:
            agent_by_email.user = user
            agent_by_email.save()
            logger.info(f"AgentDashboard: Linked orphaned agent #{agent_by_email.id} to user #{user.id} ({user.email})")
            agent = agent_by_email
        else:
            messages.error(request, "Please complete your registration.")
            return redirect('agents:agent_registration')

    # ── Self-Heal 2: Stuck in pending_payment but subscription completed ──
    if agent.status in ['pending_payment', 'incomplete'] or agent.registration_step < 2:
        completed_sub = AgentSubscription.objects.filter(
            agent=agent,
            payment_status='completed',
            status='active'
        ).order_by('-created_at').first()

        if completed_sub:
            plan_name = (completed_sub.selected_plan or '').lower()
            plan_type = 'free_trial' if 'trial' in plan_name else (
                'professional' if ('professional' in plan_name or 'pro' in plan_name) else (
                'basic' if ('starter' in plan_name or 'basic' in plan_name) else 'standard'
            ))

            agent.status = 'active'
            agent.plan_type = plan_type
            agent.registration_step = 2

            if plan_type == 'free_trial' and not agent.trial_ends_at:
                agent.trial_ends_at = completed_sub.expires_at or (timezone.now() + timezone.timedelta(days=30))

            agent.save()
            logger.info(f"AgentDashboard self-heal: agent #{agent.id} promoted to active.")

    # Enforce role guard check for dashboard access
    is_admin = user.is_staff or user.is_superuser
    if not (agent or is_admin):
        logout(request)
        messages.error(request, "Unauthorized access. Gated area.")
        return redirect('agents:agent_login')

    # Load statistics
    start_of_month = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    try:
        lead_base_query = AgentLead.objects.filter(agent=agent)
        total_leads = lead_base_query.count()
        monthly_leads = lead_base_query.filter(created_at__gte=start_of_month).count()

        new_leads = lead_base_query.filter(lead_status='new').count()
        contacted_leads = lead_base_query.filter(lead_status='contacted').count()
        follow_up_leads = lead_base_query.filter(lead_status='follow_up').count()
        closed_leads = lead_base_query.filter(lead_status='closed').count()
    except Exception as e:
        logger.warning(f"Dashboard lead stats unavailable for agent #{agent.id}: {e}")
        total_leads = monthly_leads = new_leads = contacted_leads = follow_up_leads = closed_leads = 0

    active_leads = new_leads + contacted_leads + follow_up_leads
    conversion_rate = round((closed_leads / total_leads * 100), 1) if total_leads > 0 else 0.0

    try:
        total_page_views = AgentProfileView.objects.filter(agent=agent).aggregate(Sum('view_count'))['view_count__sum'] or 0
        monthly_visits = AgentProfileView.objects.filter(
            agent=agent,
            view_date__gte=start_of_month.date()
        ).aggregate(Sum('view_count'))['view_count__sum'] or 0
    except Exception as e:
        logger.warning(f"Dashboard profile view stats unavailable for agent #{agent.id}: {e}")
        total_page_views = monthly_visits = 0

    try:
        recent_leads = AgentLead.objects.filter(agent=agent).order_by('-created_at')[:10]
    except Exception as e:
        logger.warning(f"Dashboard recent leads unavailable for agent #{agent.id}: {e}")
        recent_leads = []

    dashboard_stats = {
        'conversionRate': conversion_rate,
        'monthlyTarget': 0,
        'totalPageViews': total_page_views,
        'contactRequests': total_leads,
        'monthlyVisits': monthly_visits,
        'totalLeads': total_leads,
        'monthlyLeads': monthly_leads,
        'newLeads': new_leads,
        'contactedLeads': contacted_leads,
        'followUpLeads': follow_up_leads,
        'closedLeads': closed_leads,
        'activeLeads': active_leads,
    }

    # Referral Config check
    referral_config = SiteSetting.get_value('referral_config', {'eligibility': 'free_trial_only'})
    show_referral = False
    if referral_config.get('eligibility') == 'all' or agent.plan_type == 'free_trial':
        show_referral = True

    # Profile Completion Check
    completion = 15
    profile = getattr(agent, 'profile', None)
    if profile:
        if profile.address and profile.languages:
            completion += 15
        if getattr(profile, 'service_pincodes', None) and agent.serviceableCities.exists():
            completion += 15
        if agent.insuranceSegments.exists():
            completion += 15
        # Portfolios and preferences fallback check
        # Laravel: if ($agent->portfolios->count() > 0) $completion += 15;
        # Laravel: if ($agent->leadPreferences) $completion += 15;
        # For compatibility: check related managers exists
        if hasattr(agent, 'portfolios') and agent.portfolios.exists():
            completion += 15
        if profile.profile_photo_path:
            completion += 10
        if hasattr(agent, 'leadPreferences') and agent.leadPreferences:
            completion += 15

    if agent.status == 'pending':
        completion = 100
    completion = min(completion, 100)

    # Free Trial Upgrade Discount Calculation
    is_on_trial = agent.isOnFreeTrial()
    days_left = 0
    if is_on_trial and agent.trial_ends_at:
        days_left = (agent.trial_ends_at - timezone.now()).days
        if days_left < 0:
            days_left = 0

    discount_pct = 0
    if is_on_trial:
        admin_default = SiteSetting.get_value('trial_upgrade_discount', 20)
        agent_specific = agent.upgrade_discount_percent or 0
        
        ref_code = ReferralCode.objects.filter(agent=agent).first()
        referral_discount = 0
        if ref_code:
            tier = ref_code.currentTier()
            if tier and 'discount' in tier:
                referral_discount = tier['discount']

        discount_pct = max(int(admin_default), int(agent_specific), int(referral_discount))

    pricing_config = SiteSetting.get_value('pricing_config', {
        'starter': {'name': "Starter's Plan", 'full_price': 2359},
        'professional': {'name': "Professional's Plan", 'full_price': 8258},
    })

    starter_full = float(pricing_config.get('starter', {}).get('full_price', 2359))
    prof_full = float(pricing_config.get('professional', {}).get('full_price', 8258))

    discount_factor = (100 - discount_pct) / 100
    starter_final = round(starter_full * discount_factor)
    starter_base = round(starter_final / 1.18, 0)
    starter_disc = starter_base + round(starter_base * 0.18, 0)

    prof_final = round(prof_full * discount_factor)
    if agent.referral_reward_type == 'pro_plan_1rs':
        prof_final = 1
        discount_pct = 99.99

    prof_base = round(prof_final / 1.18, 0)
    if agent.referral_reward_type == 'pro_plan_1rs':
        prof_disc = 1.00
    else:
        prof_disc = prof_base + round(prof_base * 0.18, 0)

    from django.conf import settings
    # ── Plan Name Parsing ──
    raw_plan = 'Free Plan'
    active_sub = agent.activeSubscription
    if active_sub and active_sub.selected_plan:
        import json
        try:
            decoded_plan = json.loads(active_sub.selected_plan)
            if isinstance(decoded_plan, dict) and 'name' in decoded_plan:
                raw_plan = decoded_plan['name']
            else:
                raw_plan = str(active_sub.selected_plan)
        except (json.JSONDecodeError, TypeError):
            raw_plan = str(active_sub.selected_plan)
            
    plan_name = raw_plan.replace('_', ' ').replace('-', ' ').title()

    context = {
        'agent': agent,
        'profile': profile,
        'dashboardStats': dashboard_stats,
        'recentLeads': recent_leads,
        'showReferral': show_referral,
        'completion': completion,
        'isOnTrial': is_on_trial,
        'daysLeft': days_left,
        'discountPct': discount_pct,
        'starterFull': starter_full,
        'starterDisc': starter_disc,
        'profFull': prof_full,
        'profDisc': prof_disc,
        'planName': plan_name,
        'fcm_api_key': getattr(settings, 'FCM_API_KEY', ''),
        'fcm_auth_domain': getattr(settings, 'FCM_AUTH_DOMAIN', ''),
        'fcm_project_id': getattr(settings, 'FCM_PROJECT_ID', ''),
        'fcm_storage_bucket': getattr(settings, 'FCM_STORAGE_BUCKET', ''),
        'fcm_messaging_sender_id': getattr(settings, 'FCM_MESSAGING_SENDER_ID', ''),
        'fcm_app_id': getattr(settings, 'FCM_APP_ID', ''),
        'fcm_vapid_key': getattr(settings, 'FCM_VAPID_KEY', ''),
    }

    return render(request, 'agents/dashboard.html', context)


@login_required(login_url='agents:agent_login')
def referral(request):
    """
    Handle rendering the agent referral milestone page.
    Ported from App\Http\Controllers\Agent\AgentDashboardController@referral
    """
    user = request.user
    agent = Agent.objects.filter(user=user).first()

    if not agent:
        messages.error(request, "Please complete your registration.")
        return redirect('agents:agent_registration')

    # Eligibility check
    referral_config = SiteSetting.get_value('referral_config', {'eligibility': 'free_trial_only'})
    show_referral = (referral_config.get('eligibility') == 'all' or agent.plan_type == 'free_trial')

    if not show_referral:
        messages.error(request, "Referral program is not available for your plan.")
        return redirect('agents:agent_dashboard')

    # Load or generate referral code
    ref_code = ReferralCode.objects.filter(agent=agent).first()
    if not ref_code:
        ref_code = ReferralCode.generateForAgent(agent)

    # Sync total_referrals count with actual converted usages
    actual_conversions = ReferralUsage.objects.filter(
        referral_code=ref_code,
        status='converted'
    ).count()

    if ref_code.total_referrals != actual_conversions:
        ref_code.total_referrals = actual_conversions
        ref_code.save()

    # Calculate pending conversions: agents registered via ref_code.code, but not converted yet
    registered_ids = list(Agent.objects.filter(referred_by_code=ref_code.code).values_list('id', flat=True))
    converted_ids = list(ReferralUsage.objects.filter(
        referral_code=ref_code,
        status='converted'
    ).values_list('referred_agent_id', flat=True))

    pending_count = len(set(registered_ids) - set(converted_ids))

    current_tier = ref_code.currentTier()
    next_tier = ref_code.nextTier()

    # ── Progress Bar & Tier Calculations ──
    total = int(actual_conversions)
    pending = int(pending_count)

    # Current tier label
    tier_label = 'None Yet 🏅'
    if current_tier:
        r = current_tier.get('reward', '')
        if r == 'pro_plan_1rs':
            tier_label = 'Tier 3: Pro @ ₹1 🥇'
        elif r == 'discount_50':
            tier_label = 'Tier 2: 50% OFF 🥈'
        elif r == 'discount_25':
            tier_label = 'Tier 1: 25% OFF 🥉'
        else:
            tier_label = str(r).replace('_', ' ').upper()

    # Progress bar calculation
    next_target = next_tier.get('min') if next_tier else None
    if next_target:
        prev = 0 if next_target == 5 else (5 if next_target == 10 else 10)
        raw_pct = round(((total - prev) / (next_target - prev)) * 100) if (next_target - prev) > 0 else 0
        pct = min(100, max(0, raw_pct))
        progress_label = f"{total} / {next_target} conversions"
        next_goal_text = f"{next_target - total} more to unlock next tier!"
    else:
        pct = 100
        progress_label = f"{total} / 15 ✓"
        next_goal_text = '🎉 All tiers unlocked! Claim your reward when upgrading.'

    # WhatsApp & Email messages construction (with urlencode)
    import urllib.parse
    rocket_enc = '🚀'
    point_enc = '👉'
    rupee_enc = '₹'

    wa_msg_raw = f"{rocket_enc} I've already started my digital growth journey with PadosiAgent and the response is amazing.\n\nNow it's your turn.\n\nAs my contact, you get SPECIAL TRIAL ACCESS just at {rupee_enc}99 for 30 days.\n(No Promo Code required).\n\n{point_enc} Click below & register:\n{referral_url}\n\nOnce you're in, you'll understand why smart agents are shifting online."
    wa_msg = urllib.parse.quote(wa_msg_raw)
    email_sub = urllib.parse.quote('Special Invitation: Join PadosiAgent Digital Growth')
    email_body = wa_msg

    # Build absolute referral join URL
    domain = request.get_host()
    scheme = 'https' if request.is_secure() else 'http'
    referral_url = f"{scheme}://{domain}/join/{ref_code.code}/"

    # Load referred usages
    referred_agents = ReferralUsage.objects.filter(referral_code=ref_code).order_by('-signed_up_at')

    # Load registered agents from agents table (referred_by_code)
    all_registered = Agent.objects.filter(referred_by_code=ref_code.code).order_by('-created_at')

    # Pre-process referral details for template rendering
    for referred in all_registered:
        # Find corresponding usage
        usage = referred_agents.filter(referred_agent_id=referred.id).first()
        referred.is_converted = usage and usage.status == 'converted'
        referred.converted_date = f" · {usage.converted_at.strftime('%d %b')}" if (referred.is_converted and usage.converted_at) else ''
        referred.email_display = referred.email or (usage.referred_agent_email if usage else '—')
        
        # plan label configuration
        plan = referred.plan_type or ''
        if plan == 'professional':
            referred.plan_label_text = 'Professional'
            referred.plan_label_color = '#7c3aed'
            referred.plan_label_bg = '#ede9fe'
        elif plan == 'basic':
            referred.plan_label_text = 'Starter'
            referred.plan_label_color = '#2563eb'
            referred.plan_label_bg = '#dbeafe'
        elif plan == 'free_trial':
            referred.plan_label_text = 'Free Trial'
            referred.plan_label_color = '#f59e0b'
            referred.plan_label_bg = '#fef3c7'
        else:
            referred.plan_label_text = plan.title() if plan else '—'
            referred.plan_label_color = '#64748b'
            referred.plan_label_bg = '#f1f5f9'
            
        # status map configuration
        status = referred.status or ''
        if status == 'active':
            referred.status_text = 'Active'
            referred.status_color = '#15803d'
            referred.status_bg = '#dcfce7'
        elif status == 'pending_approval':
            referred.status_text = 'Pending Approval'
            referred.status_color = '#b45309'
            referred.status_bg = '#fef3c7'
        elif status == 'pending_payment':
            referred.status_text = 'Pending Payment'
            referred.status_color = '#1d4ed8'
            referred.status_bg = '#dbeafe'
        elif status == 'inactive':
            referred.status_text = 'Inactive'
            referred.status_color = '#94a3b8'
            referred.status_bg = '#f1f5f9'
        else:
            referred.status_text = status.title() if status else '—'
            referred.status_color = '#64748b'
            referred.status_bg = '#f1f5f9'

    context = {
        'agent': agent,
        'refCode': ref_code,
        'actualConversions': actual_conversions,
        'pendingCount': pending_count,
        'currentTier': current_tier,
        'nextTier': next_tier,
        'referralUrl': referral_url,
        'referredAgents': referred_agents,
        'allRegistered': all_registered,
        'total': total,
        'pending': pending,
        'tierLabel': tier_label,
        'nextTarget': next_target,
        'pct': pct,
        'progressLabel': progress_label,
        'nextGoalText': next_goal_text,
        'waMsg': wa_msg,
        'emailSub': email_sub,
        'emailBody': email_body,
    }

    return render(request, 'agents/referral.html', context)


def agent_public_profile(request, slug):
    from django.http import Http404
    from django.conf import settings
    from apps.agents.models import Agent, AgentProfileView, AgentReview
    import time
    
    # Try to find by slug first
    agent = Agent.objects.filter(profile__slug=slug).first()
    
    # Fallback for ID if slug not found and is numeric
    if not agent and slug.isdigit():
        agent = Agent.objects.filter(id=int(slug)).first()
        
    if not agent:
        raise Http404("Agent not found")
        
    is_owner = False
    if request.user.is_authenticated:
        is_owner = Agent.objects.filter(user=request.user, id=agent.id).exists()
        
    if not is_owner:
        try:
            session_key = f'agent_profile_viewed_{agent.id}'
            last_viewed_at = request.session.get(session_key)
            cooldown_seconds = 30 * 60
            current_time = int(time.time())
            
            if not last_viewed_at or (current_time - int(last_viewed_at)) > cooldown_seconds:
                from django.utils import timezone
                today = timezone.now().date()
                profile_view, created = AgentProfileView.objects.get_or_create(
                    agent=agent,
                    view_date=today,
                    defaults={'view_count': 1}
                )
                if not created:
                    from django.db.models import F
                    profile_view.view_count = F('view_count') + 1
                    profile_view.save()
                    
                request.session[session_key] = current_time
        except Exception as e:
            if settings.DEBUG:
                logger.warning(f"Profile tracking failed: {e}")
                
    # Fetch approved reviews
    reviews = agent.reviews.filter(is_approved=True).select_related('user').order_by('-created_at')
    
    # Find existing review for current user to populate form
    existing_review = None
    if request.user.is_authenticated and not is_owner:
        existing_review = agent.reviews.filter(user=request.user).first()
        
    profile = getattr(agent, 'profile', None)
    display_name = (profile.display_name if profile else '') or agent.fullname or 'Agent'
    agent_initial = display_name[0].upper() if display_name else 'A'
    
    import json
    social_links = {}
    if profile and profile.social_links:
        if isinstance(profile.social_links, dict):
            social_links = profile.social_links
        elif isinstance(profile.social_links, str):
            try:
                social_links = json.loads(profile.social_links)
            except ValueError:
                pass
                
    context = {
        'agent': agent,
        'profile': profile,
        'isOwnerView': is_owner,
        'reviews': reviews,
        'existingReview': existing_review,
        'reviewSlug': slug,
        'agentDisplayName': display_name,
        'agentInitial': agent_initial,
        'socialLinks': social_links,
        'performanceStats': getattr(agent, 'performanceStats', None),
        'leadPreferences': getattr(agent, 'leadPreferences', None),
    }
    return render(request, 'agents/profile_view.html', context)


from django.views.decorators.http import require_POST

@require_POST
def store_review(request, slug):
    from django.http import JsonResponse
    from apps.agents.models import Agent, AgentReview
    import re
    
    # Retrieve agent
    agent = Agent.objects.filter(profile__slug=slug).first()
    if not agent and slug.isdigit():
        agent = Agent.objects.filter(id=int(slug)).first()
        
    if not agent:
        return JsonResponse({'status': 'error', 'message': 'Agent not found'}, status=404)
        
    # Prevent agent from reviewing themselves
    if request.user.is_authenticated:
        is_owner = Agent.objects.filter(user=request.user, id=agent.id).exists()
        if is_owner:
            return JsonResponse({'status': 'error', 'message': 'You cannot review yourself'}, status=403)
            
    rating_val = request.POST.get('rating')
    review_val = request.POST.get('review')
    
    errors = {}
    if not rating_val or rating_val == '0':
        errors['rating'] = ['The rating field is required.']
    else:
        try:
            rating_val = int(rating_val)
            if rating_val < 1 or rating_val > 5:
                errors['rating'] = ['The rating must be between 1 and 5.']
        except ValueError:
            errors['rating'] = ['The rating must be an integer.']
            
    if not review_val:
        errors['review'] = ['The review field is required.']
    elif len(review_val) < 10:
        errors['review'] = ['The review must be at least 10 characters.']
    elif len(review_val) > 500:
        errors['review'] = ['The review may not be greater than 500 characters.']
        
    if not request.user.is_authenticated:
        fullname = request.POST.get('fullname')
        email = request.POST.get('email')
        mobile = request.POST.get('mobile')
        
        if not fullname:
            errors['fullname'] = ['The fullname field is required.']
        if not email:
            errors['email'] = ['The email field is required.']
        elif '@' not in email or '.' not in email:
            errors['email'] = ['The email must be a valid email address.']
        if not mobile:
            errors['mobile'] = ['The mobile field is required.']
        else:
            mobile_digits = re.sub(r'[^0-9]', '', mobile)
            if len(mobile_digits) != 10:
                errors['mobile'] = ['The mobile format is invalid. Must be 10 digits.']
    else:
        fullname = f"{request.user.first_name} {request.user.last_name}".strip() or request.user.username
        email = request.user.email
        # Try to find user's agent mobile
        user_agent = Agent.objects.filter(user=request.user).first()
        mobile = user_agent.mobile if user_agent else ""
        
    if errors:
        return JsonResponse({'status': 'error', 'errors': errors}, status=422)
        
    reviewer_email = email.lower()
    
    if request.user.is_authenticated:
        review_obj, created = AgentReview.objects.update_or_create(
            agent=agent,
            user=request.user,
            defaults={
                'reviewer_name': fullname,
                'reviewer_email': reviewer_email,
                'reviewer_mobile': mobile,
                'rating': rating_val,
                'review': review_val,
                'is_approved': True
            }
        )
    else:
        mobile_digits = re.sub(r'[^0-9]', '', mobile)
        review_obj, created = AgentReview.objects.update_or_create(
            agent=agent,
            reviewer_email=reviewer_email,
            defaults={
                'user': None,
                'reviewer_name': fullname,
                'reviewer_mobile': mobile_digits,
        'is_approved': True
            }
        )
    message = 'Review submitted successfully!' if created else 'Review updated successfully!'
    return JsonResponse({
        'status': 'success',
        'message': message
    })


@login_required(login_url='agents:agent_login')
def edit_profile(request):
    is_admin = request.user.is_staff or request.user.is_superuser
    agent_id = request.GET.get('agent_id')
    
    if is_admin and agent_id:
        agent = Agent.objects.filter(id=agent_id).first()
        is_admin_view = True
    else:
        agent = Agent.objects.filter(user=request.user).first()
        is_admin_view = False
        
    if not agent:
        if is_admin:
            messages.error(request, "Agent not found.")
            return redirect('admin:dashboard')
        else:
            messages.error(request, "Please complete your registration.")
            return redirect('agents:agent_registration')
            
    from apps.agents.models import AgentProfile
    profile, _ = AgentProfile.objects.get_or_create(agent=agent)
            
    # Load serviceable cities
    agent_cities = list(agent.serviceableCities.values_list('name', flat=True))
    
    main_cities = sorted(list(set([
        'Ahmedabad', 'Mumbai', 'Delhi', 'Bangalore', 'Hyderabad', 'Chennai', 'Kolkata', 'Pune', 'Surat', 
        'Jaipur', 'Lucknow', 'Kanpur', 'Nagpur', 'Indore', 'Thane', 'Bhopal', 'Visakhapatnam', 'Pimpri-Chinchwad', 
        'Patna', 'Vadodara', 'Ghaziabad', 'Ludhiana', 'Coimbatore', 'Agra', 'Madurai', 'Nashik', 'Vijayawada', 
        'Faridabad', 'Meerut', 'Rajkot', 'Kalyan-Dombivli', 'Vasai-Virar', 'Varanasi', 'Srinagar', 'Aurangabad', 
        'Dhanbad', 'Amritsar', 'Navi Mumbai', 'Allahabad', 'Howrah', 'Ranchi', 'Gwalior', 'Jabalpur', 
        'Jodhpur', 'Raipur', 'Chandigarh', 'Guntur', 'Guwahati', 'Solapur', 'Noida', 'Mysuru', 'Gurgaon', 
        'Bhubaneswar', 'Thiruvananthapuram', 'Dehradun', 'Jammu', 'Jamnagar', 'Ujjain', 'Jhansi', 'Kochi', 
        'Mangalore', 'Udaipur', 'Ajmer', 'Tiruppur', 'Nellore', 'Kurnool', 'Gaya', 'Hoshiarpur', 'Muzaffarpur', 
        'Vellore', 'Shimla', 'Rohtak', 'Ambala', 'Gandhinagar', 'Pondicherry', 'Siliguri', 'Raurkela', 
        'Durgapur', 'Asansol'
    ])))
    
    extra_cities = [c for c in agent_cities if c not in main_cities]
            
    import datetime
    current_year = datetime.datetime.now().year
    years_range = list(range(current_year, 1979, -1))
    months = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']
            
    context = {
        'agent': agent,
        'profile': profile,
        'isAdminView': is_admin_view,
        'base_template': 'admin/layout.html' if is_admin_view else 'base.html',
        'main_cities': main_cities,
        'agent_cities': agent_cities,
        'extra_cities': extra_cities,
        'years_range': years_range,
        'months': months,
    }
    return render(request, 'agents/edit_profile.html', context)


@login_required(login_url='agents:agent_login')
def update_profile(request):
    from django.http import JsonResponse
    from django.db import transaction
    from django.core.files.storage import default_storage
    from apps.agents.models import (
        Agent, AgentProfile, AgentPerformanceStat, AgentFamilyLicense, 
        AgentInsuranceSegment, AgentProductExpertise, AgentPortfolio, 
        AgentAchievementPhoto, AgentCareerTimeline, AgentLeadPreference, City
    )
    import re
    import os
    import time
    import uuid
    import json
    
    is_admin = request.user.is_staff or request.user.is_superuser
    agent_id = request.POST.get('agent_id')
    
    if is_admin and agent_id:
        agent = Agent.objects.filter(id=agent_id).first()
    else:
        agent = Agent.objects.filter(user=request.user).first()
        
    if not agent:
        return JsonResponse({'status': 'error', 'message': 'Agent not found'}, status=404)
        
    profile, _ = AgentProfile.objects.get_or_create(agent=agent)
    current_step = request.POST.get('current_step')
    
    # helper for step processing
    def should_process(step):
        return not current_step or str(current_step) == str(step)
        
    try:
        with transaction.atomic():
            # ── Step 1: Basic Info ──
            if should_process(1):
                full_name = request.POST.get('full_name')
                email = request.POST.get('email')
                mobile = request.POST.get('mobile')
                display_name = request.POST.get('display_name')
                whatsapp = request.POST.get('whatsapp')
                languages = request.POST.get('languages')
                address = request.POST.get('address')
                
                # Basic validation
                errors = {}
                if not full_name:
                    errors['full_name'] = ['The full name field is required.']
                if not email:
                    errors['email'] = ['The email field is required.']
                elif Agent.objects.filter(email__iexact=email).exclude(id=agent.id).exists():
                    errors['email'] = ['The email has already been taken.']
                if not mobile:
                    errors['mobile'] = ['The mobile field is required.']
                if not languages:
                    errors['languages'] = ['The languages field is required.']
                if not address:
                    errors['address'] = ['The address field is required.']
                    
                if errors:
                    return JsonResponse({'status': 'error', 'message': 'Validation failed', 'errors': errors}, status=422)
                    
                agent.fullname = full_name
                agent.email = email
                agent.mobile = mobile
                
                # User types (Optional)
                user_types = request.POST.getlist('user_types[]') or request.POST.getlist('user_types')
                if user_types:
                    agent.user_types = user_types
                    
                # Admin values
                if is_admin:
                    badge_data = request.POST.getlist('badge[]') or request.POST.getlist('badge')
                    agent.badge = ','.join(filter(None, badge_data))
                    if request.POST.get('status'):
                        agent.status = request.POST.get('status')
                        
                agent.save()
                
                profile.display_name = display_name
                profile.whatsapp = whatsapp
                profile.languages = languages
                profile.address = address
                
                # Profile Photo upload
                profile_photo = request.FILES.get('profile_photo')
                if profile_photo:
                    file_ext = os.path.splitext(profile_photo.name)[1]
                    file_name = f"app/public/profile/agent_{agent.id}_{int(time.time())}{file_ext}"
                    saved_path = default_storage.save(file_name, profile_photo)
                    profile.profile_photo_path = saved_path
                    
                profile.save()
                
            # ── Step 2: Professional Details ──
            if should_process(2):
                pan = request.POST.get('pan')
                agency_name = request.POST.get('agency_name')
                office_address = request.POST.get('office_address')
                service_pincode = request.POST.get('service_pincode')
                has_pos_license = request.POST.get('has_pos_license') == '1'
                experience_years = request.POST.get('experience_years')
                client_base = request.POST.get('client_base')
                
                # Validation
                errors = {}
                if not service_pincode:
                    errors['service_pincode'] = ['The service pincode field is required.']
                if not experience_years:
                    errors['experience_years'] = ['The experience field is required.']
                if not client_base:
                    errors['client_base'] = ['The client base field is required.']
                    
                serviceable_cities_data = request.POST.getlist('serviceable_cities[]') or request.POST.getlist('serviceable_cities')
                if not serviceable_cities_data:
                    errors['serviceable_cities'] = ['The serviceable cities field is required.']
                    
                if errors:
                    return JsonResponse({'status': 'error', 'message': 'Validation failed', 'errors': errors}, status=422)
                    
                profile.pan_number = pan
                profile.agency_name = agency_name
                profile.office_address = office_address
                profile.service_pincode = service_pincode
                profile.has_pos_license = has_pos_license
                
                if is_admin and request.POST.get('license_number'):
                    profile.license_number = request.POST.get('license_number')
                    
                profile.save()
                
                agent.experience_range = experience_years
                agent.client_base = client_base
                
                insurance_companies = request.POST.getlist('insurance_companies[]') or request.POST.getlist('insurance_companies')
                if insurance_companies:
                    agent.insurance_companies = insurance_companies
                    
                agent.save()
                
                # Family Licenses
                agent.familyLicenses.all().delete()
                family_indices = set()
                for key in request.POST.keys():
                    match = re.match(r'family_members\[(\d+)\]\[name\]', key)
                    if match:
                        family_indices.add(int(match.group(1)))
                        
                for idx in sorted(family_indices):
                    name = request.POST.get(f'family_members[{idx}][name]', '').strip()
                    relationship = request.POST.get(f'family_members[{idx}][relationship]', '').strip()
                    license_num = request.POST.get(f'family_members[{idx}][license]', '').strip()
                    if name:
                        AgentFamilyLicense.objects.create(
                            agent=agent,
                            full_name=name,
                            relationship=relationship,
                            license_number=license_num
                        )
                        
                # Performance Stats
                claims_processed = int(request.POST.get('claims_processed') or 0)
                claims_settled = int(request.POST.get('claims_settled') or 0)
                claims_amount = float(request.POST.get('claims_amount') or 0.0)
                response_time = int(request.POST.get('response_time') or 2)
                success_rate = round((claims_settled / claims_processed) * 100, 2) if claims_processed > 0 else 0.0
                
                AgentPerformanceStat.objects.update_or_create(
                    agent=agent,
                    defaults={
                        'claims_processed': claims_processed,
                        'claims_settled': claims_settled,
                        'claims_amount': claims_amount,
                        'success_rate': success_rate,
                        'response_time': response_time
                    }
                )
                
                # Serviceable Cities
                city_ids = []
                for city_name in serviceable_cities_data:
                    city, _ = City.objects.get_or_create(
                        name=city_name,
                        defaults={
                            'slug': re.sub(r'[^a-zA-Z0-9]', '-', city_name).lower(),
                            'is_active': True
                        }
                    )
                    city_ids.append(city.id)
                agent.serviceableCities.set(city_ids)
                
            # ── Step 3: Insurance Segments ──
            if should_process(3):
                segments = request.POST.getlist('segments[]') or request.POST.getlist('segments')
                
                agent.insuranceSegments.all().delete()
                for segment_type in segments:
                    AgentInsuranceSegment.objects.create(agent=agent, segment_type=segment_type)
                    
                # Product expertise ratings
                agent.productExpertise.all().delete()
                for key, value in request.POST.items():
                    match = re.match(r'expertise\[([^\]]+)\]\[([^\]]+)\]', key)
                    if match:
                        segment = match.group(1)
                        product = match.group(2)
                        try:
                            level = int(value)
                            if level > 0:
                                is_custom = request.POST.get(f"custom_products[{segment}][{product}]") == '1'
                                AgentProductExpertise.objects.create(
                                    agent=agent,
                                    segment_type=segment,
                                    product_name=product,
                                    expertise_level=level,
                                    is_custom=is_custom
                                )
                        except ValueError:
                            pass
                            
            # ── Step 4: Portfolios ──
            if should_process(4):
                # Sync segments again if sent
                segments = request.POST.getlist('segments[]') or request.POST.getlist('segments')
                if segments:
                    agent.insuranceSegments.all().delete()
                    for segment_type in segments:
                        AgentInsuranceSegment.objects.create(agent=agent, segment_type=segment_type)
                        
                portfolio_data = {}
                for key in request.POST.keys():
                    match = re.match(r'portfolio\[([^\]]+)\]\[([^\]]+)\]', key)
                    if match:
                        segment = match.group(1)
                        field = match.group(2)
                        if segment not in portfolio_data:
                            portfolio_data[segment] = {}
                        if field != 'companies_extra':
                            portfolio_data[segment][field] = request.POST.get(key)
                            
                for key in request.POST.keys():
                    match = re.match(r'portfolio\[([^\]]+)\]\[companies_extra\]\[(\d+)\]\[(name|percent)\]', key)
                    if match:
                        segment = match.group(1)
                        idx = int(match.group(2))
                        field = match.group(3)
                        
                        if segment not in portfolio_data:
                            portfolio_data[segment] = {}
                        if 'companies_extra' not in portfolio_data[segment]:
                            portfolio_data[segment]['companies_extra'] = {}
                        if idx not in portfolio_data[segment]['companies_extra']:
                            portfolio_data[segment]['companies_extra'][idx] = {}
                            
                        portfolio_data[segment]['companies_extra'][idx][field] = request.POST.get(key)
                        
                agent.portfolios.all().delete()
                for segment_type, data in portfolio_data.items():
                    primary_name = (data.get('primary_company') or '').strip()
                    primary_percent = (data.get('primary_percent') or '').strip()
                    secondary_name = (data.get('secondary_company') or '').strip()
                    secondary_percent = (data.get('secondary_percent') or '').strip()
                    other_companies = (data.get('other_companies') or '').strip()
                    
                    if primary_name:
                        # Construct companies extra list
                        extra_list = []
                        if 'companies_extra' in data:
                            for idx, comp in data['companies_extra'].items():
                                cname = (comp.get('name') or '').strip()
                                cpercent = (comp.get('percent') or '').strip()
                                if cname:
                                    extra_list.append({'name': cname, 'percent': cpercent})
                                    
                        all_companies = [{'name': primary_name, 'percent': primary_percent}]
                        if secondary_name:
                            all_companies.append({'name': secondary_name, 'percent': secondary_percent})
                        all_companies.extend(extra_list)
                        
                        AgentPortfolio.objects.create(
                            agent=agent,
                            segment_type=segment_type,
                            primary_companies={
                                'name': primary_name,
                                'percentage': primary_percent
                            },
                            secondary_companies={
                                'name': secondary_name,
                                'percentage': secondary_percent,
                                'others': other_companies,
                                'companies': all_companies
                            }
                        )
                        
            # ── Step 5: Additional Info ──
            if should_process(5):
                website = request.POST.get('website')
                google_business = request.POST.get('google_business')
                linkedin = request.POST.get('linkedin_url')
                instagram = request.POST.get('instagram_url')
                facebook = request.POST.get('facebook_url')
                youtube = request.POST.get('youtube_url')
                career_highlights = request.POST.get('career_highlights')
                
                # Check photos limits
                remove_photo_ids = request.POST.getlist('remove_photos[]') or request.POST.getlist('remove_photos')
                remove_photo_ids = [int(i) for i in remove_photo_ids if i.isdigit()]
                
                plan_text = str(agent.activeSubscription.selected_plan if agent.activeSubscription else '').lower()
                max_achievement_photos = 10 if 'professional' in plan_text else 5
                
                existing_photos_count = agent.achievementPhotos.count()
                removed_count = len(remove_photo_ids)
                new_photos = request.FILES.getlist('achievement_photos')
                new_photos_count = len(new_photos)
                
                projected_total = max(0, existing_photos_count - removed_count) + new_photos_count
                if projected_total > max_achievement_photos:
                    return JsonResponse({
                        'status': 'error',
                        'message': f"Achievement photo limit exceeded. Your current plan allows up to {max_achievement_photos} photos.",
                        'errors': {
                            'achievement_photos': [f"You can upload up to {max_achievement_photos} achievement photos."]
                        }
                    }, status=422)
                    
                profile.website_url = website
                profile.social_links = {
                    'google_business': google_business,
                    'linkedin': linkedin,
                    'instagram': instagram,
                    'facebook': facebook,
                    'youtube': youtube
                }
                profile.career_highlights = career_highlights
                profile.save()
                
                # Process photo removal
                if remove_photo_ids:
                    agent.achievementPhotos.filter(id__in=remove_photo_ids).delete()
                    
                # Process photo uploads
                for photo_file in new_photos:
                    file_ext = os.path.splitext(photo_file.name)[1]
                    file_name = f"app/public/achievement/achievement_{agent.id}_{int(time.time())}_{uuid.uuid4().hex[:6]}{file_ext}"
                    saved_path = default_storage.save(file_name, photo_file)
                    AgentAchievementPhoto.objects.create(agent=agent, photo_path=saved_path)
                    
                # Recreate career timelines
                agent.careerTimelines.all().delete()
                timeline_indices = set()
                for key in request.POST.keys():
                    match = re.match(r'career_timelines\[(\d+)\]\[event_text\]', key)
                    if match:
                        timeline_indices.add(int(match.group(1)))
                        
                for idx in sorted(timeline_indices):
                    event_type = request.POST.get(f'career_timelines[{idx}][type]', 'Career Event').strip()
                    event_text = request.POST.get(f'career_timelines[{idx}][event_text]', '').strip()
                    month = request.POST.get(f'career_timelines[{idx}][month]', '').strip()
                    year = request.POST.get(f'career_timelines[{idx}][year]', '').strip()
                    if event_text and year:
                        AgentCareerTimeline.objects.create(
                            agent=agent,
                            event_type=event_type,
                            event_text=event_text,
                            month=month,
                            year=year
                        )
                        
            # ── Step 6: Lead Preferences ──
            if should_process(6):
                lead_types = request.POST.getlist('lead_types[]') or request.POST.getlist('lead_types')
                portfolio_charging = request.POST.get('portfolio_charging', 'free')
                
                portfolio_fee = 0.0
                if portfolio_charging == 'conditional':
                    portfolio_fee = float(request.POST.get('portfolio_fee_conditional') or 0.0)
                elif portfolio_charging == 'paid':
                    portfolio_fee = float(request.POST.get('portfolio_fee_paid') or 0.0)
                    
                claims_charging = request.POST.get('claims_charging', 'free')
                claims_fee_amount = float(request.POST.get('claims_fee_amount') or 0.0) if claims_charging == 'fee' else 0.0
                claims_percent = float(request.POST.get('claims_percent') or 0.0) if claims_charging == 'percentage' else 0.0
                
                AgentLeadPreference.objects.update_or_create(
                    agent=agent,
                    defaults={
                        'leads_new_business': 'new_business' in lead_types,
                        'leads_portfolio_analysis': 'portfolio_analysis' in lead_types,
                        'portfolio_charging': portfolio_charging,
                        'portfolio_fee': portfolio_fee,
                        'leads_claims_support': 'claims_support' in lead_types,
                        'claims_charging': claims_charging,
                        'claims_fee_amount': claims_fee_amount,
                        'claims_percent': claims_percent
                    }
                )
                
            # ── Step 7: Final Submission ──
            if not current_step or str(current_step) == '7':
                if not is_admin:
                    agent.status = 'pending_approval'
                    agent.save()
                    
            return JsonResponse({
                'status': 'success',
                'message': 'Profile saved successfully' if not current_step else 'Progress saved',
                'redirect': None if current_step and str(current_step) != '7' else (
                    '/admin/agents/manage/' + str(agent.id) + '/' if is_admin else '/agent/dashboard/'
                ),
                'profile_photo_url': profile.profile_photo_url
            })
            
    except Exception as e:
        import traceback
        logger.error(f"Profile update failed: {e}\n{traceback.format_exc()}")
        return JsonResponse({
            'status': 'error',
            'message': f"An error occurred while updating your profile: {str(e)}"
        }, status=500)


@require_POST
def agent_push_token(request):
    """
    Handle POST request to store/update the FCM push token for the authenticated agent.
    """
    if not request.user.is_authenticated:
        return JsonResponse({'message': 'Unauthenticated.'}, status=401)

    agent = Agent.objects.filter(user=request.user).first()
    if not agent:
        return JsonResponse({'message': 'Agent not found.'}, status=403)

    try:
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            data = request.POST

        token = data.get('token', '').strip()
        platform = data.get('platform', '').strip() or None

        if not token:
            return JsonResponse({'message': 'Token is required.'}, status=422)

        AgentDeviceToken.objects.update_or_create(
            token=token,
            defaults={
                'agent': agent,
                'platform': platform,
                'last_seen_at': timezone.now()
            }
        )
        return JsonResponse({'message': 'Token saved.'})
    except Exception as e:
        logger.error(f"FCM token store failed: {e}")
        return JsonResponse({'message': 'Failed to save token.'}, status=500)


def referral_info(request):
    """
    Agent referral info API (for dashboard)
    """
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Unauthenticated.'}, status=401)

    agent = Agent.objects.filter(user=request.user).first()
    if not agent:
        return JsonResponse({'error': 'Agent Profile Not found'}, status=404)

    try:
        ref_code = ReferralCode.objects.filter(agent=agent).first()
        if not ref_code:
            ref_code = ReferralCode.generateForAgent(agent)

        # Auto self-heal total_referrals from actual converted usages
        actual_conversions = ReferralUsage.objects.filter(
            referral_code=ref_code,
            status='converted'
        ).count()

        if ref_code.total_referrals != actual_conversions:
            ref_code.total_referrals = actual_conversions
            ref_code.save()

        next_tier = ref_code.nextTier()

        # Calculate pending referrals: registered with this code but not converted yet
        total_registered_agents = list(Agent.objects.filter(referred_by_code=ref_code.code).values_list('id', flat=True))
        converted_agent_ids = list(ReferralUsage.objects.filter(
            referral_code=ref_code,
            status='converted'
        ).values_list('referred_agent_id', flat=True))

        pending_referrals = len(set(total_registered_agents) - set(converted_agent_ids))

        # Build absolute referral URL in Django
        from django.urls import reverse
        try:
            referral_url = request.build_absolute_uri(reverse('agents:referral_join', args=[ref_code.code]))
        except Exception:
            referral_url = f"{request.scheme}://{request.get_host()}/join/{ref_code.code}/"

        return JsonResponse({
            'code': ref_code.code,
            'total_referrals': actual_conversions,
            'pending_referrals': pending_referrals,
            'current_tier': ref_code.currentTier(),
            'next_tier': next_tier,
            'next_target': next_tier['min'] if next_tier else None,
            'reward_claimed': bool(ref_code.reward_claimed),
            'referral_url': referral_url,
        })
    except Exception as e:
        logger.error(f"Referral info API failed: {e}")
        return JsonResponse({'error': f"Server Error: {str(e)}"}, status=500)


@require_POST
def agent_upgrade_plan(request):
    """
    Handle plan upgrade checkout for logged-in agents (creates Razorpay order).
    """
    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'message': 'Unauthenticated.'}, status=401)

    agent = Agent.objects.filter(user=request.user).first()
    if not agent:
        return JsonResponse({'success': False, 'message': 'Agent not found.'}, status=403)

    try:
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            data = request.POST

        plan_type = data.get('plan_type')
        if plan_type not in ['basic', 'professional']:
            return JsonResponse({'success': False, 'message': 'Invalid plan selection.'}, status=400)

        # Re-compute prices
        admin_default = SiteSetting.get_value('trial_upgrade_discount', 20)
        agent_specific = agent.upgrade_discount_percent or 0
        
        ref_code = ReferralCode.objects.filter(agent=agent).first()
        referral_discount = 0
        if ref_code:
            tier = ref_code.currentTier()
            if tier and 'discount' in tier:
                referral_discount = tier['discount']

        discount_pct = max(int(admin_default), int(agent_specific), int(referral_discount))

        pricing_config = SiteSetting.get_value('pricing_config', {
            'starter': {'name': "Starter's Plan", 'full_price': 2359},
            'professional': {'name': "Professional's Plan", 'full_price': 8258},
        })

        starter_full = float(pricing_config.get('starter', {}).get('full_price', 2359))
        prof_full = float(pricing_config.get('professional', {}).get('full_price', 8258))

        discount_factor = (100 - discount_pct) / 100
        starter_final = round(starter_full * discount_factor)
        starter_base = round(starter_final / 1.18, 0)
        starter_disc = starter_base + round(starter_base * 0.18, 0)

        prof_final = round(prof_full * discount_factor)
        if agent.referral_reward_type == 'pro_plan_1rs':
            prof_final = 1
            discount_pct = 99.99

        prof_base = round(prof_final / 1.18, 0)
        if agent.referral_reward_type == 'pro_plan_1rs':
            prof_disc = 1.00
        else:
            prof_disc = prof_base + round(prof_base * 0.18, 0)

        if plan_type == 'basic':
            total_amount = starter_disc
            plan_amount = starter_base
            plan_name = pricing_config.get('starter', {}).get('name', "Starter's Plan")
        else:
            total_amount = prof_disc
            plan_amount = prof_base
            plan_name = pricing_config.get('professional', {}).get('name', "Professional's Plan")

        # Check duplicate paid subscription
        already_paid = AgentSubscription.objects.filter(
            agent=agent,
            payment_status='completed',
            selected_plan=plan_name
        ).first()

        if already_paid:
            return JsonResponse({
                'success': True,
                'already_completed': True,
                'agent_id': agent.id
            })

        # Initialize Razorpay Client and create Order
        import razorpay
        import time
        from django.conf import settings
        
        razorpay_order_id = None
        amount_paise = int(round(total_amount * 100))
        is_test_key = bool(settings.RAZORPAY_KEY and settings.RAZORPAY_KEY.startswith('rzp_test'))
        
        if settings.RAZORPAY_KEY and settings.RAZORPAY_SECRET and amount_paise > 0:
            try:
                client = razorpay.Client(auth=(settings.RAZORPAY_KEY, settings.RAZORPAY_SECRET))
                order_data = {
                    'amount': amount_paise,
                    'currency': 'INR',
                    'receipt': f'agent_upgrade_{agent.pk}_{int(time.time())}',
                    'payment_capture': 1
                }
                order = client.order.create(order_data)
                razorpay_order_id = order.get('id')
            except Exception as e:
                logger.error(f"Razorpay Upgrade Order Creation Failed: {str(e)}")
                return JsonResponse({'success': False, 'message': 'Payment service is offline.'}, status=500)

        # Update or create AgentSubscription
        subscription, created = AgentSubscription.objects.update_or_create(
            agent=agent,
            razorpay_order_id=razorpay_order_id,
            defaults={
                'selected_plan': plan_name or plan_type,
                'promo_code': None,
                'registration_amount': total_amount,
                'payment_status': 'pending',
                'status': 'inactive',
            }
        )

        agent.status = 'pending_payment'
        agent.save()

        # If test mode & no key OR 0 amount, complete instantly
        if (not settings.RAZORPAY_KEY or not settings.RAZORPAY_SECRET or amount_paise == 0) and is_test_key:
            subscription.payment_status = 'completed'
            subscription.status = 'active'
            subscription.starts_at = timezone.now()
            subscription.expires_at = timezone.now() + timezone.timedelta(days=365)
            subscription.save()
            
            agent.status = 'active'
            agent.plan_type = plan_type
            agent.save()

            # Credit referral
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
                    logger.warning(f"Referral credit during plan upgrade failed: {ref_err}")
            
            try:
                ReferralCode.generateForAgent(agent)
            except Exception:
                pass

            return JsonResponse({
                'success': True,
                'already_completed': True,
                'agent_id': agent.id
            })

        return JsonResponse({
            'success': True,
            'order_id': razorpay_order_id,
            'amount': amount_paise,
            'key': settings.RAZORPAY_KEY,
            'agent_id': agent.id,
            'name': agent.fullname,
            'email': agent.email,
            'plan_amount': plan_amount,
            'total_amount': total_amount,
            'test_payment': is_test_key
        })

    except Exception as e:
        logger.error(f"Plan upgrade request failed: {e}")
        return JsonResponse({'success': False, 'message': 'An unexpected error occurred.'}, status=500)


@csrf_exempt
@require_POST
def agent_capture_lead(request):
    try:
        agent_id = request.POST.get('agent_id')
        interaction_type = request.POST.get('interaction_type')
        service_type = request.POST.get('service_type')
        insurance_type = request.POST.get('insurance_type')
        insurance_company = request.POST.get('insurance_company')
        source_page = request.POST.get('source_page')

        if not agent_id or not interaction_type:
            return JsonResponse({'success': False, 'message': 'Missing required fields: agent_id and interaction_type.'}, status=400)

        allowed_types = ['call', 'whatsapp', 'linkedin', 'facebook', 'instagram', 'youtube', 'google_business']
        if interaction_type not in allowed_types:
            return JsonResponse({'success': False, 'message': 'Invalid interaction type.'}, status=400)

        # Get client IP
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            client_ip = x_forwarded_for.split(',')[0].strip()
        else:
            client_ip = request.META.get('REMOTE_ADDR')

        # 1. Explicit IP Block Check
        from apps.agents.models import BlockedIp
        if BlockedIp.objects.filter(ip_address=client_ip).exists():
            return JsonResponse({
                'success': False,
                'url': '#',
                'message': 'Access denied. Your IP address has been blocked due to suspicious activity.'
            })

        # Check Agent exists
        agent = Agent.objects.filter(id=agent_id).first()
        if not agent:
            return JsonResponse({'success': False, 'message': 'Agent not found.'}, status=404)

        # 2. Dynamic Rate Limiting (Unique Agents per IP)
        allowed_unique_leads = int(SiteSetting.get_value('rate_limit_clicks', 10))
        timeframe_hours = int(SiteSetting.get_value('rate_limit_timeframe', 2))

        time_threshold = timezone.now() - timezone.timedelta(hours=timeframe_hours)

        unique_interactions_count = AgentLead.objects.filter(
            ip_address=client_ip,
            created_at__gte=time_threshold
        ).order_by().values('agent_id').distinct().count()

        if unique_interactions_count >= allowed_unique_leads:
            is_same_interaction_allowed = AgentLead.objects.filter(
                ip_address=client_ip,
                agent_id=agent_id,
                interaction_type=interaction_type,
                created_at__gte=time_threshold
            ).exists()

            if not is_same_interaction_allowed:
                return JsonResponse({
                    'success': False,
                    'url': '#',
                    'message': f"Rate limit exceeded: You can only contact {allowed_unique_leads} different agents every {timeframe_hours} hours. Please try again later."
                })

        # Resolve customer details
        lead_user = request.session.get('quick_lead_user', {})
        customer_name = lead_user.get('fullname') or request.POST.get('fullname')
        customer_email = lead_user.get('email') or request.POST.get('email')
        customer_mobile = lead_user.get('mobile') or request.POST.get('mobile')
        customer_pincode = lead_user.get('pincode') or request.POST.get('pincode')

        if (not customer_name or not customer_email) and request.user.is_authenticated:
            user = request.user
            customer_name = customer_name or getattr(user, 'fullname', '') or user.get_full_name() or user.username
            customer_email = customer_email or user.email
            customer_mobile = customer_mobile or getattr(getattr(user, 'client', None), 'mobile', None)
            customer_pincode = customer_pincode or getattr(getattr(user, 'client', None), 'pincode', None)

        enquiry_parts = [val for val in [service_type, insurance_type, insurance_company] if val]
        enquiry_requirements = ' | '.join(enquiry_parts) if enquiry_parts else None

        # Secure URL Calculation
        from apps.agents.models import AgentProfile
        profile = AgentProfile.objects.filter(agent=agent).first()
        url = '#'

        if interaction_type == 'whatsapp':
            whatsapp_source = ''
            if profile and profile.whatsapp:
                whatsapp_source = str(profile.whatsapp)
            elif agent.mobile:
                whatsapp_source = str(agent.mobile)

            import re
            whatsapp_digits = re.sub(r'[^0-9]', '', whatsapp_source)
            if len(whatsapp_digits) == 10:
                whatsapp_digits = '91' + whatsapp_digits
            url = f'https://wa.me/{whatsapp_digits}' if whatsapp_digits else '#'

        elif interaction_type == 'call':
            url = f'tel:{agent.mobile}' if agent.mobile else '#'

        elif interaction_type in ['linkedin', 'facebook', 'instagram', 'youtube', 'google_business']:
            social_links = {}
            if profile and profile.social_links:
                if isinstance(profile.social_links, dict):
                    social_links = profile.social_links
                elif isinstance(profile.social_links, str):
                    try:
                        social_links = json.loads(profile.social_links)
                    except ValueError:
                        pass
            url = social_links.get(interaction_type) or '#'

        # Deduplication (1 hour timeframe)
        one_hour_ago = timezone.now() - timezone.timedelta(hours=1)
        existing_lead_query = AgentLead.objects.filter(
            agent_id=agent_id,
            interaction_type=interaction_type,
            created_at__gte=one_hour_ago
        )

        has_identifier = False
        if customer_mobile:
            existing_lead_query = existing_lead_query.filter(customer_mobile=customer_mobile)
            has_identifier = True
        elif customer_email:
            existing_lead_query = existing_lead_query.filter(customer_email=customer_email)
            has_identifier = True

        if has_identifier:
            existing_lead = existing_lead_query.first()
            if existing_lead:
                return JsonResponse({
                    'success': True,
                    'duplicate': True,
                    'url': url
                })

        # Create Lead
        lead = AgentLead.objects.create(
            agent=agent,
            customer_name=customer_name,
            customer_email=customer_email,
            customer_mobile=customer_mobile,
            customer_pincode=customer_pincode,
            interaction_type=interaction_type,
            lead_status='new',
            service_type=service_type,
            insurance_type=insurance_type,
            insurance_company=insurance_company,
            enquiry_requirements=enquiry_requirements,
            source_page=source_page or 'find-agents',
            ip_address=client_ip,
        )

        # Retrieve device tokens for the agent and dispatch FCM pushes via FcmService
        tokens = list(AgentDeviceToken.objects.filter(agent_id=agent_id).values_list('token', flat=True))
        tokens = [t for t in tokens if t]

        if tokens:
            title = 'New Lead Assigned'
            lead_name = customer_name or 'A customer'
            body = f"{lead_name} contacted you via {interaction_type}."

            try:
                from apps.agents.services.fcm import FcmService
                fcm_service = FcmService()
                import threading
                thread = threading.Thread(
                    target=fcm_service.send_to_tokens,
                    args=(tokens, title, body, {
                        'url': '/agent/dashboard',
                        'lead_id': str(lead.id),
                    })
                )
                thread.daemon = True
                thread.start()
            except Exception as fcm_err:
                logger.error(f"FCM thread dispatch failed: {fcm_err}")

        return JsonResponse({
            'success': True,
            'message': 'Lead captured successfully.',
            'url': url
        })

    except Exception as e:
        logger.exception(f"Lead capture failed: {e}")
        return JsonResponse({'success': False, 'message': 'An unexpected error occurred.'}, status=500)


def agent_og_image(request, agent_id):
    import os
    from django.core.cache import cache
    from django.http import HttpResponse, Http404
    from PIL import Image, ImageDraw, ImageFont
    import io
    import requests
    from django.conf import settings

    try:
        agent = Agent.objects.get(id=agent_id)
    except Agent.DoesNotExist:
        raise Http404("Agent not found")

    cache_key = f'og_image_agent_photo_fit_{agent_id}'
    nocache = request.GET.get('nocache') == '1'

    if not nocache:
        cached_image = cache.get(cache_key)
        if cached_image:
            response = HttpResponse(cached_image, content_type='image/jpeg')
            response['Cache-Control'] = 'public, max-age=86400'
            return response

    # Recreate image
    try:
        width = 800
        height = 800
        canvas = None
        photo_loaded = False

        from apps.agents.models import AgentProfile
        profile = AgentProfile.objects.filter(agent=agent).first()

        if profile and profile.profile_photo_path:
            raw_path = profile.profile_photo_path
            if '?' in raw_path:
                raw_path = raw_path.split('?')[0]

            if raw_path.startswith(('http://', 'https://')):
                try:
                    res = requests.get(raw_path, timeout=10, verify=False)
                    if res.status_code == 200:
                        src_image = Image.open(io.BytesIO(res.content))
                        photo_loaded = True
                except Exception as e:
                    logger.warning(f"Failed to fetch profile image from URL {raw_path}: {e}")
            else:
                normalized_path = raw_path.replace('\\', '/').lstrip('/')
                possible_paths = [
                    os.path.join(settings.MEDIA_ROOT, normalized_path)
                ]

                cleaned_path = normalized_path
                for prefix in ['app/public/', 'public/storage/', 'public/', 'storage/']:
                    if cleaned_path.startswith(prefix):
                        cleaned_path = cleaned_path[len(prefix):]
                        break

                possible_paths.append(os.path.join(settings.MEDIA_ROOT, cleaned_path))
                possible_paths.append(os.path.join(settings.BASE_DIR, 'media', cleaned_path))

                laravel_storage_path = os.path.abspath(os.path.join(settings.BASE_DIR, '..', 'storage', 'app', 'public', cleaned_path))
                possible_paths.append(laravel_storage_path)

                laravel_public_storage = os.path.abspath(os.path.join(settings.BASE_DIR, '..', 'public', 'storage', cleaned_path))
                possible_paths.append(laravel_public_storage)

                src_image = None
                for path in possible_paths:
                    if os.path.exists(path) and os.path.isfile(path):
                        try:
                            src_image = Image.open(path)
                            photo_loaded = True
                            break
                        except Exception as e:
                            logger.warning(f"Failed to open image at {path}: {e}")

            if photo_loaded and src_image:
                if src_image.mode not in ('RGB', 'RGBA'):
                    src_image = src_image.convert('RGB')

                src_w, src_h = src_image.size
                src_ratio = src_w / src_h
                target_ratio = 1.0

                if src_ratio > target_ratio:
                    dst_w = 800
                    dst_h = int(800 / src_ratio)
                    dst_x = 0
                    dst_y = int((800 - dst_h) / 2)
                else:
                    dst_w = int(800 * src_ratio)
                    dst_h = 800
                    dst_x = int((800 - dst_w) / 2)
                    dst_y = 0

                src_resized = src_image.resize((dst_w, dst_h), Image.Resampling.LANCZOS)
                canvas = Image.new('RGB', (800, 800), (255, 255, 255))
                if src_resized.mode == 'RGBA':
                    canvas.paste(src_resized, (dst_x, dst_y), mask=src_resized.split()[3])
                else:
                    canvas.paste(src_resized, (dst_x, dst_y))

        if not photo_loaded:
            canvas = Image.new('RGB', (800, 800), (226, 232, 240))
            draw = ImageDraw.Draw(canvas)

            name = agent.fullname or 'A'
            initial = name[0].upper() if name else 'A'

            font = None
            font_paths = [
                os.path.join(settings.BASE_DIR, 'static', 'fonts', 'Roboto-Bold.ttf'),
                os.path.join(settings.BASE_DIR, '..', 'public', 'fonts', 'Roboto-Bold.ttf'),
                "Roboto-Bold.ttf",
                "arial.ttf",
                "Arial.ttf",
                "msyh.ttc",
                "msgothic.ttc"
            ]
            windows_fonts_dir = r"C:\Windows\Fonts"
            if os.path.exists(windows_fonts_dir):
                font_paths.append(os.path.join(windows_fonts_dir, "arialbd.ttf"))
                font_paths.append(os.path.join(windows_fonts_dir, "Arial.ttf"))
                font_paths.append(os.path.join(windows_fonts_dir, "cambriab.ttf"))

            for fp in font_paths:
                try:
                    font = ImageFont.truetype(fp, size=400)
                    break
                except Exception:
                    continue

            if font is None:
                font = ImageFont.load_default()

            text_color = (100, 116, 139)
            try:
                bbox = draw.textbbox((0, 0), initial, font=font)
                text_w = bbox[2] - bbox[0]
                text_h = bbox[3] - bbox[1]
                x = (800 - text_w) / 2 - bbox[0]
                y = (800 - text_h) / 2 - bbox[1]
                draw.text((x, y), initial, font=font, fill=text_color)
            except AttributeError:
                text_w, text_h = draw.textsize(initial, font=font)
                x = (800 - text_w) / 2
                y = (800 - text_h) / 2
                draw.text((x, y), initial, font=font, fill=text_color)

        # Save to buffer
        buffer = io.BytesIO()
        canvas.save(buffer, format='JPEG', quality=90)
        encoded_image = buffer.getvalue()

        cache.set(cache_key, encoded_image, 86400)

        response = HttpResponse(encoded_image, content_type='image/jpeg')
        response['Cache-Control'] = 'public, max-age=86400'
        return response

    except Exception as e:
        logger.exception(f"OG Image Generation error: {e}")
        fallback_canvas = Image.new('RGB', (800, 800), (15, 58, 102))
        buf = io.BytesIO()
        fallback_canvas.save(buf, format='JPEG', quality=50)
        fallback_data = buf.getvalue()
        response = HttpResponse(fallback_data, content_type='image/jpeg')
        response['Cache-Control'] = 'no-store'
        return response

