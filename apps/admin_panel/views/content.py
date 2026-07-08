from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse
from apps.home.models.site_setting import SiteSetting
from apps.home.models.faq import Faq
from apps.admin_panel.models.admin_activity_log import AdminActivityLog
from apps.admin_panel.views.dashboard import _get_admin_from_session


# ─── ABOUT ───────────────────────────────────────────────────────────────────

def about(request):
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return redirect('admin_login')

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
    return render(request, 'admin/content/about.html', {'about': about_content})


def update_about(request):
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return redirect('admin_login')

    if request.method == 'POST':
        about_data = {
            'banner_title':    request.POST.get('banner_title', 'About Us'),
            'banner_subtitle': request.POST.get('banner_subtitle', 'Connecting you with trusted insurance agents in your neighborhood'),
            'who_we_are':      request.POST.get('who_we_are', ''),
            'why_we_exist':    request.POST.get('why_we_exist', ''),
            'what_we_do':      request.POST.get('what_we_do', ''),
            'vision':          request.POST.get('vision', ''),
            'mission':         request.POST.get('mission', ''),
            'commitment':      request.POST.get('commitment', ''),
        }
        SiteSetting.set_value('about_page_content', about_data, 'about')
        AdminActivityLog.log('Update about page content', 'SiteSetting', request=request)
        messages.success(request, 'About page updated successfully.')
        return redirect('admin_content_about')

    return redirect('admin_content_about')


# ─── FAQs ────────────────────────────────────────────────────────────────────

def faqs(request):
    """Admin FAQ manager — list all FAQs + page header settings."""
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return redirect('admin_login')

    faq_content = SiteSetting.get_value('faq_page_content', {
        'title':    "Got Questions? I've Got Your Answers",
        'subtitle': 'Everything you need to know before finding your PadosiAgent',
    })
    all_faqs = list(Faq.objects.all().order_by('sort_order', 'id'))
    return render(request, 'admin/content/faqs.html', {
        'faq_content':    faq_content,
        'faqs':           all_faqs,
        'active_count':   sum(1 for f in all_faqs if f.is_active),
        'hidden_count':   sum(1 for f in all_faqs if not f.is_active),
        'faq_categories': Faq.CATEGORY_CHOICES,
    })


def faq_settings_update(request):
    """Save FAQ page header (title + subtitle) to site_settings."""
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return redirect('admin_login')

    if request.method == 'POST':
        data = {
            'title':    request.POST.get('title', "Got Questions? I've Got Your Answers"),
            'subtitle': request.POST.get('subtitle', 'Everything you need to know before finding your PadosiAgent'),
        }
        SiteSetting.set_value('faq_page_content', data, 'faq')
        AdminActivityLog.log('Update FAQ page header', 'SiteSetting', request=request)
        messages.success(request, 'FAQ page header saved successfully.')
    return redirect('admin_content_faqs')


def faq_store(request):
    """Create a new FAQ entry."""
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return redirect('admin_login')

    if request.method == 'POST':
        question   = request.POST.get('question', '').strip()
        answer     = request.POST.get('answer', '').strip()
        category   = request.POST.get('category', 'general')
        sort_order = Faq.objects.count()  # append at end

        if question and answer:
            faq = Faq.objects.create(
                question=question,
                answer=answer,
                category=category,
                sort_order=sort_order,
                is_active=True,
            )
            AdminActivityLog.log(f'Added FAQ #{faq.id}', 'Faq', request=request)
            messages.success(request, 'FAQ added successfully.')
        else:
            messages.error(request, 'Question and Answer are required.')

    return redirect('admin_content_faqs')


def faq_update(request, faq_id):
    """Inline-edit an existing FAQ (question, answer, category)."""
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return redirect('admin_login')

    if request.method == 'POST':
        faq_obj  = get_object_or_404(Faq, id=faq_id)
        question = request.POST.get('question', '').strip()
        answer   = request.POST.get('answer', '').strip()
        category = request.POST.get('category', faq_obj.category)

        if question and answer:
            faq_obj.question = question
            faq_obj.answer   = answer
            faq_obj.category = category
            faq_obj.save()
            AdminActivityLog.log(f'Updated FAQ #{faq_id}', 'Faq', request=request)
            messages.success(request, 'FAQ updated successfully.')
        else:
            messages.error(request, 'Question and Answer are required.')

    return redirect('admin_content_faqs')


def faq_toggle(request):
    """Toggle is_active via AJAX — returns JSON {success, is_active}."""
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return JsonResponse({'success': False}, status=401)

    if request.method == 'POST':
        faq_id         = request.POST.get('id')
        current_status = request.POST.get('current_status') == 'true'
        faq_obj = get_object_or_404(Faq, id=faq_id)
        faq_obj.is_active = not current_status
        faq_obj.save()
        AdminActivityLog.log(f'Toggled FAQ #{faq_id} → {"active" if faq_obj.is_active else "hidden"}', 'Faq', request=request)
        return JsonResponse({'success': True, 'is_active': faq_obj.is_active})
    return JsonResponse({'success': False}, status=400)


# ─── CONTACT ─────────────────────────────────────────────────────────────────

def contact(request):
    """Admin Contact page editor — banner title + section text."""
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return redirect('admin_login')

    contact_content = SiteSetting.get_value('contact_page_content', {
        'banner_title':    'Contact Us',
        'section_title':   'Secure Your Family Future With us.',
        'section_subtitle': "Have questions or need assistance? Reach out to us today for expert guidance on securing your family's future.",
    })
    return render(request, 'admin/content/contact.html', {'contact': contact_content})


def update_contact(request):
    """Save contact page content to site_settings."""
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return redirect('admin_login')

    if request.method == 'POST':
        data = {
            'banner_title':    request.POST.get('banner_title', 'Contact Us'),
            'section_title':   request.POST.get('section_title', ''),
            'section_subtitle': request.POST.get('section_subtitle', ''),
        }
        SiteSetting.set_value('contact_page_content', data, 'contact')
        AdminActivityLog.log('Update contact page content', 'SiteSetting', request=request)
        messages.success(request, 'Contact page content saved successfully.')
        return redirect('admin_content_contact')

    return redirect('admin_content_contact')


# ─── BANNER SLIDES ────────────────────────────────────────────────────────────

_DEFAULT_BANNERS = [
    {
        'title': 'Buy/Port/Renew Insurance',
        'subtitle': 'Find your trusted local PadosiAgent',
        'cta_text': 'Find Your PadosiAgent',
        'cta_link': '/find-agents?ServiceType=New%20Policy&openFilter=1',
        'bg_class': 'banner-new-policy',
        'visible': True,
    },
    {
        'title': 'Claim Assistance',
        'subtitle': 'Need help with your insurance claim?',
        'cta_text': 'Find Claims Expert',
        'cta_link': '/find-agents?ServiceType=Claim%20Assistance&openFilter=1',
        'bg_class': 'banner-claim-assistance',
        'visible': True,
    },
    {
        'title': 'Review My Policy',
        'subtitle': "Unsure if you're covered?",
        'cta_text': 'Find Insurance Expert',
        'cta_link': '/find-agents?ServiceType=Policy%20Review&openFilter=1',
        'bg_class': 'banner-policy-review',
        'visible': True,
    },
]


def banners(request):
    """Admin Banner Slides editor — reads/writes homepage_banners in site_settings."""
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return redirect('admin_login')

    banner_list = SiteSetting.get_value('homepage_banners', _DEFAULT_BANNERS)
    # Ensure each slide has all expected keys (safe defaults)
    for slide in banner_list:
        slide.setdefault('title', '')
        slide.setdefault('subtitle', '')
        slide.setdefault('cta_text', '')
        slide.setdefault('cta_link', '')
        slide.setdefault('bg_class', '')
        slide.setdefault('visible', True)

    return render(request, 'admin/content/banners.html', {'banners': banner_list})


def update_banners(request):
    """Save banner slides submitted from the banners editor form."""
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return redirect('admin_login')

    if request.method == 'POST':
        titles     = request.POST.getlist('title[]')
        subtitles  = request.POST.getlist('subtitle[]')
        cta_texts  = request.POST.getlist('cta_text[]')
        cta_links  = request.POST.getlist('cta_link[]')
        bg_classes = request.POST.getlist('bg_class[]')

        banner_list = []
        for i, title in enumerate(titles):
            # visible[i] checkbox — present means True, absent means False
            visible_key = f'visible[{i}]'
            banner_list.append({
                'title':    title,
                'subtitle': subtitles[i] if i < len(subtitles) else '',
                'cta_text': cta_texts[i] if i < len(cta_texts) else '',
                'cta_link': cta_links[i] if i < len(cta_links) else '',
                'bg_class': bg_classes[i] if i < len(bg_classes) else '',
                'visible':  visible_key in request.POST,
            })

        SiteSetting.set_value('homepage_banners', banner_list, 'homepage')
        AdminActivityLog.log('Updated homepage banner slides', 'SiteSetting', request=request)
        messages.success(request, 'Banner slides updated successfully.')

    return redirect('admin_content_banners')


# ─── PLANS & PRICING ──────────────────────────────────────────────────────────

_DEFAULT_PRICING = {
    'starter': {
        'name': "Starter's Plan",
        'full_price': 2359,
        'promo_price': 589,
        'description': 'Perfect for New Agents',
        'badge': 'STANDARD',
    },
    'professional': {
        'name': "Professional's Plan",
        'full_price': 8258,
        'promo_price': 2359,
        'description': 'For Established Professionals',
        'badge': 'RECOMMENDED',
    },
    'promo_discount_label': 'Partner Promo Applied! Once in a lifetime offer!',
    'standard_label': 'Get started with our standard partner plans',
}


def plans(request):
    """Admin Plans & Pricing editor — reads/writes pricing_config in site_settings."""
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return redirect('admin_login')

    pricing = SiteSetting.get_value('pricing_config', _DEFAULT_PRICING)
    # Ensure nested dicts exist with defaults
    pricing.setdefault('starter', _DEFAULT_PRICING['starter'])
    pricing.setdefault('professional', _DEFAULT_PRICING['professional'])
    pricing.setdefault('promo_discount_label', _DEFAULT_PRICING['promo_discount_label'])
    pricing.setdefault('standard_label', _DEFAULT_PRICING['standard_label'])

    return render(request, 'admin/content/plans.html', {'pricing': pricing})


def update_plans(request):
    """Save plans & pricing config submitted from the plans editor form."""
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return redirect('admin_login')

    if request.method == 'POST':
        pricing = {
            'starter': {
                'name':        request.POST.get('starter_name', "Starter's Plan"),
                'full_price':  int(request.POST.get('starter_full_price', 2359) or 2359),
                'promo_price': int(request.POST.get('starter_promo_price', 589) or 589),
                'description': request.POST.get('starter_description', 'Perfect for New Agents'),
                'badge':       request.POST.get('starter_badge', 'STANDARD'),
            },
            'professional': {
                'name':        request.POST.get('professional_name', "Professional's Plan"),
                'full_price':  int(request.POST.get('professional_full_price', 8258) or 8258),
                'promo_price': int(request.POST.get('professional_promo_price', 2359) or 2359),
                'description': request.POST.get('professional_description', 'For Established Professionals'),
                'badge':       request.POST.get('professional_badge', 'RECOMMENDED'),
            },
            'promo_discount_label': request.POST.get('promo_discount_label', 'Partner Promo Applied! Once in a lifetime offer!'),
            'standard_label':       request.POST.get('standard_label', 'Get started with our standard partner plans'),
        }

        SiteSetting.set_value('pricing_config', pricing, 'pricing')
        AdminActivityLog.log('Updated agent pricing plans', 'SiteSetting', request=request)
        messages.success(request, 'Pricing configuration updated successfully.')

    return redirect('admin_content_plans')
