import re
import os
from django.shortcuts import render, redirect
from django.contrib import messages
from django.conf import settings
from django.core.files.storage import FileSystemStorage
from apps.home.models.site_setting import SiteSetting
from apps.admin_panel.models.admin_activity_log import AdminActivityLog
from apps.admin_panel.decorators import admin_login_required

def parse_nested_post(post_dict):
    """
    Parses flat Django post data like 'homepage_content[hero][headline]' into a nested dict.
    Supports lists (represented by integer keys).
    """
    data = {}
    for key, value in post_dict.items():
        if key == 'csrfmiddlewaretoken':
            continue
        # Find all brackets or initial keys
        matches = re.findall(r'([^\[\]]+)', key)
        if not matches:
            continue
        
        current = data
        for i, part in enumerate(matches[:-1]):
            next_part = matches[i + 1]
            is_next_list = next_part.isdigit()
            
            if is_next_list:
                if part not in current:
                    current[part] = []
                current = current[part]
            else:
                if isinstance(current, list):
                    idx = int(part)
                    while len(current) <= idx:
                        current.append({})
                    current = current[idx]
                else:
                    if part not in current:
                        current[part] = {}
                    current = current[part]
                    
        last_part = matches[-1]
        if isinstance(current, list):
            idx = int(last_part)
            while len(current) <= idx:
                current.append(None)
            current[idx] = value
        else:
            current[last_part] = value
            
    return data

@admin_login_required
def homepage(request):
    # Fetch homepage settings (with fallback defaults)
    default_dyk_slides = [
        {'accent': 'accent-rose',   'bg': 'bg-rose-500',   'icon': 'users',         'title': '3× faster claim settlements',      'body': 'Customers served by a nearby agent report claims clearing up to 3× faster — your agent walks the file through with the insurer.'},
        {'accent': 'accent-emerald','bg': 'bg-emerald-500','icon': 'shield',         'title': 'Local agents catch policy gaps',    'body': 'A neighbourhood expert knows your city\'s hospital network, traffic risks and weather patterns — and recommends covers a tele-caller never will.'},
        {'accent': 'accent-sky',    'bg': 'bg-sky-500',    'icon': 'clock',          'title': 'Face-to-face saves hours of confusion','body': '70%+ of policyholders say they understood their cover only after meeting an agent in person. Jargon disappears across a table.'},
        {'accent': 'accent-amber',  'bg': 'bg-amber-500',  'icon': 'trending-up',    'title': '40% lower lapse rates',             'body': 'Customers with a dedicated nearby agent are 40% less likely to let a policy lapse — they get timely renewal nudges from a real human.'},
        {'accent': 'accent-violet', 'bg': 'bg-violet-500', 'icon': 'lightbulb',      'title': 'Zero platform fee, full licensed advice','body': 'Your agent earns from the insurer — not from you. Same premium, lifetime advisor in your neighbourhood.'},
        {'accent': 'accent-pink',   'bg': 'bg-pink-500',   'icon': 'heart',          'title': 'Lifetime relationship, not a ticket number','body': 'Your Padosi agent stays the same across renewals, claims and family additions — no fresh call-centre script each time.'},
        {'accent': 'accent-indigo', 'bg': 'bg-indigo-500', 'icon': 'building-2',     'title': 'Hospital networks matter locally',  'body': 'A local agent maps the right cashless hospitals near your home and office before you ever need one.'},
        {'accent': 'accent-teal',   'bg': 'bg-teal-500',   'icon': 'indian-rupee',   'title': 'Right cover, not the costliest cover','body': 'A neighbourhood advisor sizes the premium to your real life — not to a target sheet.'},
    ]

    default_quick_picks = [
        {'label': 'Mediclaim',          'badge': 'Most Bought', 'badge_bg': '#ffe4e6', 'badge_color': '#be123c', 'icon_bg': '#fff1f2', 'icon_color': '#f43f5e', 'icon': 'heart-pulse',    'url': '/find-agents?ServiceType=New%20Policy&InsuranceType=Health%20Insurance&InsuranceCompany=Mediclaim&openFilter=1'},
        {'label': 'Term Plan',           'badge': 'Pure Cover',  'badge_bg': '#e0f2fe', 'badge_color': '#0369a1', 'icon_bg': '#f0f9ff', 'icon_color': '#0284c7', 'icon': 'clock',          'url': '/find-agents?ServiceType=New%20Policy&InsuranceType=Life%20Insurance&InsuranceCompany=Term%20Plan&openFilter=1'},
        {'label': 'Private Car',         'badge': 'Renew Fast',  'badge_bg': '#fef3c7', 'badge_color': '#b45309', 'icon_bg': '#fffbeb', 'icon_color': '#d97706', 'icon': 'car-front',      'url': '/find-agents?ServiceType=New%20Policy&InsuranceType=Motor%20Insurance&InsuranceCompany=Private%20Car&openFilter=1'},
        {'label': 'Two Wheeler',         'badge': '',            'badge_bg': '',        'badge_color': '',        'icon_bg': '#ecfdf5', 'icon_color': '#059669', 'icon': 'bike',           'url': '/find-agents?ServiceType=New%20Policy&InsuranceType=Motor%20Insurance&InsuranceCompany=Two%20Wheeler&openFilter=1'},
        {'label': 'Critical Illness',    'badge': 'Lumpsum',     'badge_bg': '#fae8ff', 'badge_color': '#a21caf', 'icon_bg': '#fdf4ff', 'icon_color': '#c026d3', 'icon': 'alert-triangle', 'url': '/find-agents?ServiceType=New%20Policy&InsuranceType=Health%20Insurance&InsuranceCompany=Critical%20Illness&openFilter=1'},
        {'label': 'Personal Accident',   'badge': '',            'badge_bg': '',        'badge_color': '',        'icon_bg': '#fff7ed', 'icon_color': '#ea580c', 'icon': 'user-check',     'url': '/find-agents?ServiceType=New%20Policy&InsuranceType=Health%20Insurance&InsuranceCompany=Personal%20Accident&openFilter=1'},
        {'label': 'Super Top-up',        'badge': 'Save Big',    'badge_bg': '#ccfbf1', 'badge_color': '#0f766e', 'icon_bg': '#f0fdfa', 'icon_color': '#0d9488', 'icon': 'trending-up',    'url': '/find-agents?ServiceType=New%20Policy&InsuranceType=Health%20Insurance&InsuranceCompany=Super%20Top-up&openFilter=1'},
        {'label': 'ULIP Plan',           'badge': '',            'badge_bg': '',        'badge_color': '',        'icon_bg': '#f5f3ff', 'icon_color': '#7c3aed', 'icon': 'bar-chart-3',    'url': '/find-agents?ServiceType=New%20Policy&InsuranceType=Life%20Insurance&InsuranceCompany=ULIP%20Plan&openFilter=1'},
        {'label': 'Pension Plan',        'badge': 'Lifetime',    'badge_bg': '#e0e7ff', 'badge_color': '#4338ca', 'icon_bg': '#eef2ff', 'icon_color': '#4f46e5', 'icon': 'landmark',       'url': '/find-agents?ServiceType=New%20Policy&InsuranceType=Life%20Insurance&InsuranceCompany=Pension%20Plan&openFilter=1'},
        {'label': 'Saving Plan',         'badge': '',            'badge_bg': '',        'badge_color': '',        'icon_bg': '#fdf2f8', 'icon_color': '#db2777', 'icon': 'piggy-bank',     'url': '/find-agents?ServiceType=New%20Policy&InsuranceType=Life%20Insurance&InsuranceCompany=Saving%20Plan&openFilter=1'},
        {'label': 'Commercial Vehicle',  'badge': '',            'badge_bg': '',        'badge_color': '',        'icon_bg': '#fef9c3', 'icon_color': '#a16207', 'icon': 'truck',          'url': '/find-agents?ServiceType=New%20Policy&InsuranceType=Motor%20Insurance&InsuranceCompany=Commercial%20Vehicle&openFilter=1'},
        {'label': 'Fire (SME)',           'badge': '',            'badge_bg': '',        'badge_color': '',        'icon_bg': '#fef2f2', 'icon_color': '#dc2626', 'icon': 'flame',          'url': '/find-agents?ServiceType=New%20Policy&InsuranceType=SME%20Insurance&InsuranceCompany=Fire%20(SME)&openFilter=1'},
        {'label': 'Cyber (SME)',          'badge': 'New',         'badge_bg': '#cffafe', 'badge_color': '#0e7490', 'icon_bg': '#ecfeff', 'icon_color': '#0891b2', 'icon': 'lock',           'url': '/find-agents?ServiceType=New%20Policy&InsuranceType=SME%20Insurance&InsuranceCompany=Cyber%20(SME)&openFilter=1'},
        {'label': 'Liability (SME)',      'badge': '',            'badge_bg': '',        'badge_color': '',        'icon_bg': '#f1f5f9', 'icon_color': '#475569', 'icon': 'scale',          'url': '/find-agents?ServiceType=New%20Policy&InsuranceType=SME%20Insurance&InsuranceCompany=Liability%20(SME)&openFilter=1'},
    ]

    default_why_cards = [
        {'bg': '#fff1f2', 'stat': '0',      'caption': 'Spam Calls',      'icon_color': '#f43f5e', 'icon': 'shield-check', 'title': 'Privacy-first by design',         'body': 'Only YOU can contact an agent. Agents can never call you first — your number is never sold or shared.'},
        {'bg': '#ecfdf5', 'stat': '₹0',     'caption': 'Platform Fee',    'icon_color': '#059669', 'icon': 'indian-rupee',  'title': '100% free for buyers',             'body': 'No charges, no hidden costs. Your premium stays the same — the agent earns from the insurer, never from you.'},
        {'bg': '#f0f9ff', 'stat': '100%',   'caption': 'Licensed Agents', 'icon_color': '#0284c7', 'icon': 'badge-check',   'title': 'Verified, licensed experts only',  'body': 'Every agent is a licensed insurance professional, vetted before listing. No call-centre scripts, ever.'},
        {'bg': '#fffbeb', 'stat': '1,000+', 'caption': 'Padosi Agents',   'icon_color': '#d97706', 'icon': 'map-pin',       'title': 'A neighbour in every PIN code',    'body': 'Discover trusted advisors within your locality who understand local hospitals, traffic and risks.'},
        {'bg': '#f5f3ff', 'stat': '1L+',    'caption': 'Families Covered','icon_color': '#7c3aed', 'icon': 'users',         'title': 'A network you can rely on',        'body': 'Lakhs of Indian families have already found their PadosiAgent for buying, renewing and claims.'},
        {'bg': '#fdf4ff', 'stat': '5.0★',   'caption': 'Average Rating',  'icon_color': '#c026d3', 'icon': 'star',          'title': 'Loved by buyers across India',     'body': 'Real reviews from real customers — no incentivised ratings, no fake testimonials.'},
        {'bg': '#eef2ff', 'stat': 'AES-256','caption': 'Encrypted Data',  'icon_color': '#4f46e5', 'icon': 'lock',          'title': 'Bank-grade data security',         'body': 'Your information is encrypted end-to-end and never sold to third parties. Full control, always.'},
    ]

    default_steps = [
        {'icon': 'search',           'accent': 'accent-primary',   'badge': '1', 'title': 'Search',    'desc': 'Find verified agents',    'tooltip': 'Find verified insurance experts by area or service.'},
        {'icon': 'git-compare',      'accent': 'accent-secondary',  'badge': '2', 'title': 'Compare',   'desc': 'Review ratings',          'tooltip': 'Review ratings and profiles to find your perfect match.'},
        {'icon': 'message-square',   'accent': 'accent-accent',     'badge': '3', 'title': 'Connect',   'desc': 'Call or WhatsApp',        'tooltip': 'Get in touch via Call or WhatsApp instantly.'},
        {'icon': 'hand-heart',       'accent': 'accent-violet',     'badge': '4', 'title': 'Assist Me', 'desc': 'Personalized service',    'tooltip': 'Get professional support for policies, claims, and more.'},
    ]

    content = SiteSetting.get_value('homepage_content', {})
    
    # Fill defaults
    if not content.get('dyk', {}).get('slides'):
        content.setdefault('dyk', {})['slides'] = default_dyk_slides
    if not content.get('quickpicks', {}).get('items'):
        content.setdefault('quickpicks', {})['items'] = default_quick_picks
    if not content.get('why_choose', {}).get('cards'):
        content.setdefault('why_choose', {})['cards'] = default_why_cards
    if not content.get('works', {}).get('steps'):
        content.setdefault('works', {})['steps'] = default_steps
    if 'testimonials' not in content:
        content['testimonials'] = {'label': 'Testimonials', 'title': 'What Users Say About Their PadosiAgent', 'subtitle': 'Real experiences...', 'use_custom': False, 'visible': True, 'custom_list': []}

    return render(request, 'admin/settings/homepage.html', {'content': content})

@admin_login_required
def update_homepage(request):
    if request.method == 'POST':
        # Reconstruct structured nested dictionary
        post_data = request.POST.dict()
        parsed = parse_nested_post(post_data)
        
        # Get homepage content dictionary
        content = parsed.get('homepage_content', {})

        # Handle visibility/custom toggle defaults since unchecked checkboxes are not in POST
        content.setdefault('hero', {})['visible'] = 'hero' in parsed.get('homepage_content', {}) and parsed['homepage_content']['hero'].get('visible') == '1'
        content.setdefault('dyk', {})['visible'] = 'dyk' in parsed.get('homepage_content', {}) and parsed['homepage_content']['dyk'].get('visible') == '1'
        content.setdefault('quickpicks', {})['visible'] = 'quickpicks' in parsed.get('homepage_content', {}) and parsed['homepage_content']['quickpicks'].get('visible') == '1'
        content.setdefault('why_choose', {})['visible'] = 'why_choose' in parsed.get('homepage_content', {}) and parsed['homepage_content']['why_choose'].get('visible') == '1'
        content.setdefault('works', {})['visible'] = 'works' in parsed.get('homepage_content', {}) and parsed['homepage_content']['works'].get('visible') == '1'
        
        # Testimonial parameters
        content.setdefault('testimonials', {})['visible'] = 'testimonials' in parsed.get('homepage_content', {}) and parsed['homepage_content']['testimonials'].get('visible') == '1'
        content['testimonials']['use_custom'] = 'testimonials' in parsed.get('homepage_content', {}) and parsed['homepage_content']['testimonials'].get('use_custom') == '1'
        
        # Sections visibility
        content.setdefault('sections', {})
        content['sections']['claim_assistance'] = 'sections' in content and content['sections'].get('claim_assistance') == '1'
        content['sections']['policy_review'] = 'sections' in content and content['sections'].get('policy_review') == '1'
        content['sections']['stats'] = 'sections' in content and content['sections'].get('stats') == '1'
        content['sections']['why_choose'] = 'sections' in content and content['sections'].get('why_choose') == '1'

        # Save setting and invalidates cache
        SiteSetting.set_value('homepage_content', content, 'homepage')
        AdminActivityLog.log('Update homepage content', 'SiteSetting', request=request)
        messages.success(request, 'Homepage settings saved successfully. Changes are live immediately!')
        
    return redirect('admin_panel:settings_homepage')

@admin_login_required
def hero_section(request):
    defaults = {
        'heading': 'Find a {Trusted} Insurance Expert in your {Padosi}',
        'trust_badges': [
            {'icon': 'check-circle', 'label': 'Licensed'},
            {'icon': 'shield',       'label': 'No Spam Calls'},
            {'icon': 'trending-up',  'label': 'Zero Platform Fee'},
        ],
        'stats': [
            {'label': 'Expert Agents',    'target': 1000, 'suffix': '+',  'icon': 'users',   'large': True,  'decimal': False},
            {'label': 'Cities Covered',   'target': 50,   'suffix': '+',  'icon': 'map-pin', 'large': False, 'decimal': False},
            {'label': 'Rating',           'target': 4.8,  'suffix': '',   'icon': 'star',    'large': False, 'decimal': True},
            {'label': 'Families Covered', 'target': 1,    'suffix': 'L+', 'icon': 'heart',   'large': False, 'decimal': False},
        ],
        'tiles': [
            {'label': 'Health Insurance',   'icon': 'heart',      'url': '/find-agents?ServiceType=New+Policy&InsuranceType=Health+Insurance&openFilter=1',   'tileClass': 'pa-tile-rose'},
            {'label': 'Life Insurance',     'icon': 'shield',     'url': '/find-agents?ServiceType=New+Policy&InsuranceType=Life+Insurance&openFilter=1',     'tileClass': 'pa-tile-sky'},
            {'label': 'Vehicle Insurance',  'icon': 'car',        'url': '/find-agents?ServiceType=New+Policy&InsuranceType=Motor+Insurance&openFilter=1',    'tileClass': 'pa-tile-amber'},
            {'label': 'Business Insurance', 'icon': 'building-2', 'url': '/find-agents?ServiceType=New+Policy&InsuranceType=SME+Insurance&openFilter=1',      'tileClass': 'pa-tile-violet'},
        ],
        'slides': [
            {'icon': 'indian-rupee',  'hero': '₹25,00,000 Cr',        'tag': 'Unclaimed Insurance',    'body': "Most families miss out because they don't have an agent.",   'isChart': False},
            {'icon': 'users',         'hero': 'Agent > Chatbot',       'tag': 'Real Support Matters',   'body': 'Cheap product or hassle-free service? Agents deliver both.', 'isChart': False},
            {'icon': 'trending-up',   'hero': 'Claim Rejections +34%', 'tag': 'As Online Sales Grow',   'body': '',                                                          'isChart': True},
            {'icon': 'badge-percent', 'hero': 'Save 20-40%',           'tag': 'Better Premiums',        'body': "Agents find coverage algorithms can't.",                    'isChart': False},
            {'icon': 'clock',         'hero': 'Claims 2x Faster',      'tag': 'With an Agent',          'body': 'No IVR loops. Real human follow-through.',                  'isChart': False},
            {'icon': 'shield-check',  'hero': '9/10 Approved',         'tag': 'Agent-Backed Claims',    'body': 'Insurers settle 3x more with agent support.',               'isChart': False},
            {'icon': 'users',         'hero': '1,000+ Agents',         'tag': 'In Your City',           'body': 'Your neighbour is already an agent. Meet face-to-face.',    'isChart': False},
        ],
        'cta_claim_text': 'Insurance Claims Support',
        'cta_claim_url': '/find-agents?ServiceType=Claim%20Assistance&openFilter=1',
        'cta_review_text': 'Insurance Audit',
        'cta_review_url': '/find-agents?ServiceType=Policy%20Review&openFilter=1',
        'claims_card_label': 'FIND INSURANCE EXPERTS NEAR ME FOR:',
        'claims_card_heading': 'Claims, audits and policy review with local advisors',
        'claims_card_text': 'Easy local guidance from verified agents, with real advisor stories and trusted help just a few minutes away.',
    }

    db = SiteSetting.get_value('hero_section', {})
    hero = {**defaults, **(db if isinstance(db, dict) else {})}
    
    icon_options = ['heart', 'shield', 'car', 'building-2', 'users', 'map-pin', 'star',
                    'check-circle', 'trending-up', 'badge-percent', 'clock', 'shield-check',
                    'indian-rupee', 'lightbulb', 'search']
    
    tile_classes = ['pa-tile-rose', 'pa-tile-sky', 'pa-tile-amber', 'pa-tile-violet']
    
    import json
    return render(request, 'admin/settings/hero_section.html', {
        'hero': hero,
        'iconOptions': icon_options,
        'tileClasses': tile_classes,
        'iconOptions_json': json.dumps(icon_options),
        'tileClasses_json': json.dumps(tile_classes)
    })

@admin_login_required
def update_hero_section(request):
    if request.method == 'POST':
        post_data = request.POST.dict()
        parsed = parse_nested_post(post_data)

        badges = parsed.get('trust_badges', [])
        # Ensure valid indexes
        badges_list = [b for b in badges if b.get('icon')] if isinstance(badges, list) else []

        stats = parsed.get('stats', [])
        stats_list = []
        if isinstance(stats, list):
            for stat in stats:
                if stat.get('label'):
                    stats_list.append({
                        'label': stat['label'],
                        'target': float(stat.get('target', 0)),
                        'suffix': stat.get('suffix', ''),
                        'icon': stat.get('icon', 'users'),
                        'large': stat.get('large') == '1',
                        'decimal': stat.get('decimal') == '1'
                    })

        tiles = parsed.get('tiles', [])
        tiles_list = []
        if isinstance(tiles, list):
            for tile in tiles:
                if tile.get('label'):
                    tiles_list.append({
                        'label': tile['label'],
                        'icon': tile.get('icon', 'heart'),
                        'url': tile.get('url', '#'),
                        'tileClass': tile.get('tileClass', 'pa-tile-rose')
                    })

        slides = parsed.get('slides', [])
        slides_list = []
        if isinstance(slides, list):
            for slide in slides:
                if slide.get('hero'):
                    slides_list.append({
                        'icon': slide.get('icon', 'users'),
                        'hero': slide['hero'],
                        'tag': slide.get('tag', ''),
                        'body': slide.get('body', ''),
                        'isChart': slide.get('isChart') == '1'
                    })

        payload = {
            'heading': request.POST.get('heading', ''),
            'trust_badges': badges_list,
            'stats': stats_list,
            'tiles': tiles_list,
            'slides': slides_list,
            'cta_claim_text': request.POST.get('cta_claim_text', ''),
            'cta_claim_url': request.POST.get('cta_claim_url', ''),
            'cta_review_text': request.POST.get('cta_review_text', ''),
            'cta_review_url': request.POST.get('cta_review_url', ''),
            'claims_card_label': request.POST.get('claims_card_label', ''),
            'claims_card_heading': request.POST.get('claims_card_heading', ''),
            'claims_card_text': request.POST.get('claims_card_text', ''),
        }

        SiteSetting.set_value('hero_section', payload, 'homepage')
        AdminActivityLog.log('Updated Hero Section content', 'SiteSetting', request=request)
        messages.success(request, 'Hero Section saved successfully!')

    return redirect('admin_panel:settings_hero_section')


@admin_login_required
def general(request):
    social_links_default = {
        'facebook': '',
        'twitter': '',
        'linkedin': '',
        'instagram': ''
    }
    social_links = SiteSetting.get_value('social_links', social_links_default)
    if not isinstance(social_links, dict):
        social_links = social_links_default

    default_message = (
        "Hi! I'm partnering with PadosiAgent, and I'd love for you to join my network. "
        "Register using my exclusive link below to get special benefits:\n\n{LINK}\n\n"
        "Let me know if you have any questions!"
    )

    context = {
        'site_name': SiteSetting.get_value('site_name', 'PadosiAgent'),
        'site_logo': SiteSetting.get_value('site_logo', ''),
        'site_favicon': SiteSetting.get_value('site_favicon', ''),
        'contact_email': SiteSetting.get_value('contact_email', ''),
        'contact_phone': SiteSetting.get_value('contact_phone', '+91 80000 00000'),
        'contact_address': SiteSetting.get_value('contact_address', ''),
        'social_links': social_links,
        'distributor_invite_message': SiteSetting.get_value('distributor_invite_message', default_message),
    }

    return render(request, 'admin/settings/general.html', context)


@admin_login_required
def update_settings(request):
    if request.method == 'POST':
        group = request.POST.get('group', 'general')
        
        # Parse nested inputs like social_links[facebook]
        parsed_post = parse_nested_post(request.POST.dict())
        
        # Save each standard parsed key
        for key, value in parsed_post.items():
            if key in ['group', 'site_logo', 'site_favicon']:
                continue
            SiteSetting.set_value(key, value, group=group)
            
        # Handle file uploads (site_logo, site_favicon)
        import uuid
        fs = FileSystemStorage(location=os.path.join(settings.MEDIA_ROOT, 'site'), base_url='/media/site/')
        for key, file_obj in request.FILES.items():
            orig_name, ext = os.path.splitext(file_obj.name)
            random_suffix = uuid.uuid4().hex[:8]
            new_filename = f"{orig_name}_{random_suffix}{ext}"
            
            filename = fs.save(new_filename, file_obj)
            file_url = fs.url(filename)
            SiteSetting.set_value(key, file_url, group=group)
            
        label = 'SEO' if group == 'seo' else group.capitalize()
        AdminActivityLog.log(f'Updated {label} settings', 'SiteSetting', request=request)
        messages.success(request, f'{label} settings updated successfully.')
        
        if group == 'seo':
            return redirect('admin_panel:settings_seo')
        elif group == 'security':
            return redirect('admin_panel:settings_security')
        
    return redirect('admin_panel:settings_general')


@admin_login_required
def seo(request):
    context = {
        'seo_meta_title': SiteSetting.get_value('seo_meta_title', 'Expert & Trusted Insurance Agent in your Padosi'),
        'seo_meta_description': SiteSetting.get_value('seo_meta_description', ''),
        'seo_keywords': SiteSetting.get_value('seo_keywords', 'insurance, agent, neighborhood, padosiagent, life insurance'),
        'seo_og_title': SiteSetting.get_value('seo_og_title', ''),
        'seo_og_description': SiteSetting.get_value('seo_og_description', ''),
    }
    return render(request, 'admin/settings/seo.html', context)


@admin_login_required
def security(request):
    context = {
        'rate_limit_clicks': SiteSetting.get_value('rate_limit_clicks', '10'),
        'rate_limit_timeframe': SiteSetting.get_value('rate_limit_timeframe', '2'),
    }
    return render(request, 'admin/settings/security.html', context)


# Helper function to get physical path of template
def _get_template_path(template_type):
    valid_types = {
        'invoice': os.path.join(settings.BASE_DIR, 'templates', 'pdf', 'invoice.html'),
        'email_credentials': os.path.join(settings.BASE_DIR, 'templates', 'emails', 'agent_credentials.html'),
        'email_otp': os.path.join(settings.BASE_DIR, 'templates', 'emails', 'otp.html'),
    }
    if template_type not in valid_types:
        from django.http import Http404
        raise Http404("Invalid template type.")
    return valid_types[template_type]

# Helper to initialize default template files if missing
def _initialize_default_template(template_type, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        return
        
    defaults = {
        'email_otp': """<!DOCTYPE html>
<html>
<head>
    <title>Email Verification - PadosiAgent</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body { font-family: 'Segoe UI', sans-serif; line-height: 1.6; color: #334155; margin: 0; background-color: #f1f5f9; }
        .container { max-width: 600px; margin: 40px auto; background: #ffffff; border-radius: 16px; overflow: hidden; box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1); }
        .header { background-color: #0d9488; padding: 30px; text-align: center; }
        .content { padding: 40px; }
        .welcome-text { font-size: 18px; font-weight: 600; color: #1e293b; margin-bottom: 20px; }
        .verification-badge { display: inline-block; background-color: #e0f2fe; color: #0369a1; padding: 4px 12px; border-radius: 9999px; font-size: 14px; font-weight: 600; margin-bottom: 20px; }
        .otp-container { background-color: #f8fafc; border: 2px dashed #cbd5e1; border-radius: 12px; padding: 30px; text-align: center; margin: 30px 0; }
        .otp-code { font-size: 36px; font-weight: 800; color: #0d9488; letter-spacing: 8px; margin: 0; text-align: center; }
        .footer { padding: 30px; background-color: #f8fafc; text-align: center; font-size: 14px; color: #64748b; border-top: 1px solid #e2e8f0; }
        .signature { margin-top: 20px; color: #475569; }
    </style>
</head>
<body style="margin: 0; padding: 0; background-color: #f1f5f9;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background-color: #f1f5f9;">
        <tr>
            <td align="center" style="padding: 20px;">
                <div class="container">
                    <div class="header">
                        <div style="background-color: #ffffff; display: inline-block; padding: 12px 24px; border-radius: 8px;">
                            <img src="{{ site_logo|default:'/static/images/logo.png' }}" alt="PadosiAgent Logo" style="max-width: 180px; height: auto; display: block; margin: 0 auto;">
                        </div>
                    </div>
                    <div class="content">
                        <span class="verification-badge">Verification Required</span>
                        <p class="welcome-text">Hello,</p>
                        <p>Thank you for choosing <strong>PadosiAgent</strong>. To complete your verification, please use the 6-digit One-Time Password (OTP) provided below:</p>
                        <div class="otp-container">
                            <p class="otp-code">{{ otp }}</p>
                        </div>
                        <p>This code is valid for <strong>10 minutes</strong>. For security reasons, please do not share this code with anyone.</p>
                        <p>If you did not request this verification, please ignore this email.</p>
                        <div class="signature">
                            <p>Warm regards,<br><strong>Team PadosiAgent</strong></p>
                        </div>
                    </div>
                    <div class="footer">
                        <p style="margin: 0;">&copy; 2026 PadosiAgent ServTech Private Limited. All rights reserved.</p>
                    </div>
                </div>
            </td>
        </tr>
    </table>
</body>
</html>""",
        'email_credentials': """<!DOCTYPE html>
<html>
<head>
    <title>Welcome to PadosiAgent - Registration Complete</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body { font-family: 'Segoe UI', sans-serif; line-height: 1.6; color: #334155; margin: 0; background-color: #f1f5f9; }
        .container { max-width: 600px; margin: 40px auto; background: #ffffff; border-radius: 16px; overflow: hidden; box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1); }
        .header { background-color: #0d9488; padding: 30px; text-align: center; }
        .content { padding: 40px; }
        .welcome-text { font-size: 18px; font-weight: 600; color: #1e293b; margin-bottom: 20px; }
        .credentials-container { background-color: #f8fafc; border-radius: 12px; padding: 25px; margin: 30px 0; border: 1px solid #e2e8f0; }
        .credential-item { margin-bottom: 18px; padding-bottom: 15px; border-bottom: 1px solid #e2e8f0; }
        .credential-item:last-child { margin-bottom: 0; padding-bottom: 0; border-bottom: none; }
        .credential-label { font-weight: 600; color: #64748b; display: block; margin-bottom: 8px; font-size: 14px; text-transform: uppercase; }
        .credential-value { color: #0d9488; font-weight: 600; font-size: 14px; background-color: #f1f5f9; padding: 10px 12px; border-radius: 6px; font-family: monospace; display: block; }
        .footer { padding: 30px; background-color: #f8fafc; text-align: center; font-size: 14px; color: #64748b; border-top: 1px solid #e2e8f0; }
        .signature { margin-top: 20px; color: #475569; }
    </style>
</head>
<body style="margin: 0; padding: 0; background-color: #f1f5f9;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background-color: #f1f5f9;">
        <tr>
            <td align="center" style="padding: 20px;">
                <div class="container">
                    <div class="header">
                        <div style="background-color: #ffffff; display: inline-block; padding: 12px 24px; border-radius: 8px;">
                            <img src="{{ site_logo|default:'/static/images/logo.png' }}" alt="PadosiAgent Logo" style="max-width: 180px; height: auto; display: block; margin: 0 auto;">
                        </div>
                    </div>
                    <div class="content">
                        <p class="welcome-text">Hello {{ agent.fullname }},</p>
                        <div class="success-message" style="background-color: #dcfce7; padding: 15px; border-left: 4px solid #15803d; font-size: 14px; color: #166534; border-radius: 4px; margin: 20px 0;">
                            <strong>✓ Registration Successful!</strong><br>
                            Your account has been activated. You can now log in with the credentials below.
                        </div>
                        <p>Welcome to <strong>PadosiAgent</strong>! Use the following credentials to access your agent dashboard:</p>
                        <div class="credentials-container">
                            <div class="credential-item">
                                <span class="credential-label">Email Address</span>
                                <span class="credential-value">{{ agent.email }}</span>
                            </div>
                            <div class="credential-item">
                                <span class="credential-label">Password</span>
                                <span class="credential-value">{{ password }}</span>
                            </div>
                        </div>
                        <div style="text-align: center; margin: 30px 0;">
                            <a href="/agent-login" style="display: inline-block; background-color: #1a1a1a; color: #ffffff !important; padding: 15px 40px; border-radius: 8px; text-decoration: none; font-weight: 700;">Log In to Your Dashboard</a>
                        </div>
                        <div class="signature">
                            <p>Warm regards,<br><strong>Team PadosiAgent</strong></p>
                        </div>
                    </div>
                    <div class="footer">
                        <p style="margin: 0;">&copy; 2026 PadosiAgent ServTech Private Limited. All rights reserved.</p>
                    </div>
                </div>
            </td>
        </tr>
    </table>
</body>
</html>""",
        'invoice': """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{{ invoice.invoice_number|default:'Invoice' }}</title>
    <style>
        @page { margin: 0.5cm; }
        body { font-family: sans-serif; color: #2a2a2a; margin: 0; padding: 10px 20px; font-size: 13.5px; line-height: 1.4; }
        table { width: 100%; border-collapse: collapse; }
        td, th { vertical-align: top; }
        .invoice-header { margin-bottom: 20px; }
        .company-logo { max-width: 160px; height: auto; }
        .company-details { text-align: right; font-size: 13px; color: #6a6a6a; }
        .company-details strong { font-size: 20px; color: #18529d; display: block; margin-bottom: 5px; }
        .header-divider { border-top: 2px solid #18529d; margin: 15px 0 20px; opacity: 0.8; }
        .bill-to h4, .invoice-meta h4 { margin: 0 0 10px; font-size: 13px; text-transform: uppercase; color: #6a6a6a; }
        .bill-to p, .invoice-meta p { margin: 0 0 5px; }
        .invoice-meta { text-align: right; }
        .status-badge { display: inline-block; padding: 4px 12px; background-color: #e6f4ea; color: #1d724f; border: 1px solid #cce8d6; border-radius: 4px; font-weight: bold; }
        .invoice-table th { background-color: #f8f9fa; color: #18529d; font-weight: bold; text-align: left; padding: 12px 15px; border-bottom: 2px solid #18529d; }
        .invoice-table td { padding: 8px 12px; border-bottom: 1px solid #e5e5e5; }
        .totals-table { width: 300px; float: right; margin-top: 20px; }
        .totals-table td { padding: 8px 15px; }
        .total-amount { font-size: 22px; font-weight: bold; color: #18529d; background-color: #f0f5fc; padding: 10px 15px; border-radius: 6px; }
        .invoice-footer { clear: both; margin-top: 40px; padding-top: 15px; border-top: 1px solid #e5e5e5; text-align: center; color: #6a6a6a; }
    </style>
</head>
<body>
    <table class="invoice-header">
        <tr>
            <td>
                <h2 style="color: #18529d; margin: 0;">PadosiAgent</h2>
            </td>
            <td class="company-details">
                <strong>PadosiAgent ServTech Private Limited</strong>
                <p>support@padosiagent.com | +91 9876543210</p>
            </td>
        </tr>
    </table>
    <div class="header-divider"></div>
    <table class="invoice-info-section">
        <tr>
            <td class="bill-to" style="width: 50%;">
                <h4>Bill To</h4>
                <p><strong>{{ invoice.agent_name|default:'Agent Name' }}</strong></p>
                <p>{{ invoice.agent_email|default:'agent@example.com' }}</p>
            </td>
            <td class="invoice-meta">
                <h4>Invoice Details</h4>
                <p>Invoice Number: <strong>{{ invoice.invoice_number|default:'INV-2026-0001' }}</strong></p>
                <p>Invoice Date: {{ invoice.created_at|default:'25 Jun, 2026' }}</p>
            </td>
        </tr>
    </table>
    <table class="invoice-table">
        <thead>
            <tr>
                <th style="width: 5%;">#</th>
                <th>Service Details</th>
                <th style="text-align: right; width: 25%;">Amount</th>
            </tr>
        </thead>
        <tbody>
            {% for item in items %}
            <tr>
                <td>{{ forloop.counter }}</td>
                <td>
                    <p style="margin: 0; font-weight: bold;">{{ item.name }}</p>
                    <p style="margin: 0; font-size: 11px; color: #6a6a6a;">{{ item.description }}</p>
                </td>
                <td style="text-align: right;">&#8377;{{ item.amount }}</td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
</body>
</html>"""
    }
    with open(path, 'w', encoding='utf-8') as f:
        f.write(defaults[template_type].strip())


@admin_login_required
def templates(request):
    template_type = request.GET.get('type', 'invoice')
    path = _get_template_path(template_type)
    _initialize_default_template(template_type, path)
    
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
        
    return render(request, 'admin/settings/templates.html', {
        'content': content,
        'type': template_type
    })


@admin_login_required
def update_templates(request):
    if request.method == 'POST':
        template_type = request.POST.get('type')
        content = request.POST.get('file_content')
        path = _get_template_path(template_type)
        
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
            
        messages.success(request, f"{template_type.replace('_', ' ').capitalize()} template updated successfully.")
        return redirect(f"/admin/settings/templates/?type={template_type}")
    
    from django.http import Http404
    raise Http404()


