from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST
import re
import logging
import json
import requests as http_requests
from apps.home.models.site_setting import SiteSetting
from apps.home.models.faq import Faq
from apps.home.models.homepage import (
    HomePageSettings, HeroTrustBadge, HeroStatistic, HeroProductTile,
    HeroSlide, DidYouKnowSlide, QuickPickItem, WhyChooseCard, HowItWorksStep
)
from django.contrib.staticfiles.storage import staticfiles_storage


def favicon(request):
    url = SiteSetting.get_value('site_favicon', '')
    if url:
        return redirect(url)
    return redirect(staticfiles_storage.url('favicon.ico'))
from apps.admin_panel.models.contact_submission import ContactSubmission
from apps.agents.models import Agent, AgentPortfolio, AgentReview, City
from apps.home.models import Pincode, PincodeCache
from apps.home.services.distance import DistanceService
from apps.home.services.geocoding import GeocodingService
from django.db.models import Avg, Q
from django.db.models.expressions import RawSQL
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.core.cache import cache

logger = logging.getLogger(__name__)


def about(request):
    about_content = SiteSetting.get_value('about_page_content', {
        'banner_title': 'About Us',
        'banner_subtitle': 'Connecting you with trusted insurance agents in your neighborhood',
        'who_we_are': 'PadosiAgent is a digital-first platform built to simplify how people connect with trusted insurance professionals in their locality.',
        'why_we_exist': 'The insurance ecosystem often faces three common challenges.',
        'what_we_do': 'We provide a platform where customers can discover agents based on location and service segments.',
        'vision': "To build India's most trusted hyperlocal insurance discovery and service platform.",
        'mission': 'Digitally empower insurance agents. Promote transparency and accountability.',
        'commitment': 'PadosiAgent does not replace insurers, brokers, or regulatory authorities.',
    })
    return render(request, 'public/about.html', {'about': about_content})


def terms(request):
    return render(request, 'public/terms.html')


def privacy(request):
    return render(request, 'public/privacy.html')


def faq(request):
    faq_content = SiteSetting.get_value('faq_page_content', {
        'title': "Got Questions? I've Got Your Answers",
        'subtitle': 'Everything you need to know before finding your PadosiAgent',
    })

    faqs = list(Faq.objects.filter(is_active=True).order_by('sort_order', 'id'))
    half = -(-len(faqs) // 2)  # ceiling division — same as Laravel's ceil($faqs->count() / 2)
    faqs_left  = faqs[:half]
    faqs_right = faqs[half:]

    return render(request, 'public/faq.html', {
        'faq_content': faq_content,
        'faqs_left':   faqs_left,
        'faqs_right':  faqs_right,
    })


def contact(request):
    """Public Contact page — renders banner + contact form."""
    contact_content = SiteSetting.get_value('contact_page_content', {
        'banner_title':    'Contact Us',
        'section_title':   'Secure Your Family Future With us.',
        'section_subtitle': "Have questions or need assistance? Reach out to us today for expert guidance on securing your family's future.",
    })
    return render(request, 'public/contact.html', {'contact': contact_content})


@require_POST
def contact_submit(request):
    """
    AJAX contact form handler — mirrors Laravel's ContactController.store().
    Validates input, saves to contact_submissions table, returns JSON.
    """
    logger.info('CONTACT FORM SUBMISSION — received data: %s', request.POST.dict())

    try:
        name    = request.POST.get('name', '').strip()
        mobile  = request.POST.get('mobile', '').strip()
        email   = request.POST.get('email', '').strip()
        company = request.POST.get('company', '').strip()
        subject = request.POST.get('subject', '').strip()
        message = request.POST.get('message', '').strip()

        # Validation
        errors = {}
        if len(name) < 2 or len(name) > 100:
            errors['name'] = ['Full name must be between 2 and 100 characters.']
        if not re.fullmatch(r'[0-9]{10}', mobile):
            errors['mobile'] = ['Please enter a valid 10-digit mobile number.']
        if not email or '@' not in email or len(email) > 100:
            errors['email'] = ['Please enter a valid email address.']
        if len(subject) < 5 or len(subject) > 100:
            errors['subject'] = ['Subject must be between 5 and 100 characters.']
        if len(message) < 10 or len(message) > 1000:
            errors['message'] = ['Message must be between 10 and 1000 characters.']

        if errors:
            return JsonResponse({
                'success': False,
                'message': 'Please fix the validation errors below.',
                'errors':  errors,
            }, status=422)

        # Save to DB
        submission = ContactSubmission.objects.create(
            name=name,
            mobile=mobile,
            email=email,
            company=company or None,
            subject=subject,
            message=message,
            status='pending',
        )
        logger.info('CONTACT FORM SUBMISSION — saved #%s ref=%s', submission.id, submission.reference_id)

        return JsonResponse({
            'success': True,
            'message': 'Thank you! Your message has been sent successfully. We will get back to you soon.',
        }, status=200)

    except Exception as exc:
        logger.error('CONTACT FORM SUBMISSION — Error: %s', exc, exc_info=True)
        return JsonResponse({
            'success': False,
            'message': 'Failed to submit your message. Please try again.',
        }, status=400)


def home(request):
    settings = HomePageSettings.load()

    # Load from models
    trust_badges = HeroTrustBadge.objects.all()
    stats_data = HeroStatistic.objects.all()
    product_tiles = HeroProductTile.objects.all()
    hero_slides = HeroSlide.objects.all()
    dyk_slides = DidYouKnowSlide.objects.all()
    quick_picks = QuickPickItem.objects.all()
    why_cards = WhyChooseCard.objects.all()
    works_steps = HowItWorksStep.objects.all()

    # Testimonials logic (keep existing random/cache logic)
    reviews = cache.get('homepage_reviews')
    if reviews is None:
        from apps.agents.models import AgentReview
        db_reviews = AgentReview.objects.filter(is_approved=True).select_related('agent', 'agent__profile').order_by('-created_at')[:100]

        agent_counts = {}
        final_reviews = []
        backfill_reviews = []

        for rev in db_reviews:
            agent_id = rev.agent_id
            if agent_id:
                if agent_id not in agent_counts:
                    agent_counts[agent_id] = 0
                if agent_counts[agent_id] < 3:
                    final_reviews.append(rev)
                    agent_counts[agent_id] += 1
                else:
                    backfill_reviews.append(rev)
            else:
                final_reviews.append(rev)

        if len(final_reviews) < 10 and backfill_reviews:
            needed = 10 - len(final_reviews)
            final_reviews.extend(backfill_reviews[:needed])

        final_reviews = final_reviews[:10]

        reviews = []
        for rev in final_reviews:
            agent_name = rev.agent.fullname if rev.agent else None
            agent_slug = None
            agent_photo = None

            if rev.agent:
                try:
                    profile = rev.agent.profile
                    agent_slug = profile.slug
                    agent_photo = profile.profile_photo_url
                except Exception:
                    pass

            avatar_url = agent_photo if (agent_photo and 'avatar-icon.jpg' not in agent_photo) else f"https://ui-avatars.com/api/?name={rev.reviewer_name or 'User'}&background=0d9488&color=fff&bold=true"

            reviews.append({
                'name': rev.reviewer_name or 'User',
                'service': f"Client of {agent_name}" if agent_name else "Verified Client",
                'agent_url': f"/profile/{agent_slug}/" if agent_slug else None,
                'rating': float(rev.rating),
                'comment': rev.review or '',
                'image': avatar_url
            })

        if not reviews:
            reviews = [
                {'name': 'Sneha Patel', 'service': 'Client of Rajesh Kumar', 'agent_url': None, 'rating': 5.0, 'comment': 'Found my perfect health insurance through my PadosiAgent. They were professional and explained everything clearly.', 'image': 'https://ui-avatars.com/api/?name=Sneha+Patel&background=0d9488&color=fff&bold=true'},
                {'name': 'Rahul Verma', 'service': 'Client of Vikram Singh', 'agent_url': None, 'rating': 4.5, 'comment': 'My claim was rejected initially, but my PadosiAgent helped me get it approved. Highly recommended!', 'image': 'https://ui-avatars.com/api/?name=Rahul+Verma&background=0d9488&color=fff&bold=true'},
                {'name': 'Anjali Desai', 'service': 'Client of Priya Sharma', 'agent_url': None, 'rating': 4.0, 'comment': 'Got my policy reviewed and discovered I was overpaying. Saved ₹15,000 annually. Thank you!', 'image': 'https://ui-avatars.com/api/?name=Anjali+Desai&background=0d9488&color=fff&bold=true'},
            ]

        cache.set('homepage_reviews', reviews, 1800)

    # Zip trust cards with indexes to allow colored borders easily in DTL
    card_accents = [
        {'color': '#0065ff', 'class': 'pb-accent-blue'},
        {'color': '#10b981', 'class': 'pb-accent-green'},
        {'color': '#0ea5e9', 'class': 'pb-accent-sky'},
        {'color': '#d97706', 'class': 'pb-accent-orange'},
        {'color': '#7c3aed', 'class': 'pb-accent-purple'},
        {'color': '#14b8a6', 'class': 'pb-accent-teal'},
    ]
    why_cards_zipped = []
    for idx, card in enumerate(why_cards):
        accent = card_accents[idx % len(card_accents)]
        why_cards_zipped.append({
            'card': card,
            'accent': accent,
            'index': idx
        })

    slide_gradients = [
        'linear-gradient(135deg, hsla(var(--pa-primary-h), var(--pa-primary-s), var(--pa-primary-l), 0.25), hsla(var(--pa-primary-h), var(--pa-primary-s), var(--pa-primary-l), 0.1), hsla(var(--pa-primary-h), var(--pa-primary-s), var(--pa-primary-l), 0.05))',
        'linear-gradient(135deg, hsla(var(--pa-secondary-h), var(--pa-secondary-s), var(--pa-secondary-l), 0.25), hsla(var(--pa-secondary-h), var(--pa-secondary-s), var(--pa-secondary-l), 0.1), hsla(var(--pa-secondary-h), var(--pa-secondary-s), var(--pa-secondary-l), 0.05))',
        'linear-gradient(135deg, hsla(0, 72%, 51%, 0.25), hsla(0, 72%, 51%, 0.1), hsla(0, 72%, 51%, 0.05))',
        'linear-gradient(135deg, hsla(38, 92%, 50%, 0.25), hsla(38, 92%, 50%, 0.1), hsla(38, 92%, 50%, 0.05))',
        'linear-gradient(135deg, hsla(173, 80%, 36%, 0.25), hsla(173, 80%, 36%, 0.1), hsla(173, 80%, 36%, 0.05))',
        'linear-gradient(135deg, hsla(160, 84%, 39%, 0.25), hsla(160, 84%, 39%, 0.1), hsla(160, 84%, 39%, 0.05))',
        'linear-gradient(135deg, hsla(262, 83%, 58%, 0.25), hsla(262, 83%, 58%, 0.1), hsla(262, 83%, 58%, 0.05))',
    ]
    slide_icon_shadows = [
        '0 10px 15px -3px hsla(var(--pa-primary-h), var(--pa-primary-s), var(--pa-primary-l), 0.2), 0 4px 6px -4px hsla(var(--pa-primary-h), var(--pa-primary-s), var(--pa-primary-l), 0.2)',
        '0 10px 15px -3px hsla(var(--pa-secondary-h), var(--pa-secondary-s), var(--pa-secondary-l), 0.2), 0 4px 6px -4px hsla(var(--pa-secondary-h), var(--pa-secondary-s), var(--pa-secondary-l), 0.2)',
        '0 10px 15px -3px hsla(0, 72%, 51%, 0.2), 0 4px 6px -4px hsla(0, 72%, 51%, 0.2)',
        '0 10px 15px -3px hsla(38, 92%, 50%, 0.2), 0 4px 6px -4px hsla(38, 92%, 50%, 0.2)',
        '0 10px 15px -3px hsla(173, 80%, 36%, 0.2), 0 4px 6px -4px hsla(173, 80%, 36%, 0.2)',
        '0 10px 15px -3px hsla(160, 84%, 39%, 0.2), 0 4px 6px -4px hsla(160, 84%, 39%, 0.2)',
        '0 10px 15px -3px hsla(262, 83%, 58%, 0.2), 0 4px 6px -4px hsla(262, 83%, 58%, 0.2)',
    ]

    facts_zipped = []
    for idx, fact in enumerate(hero_slides):
        facts_zipped.append({
            'fact': fact,
            'gradient': slide_gradients[idx % len(slide_gradients)],
            'shadow': slide_icon_shadows[idx % len(slide_icon_shadows)],
            'index': idx
        })

    # 2. Build and zip dyk slides
    slides_zipped = []
    for idx, slide in enumerate(dyk_slides):
        slides_zipped.append({
            'fact': slide,
            'index': idx
        })

    # 3. Static chart data for hero section chart slide
    chart_data = [
        {'year': '2020', 'rejection': 12},
        {'year': '2021', 'rejection': 16},
        {'year': '2022', 'rejection': 21},
        {'year': '2023', 'rejection': 27},
        {'year': '2024', 'rejection': 34},
    ]

    from apps.home.models.site_setting import SiteSetting
    custom_hero = SiteSetting.get_value('hero_section')
    if custom_hero and isinstance(custom_hero, dict) and custom_hero.get('heading'):
        raw_heading = custom_hero['heading']
    else:
        raw_heading = settings.hero_heading
    # Clean braces first if any
    cleaned_heading = raw_heading.replace('{', '').replace('}', '')
    def replace_word(match):
        word = match.group(0)
        lower_word = word.lower()
        if 'padosi' in lower_word:
            return f'<span class="pa-heading-highlight">{word}</span>'
        else:
            return f'<span class="pa-heading-trusted">{word}</span>'
    hero_heading_html = re.sub(r'\b(Trusted|Licensed|Licenced|Padosi)\b', replace_word, cleaned_heading, flags=re.IGNORECASE)

    return render(request, 'public/home.html', {
        'settings': settings,
        'why_cards_zipped': why_cards_zipped,
        'reviews_json': json.dumps(reviews),
        'hide_header': True,
        'trust_badges': trust_badges,
        'stats_data': stats_data,
        'product_tiles': product_tiles,
        'facts_zipped': facts_zipped,
        'slides_zipped': slides_zipped,
        'quick_picks': quick_picks,
        'why_cards': why_cards,
        'works_steps': works_steps,
        'chart_data': chart_data,
        'hero_heading_html': hero_heading_html,
    })


def get_portfolio_companies_by_type():
    """
    Get companies grouped by insurance type (segment).
    Cache for 30 minutes.
    """
    cache_key = 'portfolio_companies_by_type'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    segment_label_map = {
        'health': 'Health Insurance',
        'life': 'Life Insurance',
        'motor': 'Motor Insurance',
        'sme': 'SME Insurance',
    }

    companies_by_type = {
        'Health Insurance': [],
        'Life Insurance': [],
        'Motor Insurance': [],
        'SME Insurance': [],
    }

    try:
        # Fetch active agents portfolios
        portfolios = AgentPortfolio.objects.filter(
            agent__status='active',
            agent__user__isnull=False
        ).select_related('agent')

        for p in portfolios:
            segment_key = str(p.segment_type).lower().strip()
            if segment_key not in segment_label_map:
                continue

            bucket = segment_label_map[segment_key]
            candidates = []

            primary = p.primary_companies or {}
            secondary = p.secondary_companies or {}

            primary_name = str(primary.get('name', '')).strip()
            secondary_name = str(secondary.get('name', '')).strip()

            if primary_name:
                candidates.append(primary_name)
            if secondary_name:
                candidates.append(secondary_name)

            extra_companies = secondary.get('companies', [])
            if isinstance(extra_companies, list):
                for c in extra_companies:
                    if isinstance(c, dict):
                        c_name = str(c.get('name', '')).strip()
                    else:
                        c_name = str(c).strip()
                    if c_name:
                        candidates.append(c_name)

            for name in candidates:
                companies_by_type[bucket].append(name)
    except Exception as e:
        logger.error(f"Error fetching portfolio companies: {e}")

    # Dedup and sort
    for label, lst in companies_by_type.items():
        deduped = {}
        for company in lst:
            key = company.lower().strip()
            if key and key not in deduped:
                deduped[key] = company.strip()
        companies_by_type[label] = sorted(list(deduped.values()), key=str.casefold)

    cache.set(cache_key, companies_by_type, timeout=1800)
    return companies_by_type


def find_agents(request):
    sort_by = request.GET.get('sort_by', '').strip()
    invalid_pincode = False

    # RESET LOCATION
    if 'reset_location' in request.GET:
        for k in ['last_pincode', 'last_location', 'last_lat', 'last_lng', 'detected_area', 'pincode', 'location', 'lat', 'lng']:
            if k in request.session:
                del request.session[k]
        return redirect('home:find_agents')

    # Capture parameters
    pincode_param = request.GET.get('pincode', '').strip()
    location_param = request.GET.get('location', '').strip()
    lat_param = request.GET.get('lat', '').strip()
    lng_param = request.GET.get('lng', '').strip()

    is_htmx = request.headers.get('HX-Request') == 'true'

    # Save to session and clear opposite parameters to prevent conflicts
    if pincode_param or location_param:
        if pincode_param:
            request.session['last_pincode'] = pincode_param
            detected_area = pincode_param
            
            # Resolve pincode to area name immediately (before redirect)
            if re.match(r'^[1-9]\d{5}$', pincode_param):
                try:
                    pincode_row = Pincode.objects.filter(pincode=pincode_param).first()
                    is_placeholder = False
                    if pincode_row:
                        office_name = pincode_row.office_name or ''
                        is_placeholder = bool(re.match(r'^(Area|Region)\s+\d', office_name, re.IGNORECASE))
                        if not is_placeholder and office_name:
                            detected_area = pincode_row.formatted_location
                        elif pincode_row.state:
                            detected_area = f"{pincode_row.state} - {pincode_param}"
                    
                    if not pincode_row or is_placeholder:
                        geo_svc = GeocodingService()
                        resolved = geo_svc.resolve_coordinates(pincode_param)
                        if resolved and resolved.get('display_name'):
                            detected_area = resolved['display_name']
                except Exception as e:
                    logger.warning(f"find_agents: Failed to resolve area for pincode {pincode_param}: {e}")
            
            request.session['detected_area'] = detected_area

        if location_param:
            request.session['last_location'] = location_param
            request.session['detected_area'] = location_param

        # Clear old GPS memory
        for k in ['last_lat', 'last_lng', 'lat', 'lng']:
            if k in request.session:
                del request.session[k]

    elif lat_param and lng_param:
        request.session['last_lat'] = lat_param
        request.session['last_lng'] = lng_param
        
        # Clear old Pincode/Location memory
        for k in ['last_pincode', 'last_location', 'pincode', 'location', 'detected_area']:
            if k in request.session:
                del request.session[k]

    # Clean URL redirection (Session-only storage) for non-HTMX requests
    if (pincode_param or location_param or lat_param) and not is_htmx:
        params = request.GET.copy()
        for k in ['pincode', 'location', 'lat', 'lng']:
            if k in params:
                del params[k]
        url = request.path
        if params:
            url += '?' + params.urlencode()
        return redirect(url)

    # Merge session values for query lookup
    pincode = request.session.get('last_pincode', '').strip()
    location = request.session.get('last_location', '').strip()
    lat = request.session.get('last_lat', '').strip()
    lng = request.session.get('last_lng', '').strip()
    detected_area = request.session.get('detected_area', '')

    should_gate_guest = False
    service_type_input = request.GET.getlist('ServiceType')
    service_type = service_type_input[0] if service_type_input else ''
    
    has_any_filter = bool(
        request.GET.get('ServiceType') or
        request.GET.get('InsuranceType') or
        request.GET.get('InsuranceCompany') or
        request.GET.get('ComplaintType') or
        request.GET.get('search')
    )

    has_new_policy = 'New Policy' in service_type_input or 'Buying new insurance' in service_type_input
    has_claim_assistance = 'Claim Assistance' in service_type_input or 'Claim' in service_type_input
    has_policy_review = any(s in service_type_input for s in ['Policy Review', 'Insurance audit', 'Port / transfer'])

    policy_review_needs_type = has_policy_review and not request.GET.get('InsuranceType')
    new_policy_needs_type = has_new_policy and not request.GET.get('InsuranceType')
    claim_assistance_needs_type = has_claim_assistance and not request.GET.get('InsuranceType')
    no_service_type = not service_type_input

    should_require_filter_selection = False
    filter_prompt_message = (
        'Please select a Service Type and an Insurance Type, then click Apply.' if no_service_type else (
            'For New Policy, please select an Insurance Type and click Apply.' if new_policy_needs_type else (
                'For Claim Assistance, please select an Insurance Type and click Apply.' if claim_assistance_needs_type else (
                    'For Policy Review, please select at least one Insurance Type and click Apply.' if policy_review_needs_type else
                    'Please select at least one filter (Service Type, Insurance Type, or Insurance Company), then click Apply.'
                )
            )
        )
    )

    portfolio_companies_by_type = get_portfolio_companies_by_type()

    if should_require_filter_selection:
        paginator = Paginator([], 10)
        agents = paginator.page(1)
        context = {
            'agents': agents,
            'shouldGateGuest': should_gate_guest,
            'shouldRequireFilterSelection': should_require_filter_selection,
            'filterPromptMessage': filter_prompt_message,
            'detectedArea': detected_area,
            'invalidPincode': invalid_pincode,
            'hide_header': True,
        }
        if is_htmx:
            return render(request, 'partials/find-agents-list.html', context)
        context['portfolioCompaniesByType'] = portfolio_companies_by_type
        return render(request, 'public/find-agents.html', context)

    # Core query build
    query = Agent.objects.filter(status='active', user__isnull=False)
    query = query.select_related('profile', 'performanceStats').prefetch_related(
        'insuranceSegments', 'reviews', 'serviceableCities', 'productExpertise'
    )

    type_mapping = {
        'Health Insurance': 'health', 'Health': 'health',
        'Life Insurance': 'life', 'Life': 'life',
        'Motor Insurance': 'motor', 'Motor': 'motor',
        'SME Insurance': 'sme', 'SME': 'sme',
        'Travel Insurance': 'travel', 'Travel': 'travel',
        'Fire Insurance': 'fire', 'Fire': 'fire',
        'Marine Insurance': 'marine', 'Marine': 'marine',
        'Liability Insurance': 'liability', 'Liability': 'liability',
        'Other General Insurance': 'other', 'Transport': 'transport',
        'Workmen Compensation': 'workmen_compensation', 'GPA / GMC': 'gpa_gmc',
        'Group Term Insurance': 'group_term', 'Cyber': 'cyber'
    }

    db_types = []
    insurance_type_input = request.GET.getlist('InsuranceType')
    if insurance_type_input:
        for t in insurance_type_input:
            mapped_t = type_mapping.get(t, t.lower().replace(' insurance', ''))
            db_types.append(mapped_t)
        query = query.filter(insuranceSegments__segment_type__in=db_types).distinct()

    if service_type_input:
        q_pref = Q()
        if any(s in ['New Policy', 'Buying new insurance'] for s in service_type_input):
            q_pref |= Q(leadPreferences__leads_new_business=True)
        if any(s in ['Claim Assistance', 'Claim'] for s in service_type_input):
            q_pref |= Q(leadPreferences__leads_claims_support=True)
        if any(s in ['Policy Review', 'Insurance audit', 'Port / transfer'] for s in service_type_input):
            q_pref |= Q(leadPreferences__leads_portfolio_analysis=True)
            
        q_spec = Q()
        if db_types:
            q_spec = Q(insuranceSegments__segment_type__in=db_types)
            
        q_no_pref = Q(leadPreferences__isnull=True)
        query = query.filter(q_pref | q_spec | q_no_pref).distinct()

    if location:
        query = query.filter(
            Q(profile__address__icontains=location) |
            Q(profile__office_address__icontains=location) |
            Q(profile__state__icontains=location) |
            Q(serviceableCities__name__icontains=location)
        ).distinct()

    insurance_company_input = request.GET.getlist('InsuranceCompany')
    if insurance_company_input:
        q_company = Q(productExpertise__product_name__in=insurance_company_input)
        if db_types:
            q_company &= Q(productExpertise__segment_type__in=db_types)
        query = query.filter(q_company).distinct()

    claim_company_input = request.GET.get('ClaimInsuranceCompany', '').strip()
    if claim_company_input:
        query = query.filter(
            Q(portfolios__primary_companies__icontains=claim_company_input) |
            Q(portfolios__secondary_companies__icontains=claim_company_input)
        ).distinct()

    search_val = request.GET.get('search', '').strip()
    if search_val:
        query = query.filter(
            Q(fullname__icontains=search_val) |
            Q(profile__city__icontains=search_val) |
            Q(profile__state__icontains=search_val)
        ).distinct()

    # Location check and API geocoding Fallback
    user_lat = None
    user_lng = None
    if lat and lng:
        try:
            user_lat = float(lat)
            user_lng = float(lng)
        except (ValueError, TypeError):
            pass

    if not user_lat and not user_lng and pincode:
        if not re.match(r'^[1-9]\d{5}$', pincode):
            invalid_pincode = True
        else:
            try:
                geo_svc = GeocodingService()
                coords = geo_svc.resolve_coordinates(pincode)
                if coords:
                    user_lat = coords['lat']
                    user_lng = coords['lng']
                else:
                    invalid_pincode = True
            except Exception:
                coords = DistanceService.get_pincode_coordinates(pincode)
                if coords:
                    user_lat = coords['lat']
                    user_lng = coords['lng']
                else:
                    invalid_pincode = True

    if invalid_pincode:
        query = query.none()

    # Proximity reverse-geocoding for detectedArea area name
    needs_area_res = (
        not detected_area or
        bool(re.match(r'^(Area|Region)\s+\d', detected_area, re.IGNORECASE)) or
        detected_area.startswith('PIN:') or
        bool(re.match(r'^\d{6}$', detected_area))
    )
    if user_lat and user_lng and needs_area_res:
        try:
            pincode_match = Pincode.objects.annotate(
                distance=RawSQL(
                    "(6371 * acos(cos(radians(%s)) * cos(radians(latitude)) * cos(radians(longitude) - radians(%s)) + sin(radians(%s)) * sin(radians(latitude))))",
                    (user_lat, user_lng, user_lat)
                )
            ).order_by('distance').first()
            
            resolved_from_db = False
            if pincode_match and pincode_match.distance < 50:
                candidate = pincode_match.office_name or pincode_match.district
                if candidate and not re.match(r'^(Area|Region)\s+\d', candidate, re.IGNORECASE):
                    detected_area = pincode_match.formatted_location
                    resolved_from_db = True
            
            if not resolved_from_db:
                geo_svc = GeocodingService()
                detected_area = geo_svc.reverse_geocode(user_lat, user_lng)
        except Exception as e:
            logger.warning(f"find_agents: reverse geocoding failed: {e}")
            
        if detected_area:
            request.session['detected_area'] = detected_area

    if not detected_area and pincode:
        try:
            pincode_row = Pincode.objects.filter(pincode=pincode).first()
            if pincode_row:
                detected_area = pincode_row.formatted_location
            else:
                detected_area = f"PIN: {pincode}"
        except Exception:
            detected_area = f"PIN: {pincode}"
        request.session['detected_area'] = detected_area

    if user_lat and user_lng:
        request.session['lat'] = str(user_lat)
        request.session['lng'] = str(user_lng)

    if not sort_by:
        sort_by = 'distance' if (user_lat is not None and user_lng is not None) else 'match'

    # Inject Padosi Smart Rank score calculation (MySQL-specific)
    if db_types:
        placeholders = ", ".join(["%s"] * len(db_types))
        filter_match_sql = f"(SELECT COUNT(*) FROM agent_insurance_segments WHERE agent_insurance_segments.agent_id = agents.id AND agent_insurance_segments.segment_type IN ({placeholders}))"
        filter_match_params = tuple(db_types)
    else:
        filter_match_sql = "(SELECT COUNT(*) FROM agent_insurance_segments WHERE agent_insurance_segments.agent_id = agents.id AND 1=0)"
        filter_match_params = ()

    smart_rank_expr = f"""
        (CASE 
            WHEN CAST(COALESCE(NULLIF(agents.experience_range, ''), NULLIF((SELECT experience_years FROM agent_profiles WHERE agent_profiles.agent_id = agents.id), 0), 0) AS UNSIGNED) >= 15 THEN 20 
            ELSE (CAST(COALESCE(NULLIF(agents.experience_range, ''), NULLIF((SELECT experience_years FROM agent_profiles WHERE agent_profiles.agent_id = agents.id), 0), 0) AS UNSIGNED) / 15) * 20 
        END) +
        (CASE WHEN agents.client_base >= 500 THEN 20 ELSE (IFNULL(agents.client_base, 0) / 500) * 20 END) +
        (CASE 
            WHEN (SELECT IFNULL(claims_processed, 0) FROM agent_performance_stats WHERE agent_performance_stats.agent_id = agents.id) >= 100 THEN 20 
            ELSE (SELECT IFNULL(claims_processed, 0) FROM agent_performance_stats WHERE agent_performance_stats.agent_id = agents.id) / 100 * 20 
        END) +
        (CASE WHEN agents.badge IS NOT NULL AND agents.badge != 'none' AND agents.badge != '' THEN 15 ELSE 0 END) +
        (CASE WHEN (SELECT AVG(rating) FROM agent_reviews WHERE agent_reviews.agent_id = agents.id AND agent_reviews.is_approved = 1) >= 4.5 THEN 10 ELSE 0 END) +
        (CASE 
            WHEN COALESCE(
                (SELECT last_login_at FROM users WHERE users.id = agents.user_id),
                (SELECT last_login FROM auth_user WHERE auth_user.id = agents.user_id)
            ) >= DATE_SUB(UTC_TIMESTAMP(), INTERVAL 3 DAY) THEN 50
            WHEN COALESCE(
                (SELECT last_login_at FROM users WHERE users.id = agents.user_id),
                (SELECT last_login FROM auth_user WHERE auth_user.id = agents.user_id)
            ) >= DATE_SUB(UTC_TIMESTAMP(), INTERVAL 14 DAY) THEN 25
            WHEN COALESCE(
                (SELECT last_login_at FROM users WHERE users.id = agents.user_id),
                (SELECT last_login FROM auth_user WHERE auth_user.id = agents.user_id)
            ) >= DATE_SUB(UTC_TIMESTAMP(), INTERVAL 30 DAY) THEN 10
            ELSE 0
        END) +
        ((
            (CASE WHEN (SELECT profile_photo_path FROM agent_profiles WHERE agent_profiles.agent_id = agents.id) IS NOT NULL AND (SELECT profile_photo_path FROM agent_profiles WHERE agent_profiles.agent_id = agents.id) != '' THEN 1 ELSE 0 END) +
            (CASE WHEN (SELECT address FROM agent_profiles WHERE agent_profiles.agent_id = agents.id) IS NOT NULL AND (SELECT address FROM agent_profiles WHERE agent_profiles.agent_id = agents.id) != '' THEN 1 ELSE 0 END) +
            (CASE WHEN (agents.experience_range IS NOT NULL AND agents.experience_range != '') OR (SELECT experience_years FROM agent_profiles WHERE agent_profiles.agent_id = agents.id) > 0 THEN 1 ELSE 0 END) +
            (CASE WHEN (SELECT whatsapp FROM agent_profiles WHERE agent_profiles.agent_id = agents.id) IS NOT NULL AND (SELECT whatsapp FROM agent_profiles WHERE agent_profiles.agent_id = agents.id) != '' THEN 1 ELSE 0 END) +
            (CASE WHEN (SELECT license_number FROM agent_profiles WHERE agent_profiles.agent_id = agents.id) IS NOT NULL AND (SELECT license_number FROM agent_profiles WHERE agent_profiles.agent_id = agents.id) != '' THEN 1 ELSE 0 END) +
            (CASE WHEN (SELECT languages FROM agent_profiles WHERE agent_profiles.agent_id = agents.id) IS NOT NULL AND (SELECT languages FROM agent_profiles WHERE agent_profiles.agent_id = agents.id) != '' THEN 1 ELSE 0 END)
        ) * 5) +
        ({filter_match_sql} * 30)
    """

    query = query.annotate(padosi_smart_rank=RawSQL(smart_rank_expr, filter_match_params))

    # Fetch and process/sort in memory
    all_agents = list(query)

    for agent in all_agents:
        agent.distance = None
        # Proximity distance calculation
        if user_lat is not None and user_lng is not None:
            agent_coords = None
            if agent.latitude and agent.longitude:
                agent_coords = {'lat': float(agent.latitude), 'lng': float(agent.longitude)}
            
            if not agent_coords and agent.profile:
                agent_pincodes = agent.profile.service_pincodes
                if agent_pincodes and isinstance(agent_pincodes, list):
                    agent_pincode = agent_pincodes[0]
                    if isinstance(agent_pincode, dict):
                        agent_pincode = agent_pincode.get('pincode', '')
                    agent_coords = DistanceService.get_pincode_coordinates(agent_pincode)
            
            if not agent_coords and agent.profile:
                first_city = agent.serviceableCities.first()
                if first_city:
                    agent_coords = DistanceService.get_city_coordinates(first_city.name)

            if agent_coords:
                agent.distance = DistanceService.calculate(user_lat, user_lng, agent_coords['lat'], agent_coords['lng'])
            else:
                agent.distance = 999999

    # Filter to 50km radius if user coords are present
    if user_lat is not None and user_lng is not None:
        all_agents = [a for a in all_agents if a.distance is not None and a.distance <= 50]

    # In-memory sorting matching Laravel's logic
    if user_lat is not None and user_lng is not None and sort_by == 'distance':
        all_agents.sort(key=lambda x: (x.distance if x.distance is not None else 999999, -(x.padosi_smart_rank or 0)))
    elif sort_by == 'rating':
        all_agents.sort(key=lambda x: (-x.average_rating, -(x.padosi_smart_rank or 0)))
    elif sort_by == 'experience':
        all_agents.sort(key=lambda x: (-x.experience_years, -(x.padosi_smart_rank or 0)))
    else:
        # Default: best match % (smart_rank desc), tiebreaker: distance asc
        all_agents.sort(key=lambda x: (
            -(x.padosi_smart_rank or 0), 
            x.distance if x.distance is not None else 999999
        ))

    # Calculate match percentage and attach reviews/stats properties
    max_smart_rank = max([a.padosi_smart_rank or 0 for a in all_agents]) if all_agents else 165
    if max_smart_rank <= 0:
        max_smart_rank = 165

    for a in all_agents:
        rank = a.padosi_smart_rank or 0
        a.match_percent = int(min(99.0, max(80.0, 80.0 + (rank / max_smart_rank) * 19.0)))
        # Attach helper attributes for templates
        a.review_count_val = a.review_count

    # Paginate results
    page = request.GET.get('page', 1)
    paginator = Paginator(all_agents, 10)
    try:
        agents_page = paginator.page(page)
    except PageNotAnInteger:
        agents_page = paginator.page(1)
    except EmptyPage:
        agents_page = paginator.page(paginator.num_pages)

    next_page_url = None
    if agents_page.has_next():
        params = request.GET.copy()
        params['page'] = agents_page.next_page_number()
        next_page_url = f"?{params.urlencode()}"

    context = {
        'agents': agents_page,
        'sort_by': sort_by,
        'shouldGateGuest': should_gate_guest,
        'shouldRequireFilterSelection': should_require_filter_selection,
        'filterPromptMessage': filter_prompt_message,
        'detectedArea': detected_area,
        'pincode': pincode,
        'location': location,
        'lat': lat,
        'lng': lng,
        'maxSmartRank': max_smart_rank,
        'invalidPincode': invalid_pincode,
        'next_page_url': next_page_url,
        'selected_service_type': request.GET.getlist('ServiceType'),
        'selected_insurance_types': request.GET.getlist('InsuranceType'),
        'selected_insurance_companies': request.GET.getlist('InsuranceCompany'),
        'hide_header': True,
    }

    if is_htmx:
        return render(request, 'partials/find-agents-list.html', context)

    context['portfolioCompaniesByType'] = portfolio_companies_by_type
    return render(request, 'public/find-agents.html', context)


@require_GET
def pincode_fetch(request, pincode):
    if not re.match(r'^[1-9]\d{5}$', pincode):
        return JsonResponse({'success': False, 'message': 'Invalid pincode format.'})

    record = Pincode.objects.filter(pincode=pincode).first()
    if record:
        return JsonResponse({
            'success': True,
            'data': {
                'office_name': record.office_name,
                'district': record.district,
                'state': record.state,
                'latitude': str(record.latitude),
                'longitude': str(record.longitude),
            }
        })

    try:
        resp = http_requests.get(f'https://api.postalpincode.in/pincode/{pincode}', timeout=10)
        resp.raise_for_status()
        body = resp.json()
        if not body or body[0].get('Status') != 'Success' or not body[0].get('PostOffice'):
            return JsonResponse({'success': False, 'message': 'Pincode not found.'})

        po = body[0]['PostOffice'][0]
        state = po.get('State', '')
        district = po.get('District', '')
        office_name = po.get('Name', '')
        lat = po.get('Latitude', '0.0')
        lng = po.get('Longitude', '0.0')

        try:
            Pincode.objects.update_or_create(
                pincode=pincode,
                defaults={
                    'office_name': office_name or '',
                    'district': district or '',
                    'state': state or '',
                    'latitude': float(lat) if lat else 0.0,
                    'longitude': float(lng) if lng else 0.0,
                    'division': (po.get('Division') or '')[:100],
                    'region': (po.get('Region') or '')[:100],
                    'circle': (po.get('Circle') or '')[:100],
                    'taluk': (po.get('Taluk') or '')[:100],
                }
            )
        except Exception:
            pass

        return JsonResponse({
            'success': True,
            'data': {
                'office_name': office_name,
                'district': district,
                'state': state,
                'latitude': lat,
                'longitude': lng,
            }
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Could not verify pincode: {str(e)}'
        })


def custom_page(request, slug):
    """
    Catch-all view to render custom CMS pages.
    """
    from apps.home.models.page import Page
    from django.http import HttpResponse, Http404
    
    page = Page.objects.filter(slug=slug).first()
    if not page:
        raise Http404("Page not found")
        
    # Draft check: only admins can view drafts
    is_admin = bool(request.session.get('admin_id'))
    if not page.is_active and not is_admin:
        raise Http404("Page not found")
        
    # Serve raw page content directly if raw code mode is active
    if page.is_raw_code:
        return HttpResponse(page.content, content_type='text/html; charset=utf-8')
        
    return render(request, 'public/page.html', {'page': page})

