from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse
from apps.home.models.site_setting import SiteSetting
from apps.home.models.faq import Faq
from apps.admin_panel.models.admin_activity_log import AdminActivityLog
from apps.admin_panel.decorators import admin_login_required


# ─── ABOUT ───────────────────────────────────────────────────────────────────

@admin_login_required
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
    return render(request, 'admin/content/about.html', {'about': about_content})


@admin_login_required
def update_about(request):
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
        return redirect('admin_panel:content_about')

    return redirect('admin_panel:content_about')


# ─── FAQs ────────────────────────────────────────────────────────────────────

@admin_login_required
def faqs(request):
    """Admin FAQ manager — list all FAQs + page header settings."""
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


@admin_login_required
def faq_settings_update(request):
    """Save FAQ page header (title + subtitle) to site_settings."""
    if request.method == 'POST':
        data = {
            'title':    request.POST.get('title', "Got Questions? I've Got Your Answers"),
            'subtitle': request.POST.get('subtitle', 'Everything you need to know before finding your PadosiAgent'),
        }
        SiteSetting.set_value('faq_page_content', data, 'faq')
        AdminActivityLog.log('Update FAQ page header', 'SiteSetting', request=request)
        messages.success(request, 'FAQ page header saved successfully.')
    return redirect('admin_panel:content_faqs')


@admin_login_required
def faq_store(request):
    """Create a new FAQ entry."""
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

    return redirect('admin_panel:content_faqs')


@admin_login_required
def faq_update(request, faq_id):
    """Inline-edit an existing FAQ (question, answer, category)."""
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

    return redirect('admin_panel:content_faqs')


@admin_login_required
def faq_delete(request, faq_id):
    """Delete a FAQ entry."""
    if request.method == 'POST':
        faq_obj = get_object_or_404(Faq, id=faq_id)
        faq_obj.delete()
        AdminActivityLog.log(f'Deleted FAQ #{faq_id}', 'Faq', request=request)
        messages.success(request, 'FAQ deleted.')
    return redirect('admin_panel:content_faqs')


@admin_login_required
def faq_toggle(request):
    """Toggle is_active via AJAX — returns JSON {success, is_active}."""
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

@admin_login_required
def contact(request):
    """Admin Contact page editor — banner title + section text."""
    contact_content = SiteSetting.get_value('contact_page_content', {
        'banner_title':    'Contact Us',
        'section_title':   'Secure Your Family Future With us.',
        'section_subtitle': "Have questions or need assistance? Reach out to us today for expert guidance on securing your family's future.",
    })
    return render(request, 'admin/content/contact.html', {'contact': contact_content})


@admin_login_required
def update_contact(request):
    """Save contact page content to site_settings."""
    if request.method == 'POST':
        data = {
            'banner_title':    request.POST.get('banner_title', 'Contact Us'),
            'section_title':   request.POST.get('section_title', ''),
            'section_subtitle': request.POST.get('section_subtitle', ''),
        }
        SiteSetting.set_value('contact_page_content', data, 'contact')
        AdminActivityLog.log('Update contact page content', 'SiteSetting', request=request)
        messages.success(request, 'Contact page content saved successfully.')
        return redirect('admin_panel:content_contact')

    return redirect('admin_panel:content_contact')
