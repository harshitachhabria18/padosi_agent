from django.shortcuts import render, redirect
from django.http import JsonResponse
from apps.admin_panel.views.dashboard import _get_admin_from_session
from apps.home.models.site_setting import SiteSetting


def coming_soon_index(request):
    """Admin page to manage Coming Soon content for Starter and Professional plan agents."""
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return redirect('admin_login')

    coming_soon_starter_html = SiteSetting.get_value('coming_soon_starter_html', '') or ''
    coming_soon_professional_html = SiteSetting.get_value('coming_soon_professional_html', '') or ''

    return render(request, 'admin/coming_soon/index.html', {
        'coming_soon_starter_html': coming_soon_starter_html,
        'coming_soon_professional_html': coming_soon_professional_html,
    })


def save_coming_soon(request):
    """Save Coming Soon HTML content for a given plan type (starter or professional)."""
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return JsonResponse({'success': False, 'message': 'Unauthorized'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request method'}, status=405)

    plan = request.POST.get('plan', '').strip().lower()
    html_content = request.POST.get('html_content', '').strip()

    if plan not in ('starter', 'professional'):
        return JsonResponse(
            {'success': False, 'message': 'Invalid plan type. Must be starter or professional.'},
            status=400
        )

    setting_key = f'coming_soon_{plan}_html'
    SiteSetting.set_value(setting_key, html_content, group='coming_soon')

    plan_label = 'Starter' if plan == 'starter' else 'Professional'
    return JsonResponse({
        'success': True,
        'message': f'{plan_label} Plan Coming Soon content saved successfully!'
    })
