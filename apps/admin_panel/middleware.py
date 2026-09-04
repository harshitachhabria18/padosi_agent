import re
import json
import logging
import urllib.request
from django.http import HttpResponseForbidden, JsonResponse
from django.utils import timezone
from django.conf import settings
from django.template.loader import render_to_string

from apps.admin_panel.views.security import BlockedIp, SecurityThreatLog
from apps.admin_panel.services.brevo import send_brevo_email

logger = logging.getLogger(__name__)

class ThreatMonitorMiddleware:
    """
    Web Application Firewall (WAF) and Threat Monitor Middleware.
    Mirrors Laravel's ThreatMonitorMiddleware.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # 1. Get Client IP Address
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        ip = x_forwarded_for.split(',')[0].strip() if x_forwarded_for else request.META.get('REMOTE_ADDR')

        # 2. Whitelist local/trusted IPs from ANY security checks (same as PHP)
        if ip in ['127.0.0.1', '::1']:
            return self.get_response(request)

        # 3. Check if IP is already explicitly Blocked
        if BlockedIp.objects.filter(ip_address=ip).exists():
            if request.headers.get('accept') == 'application/json' or request.path.startswith('/api/'):
                return JsonResponse({'error': 'Forbidden', 'message': 'Your IP address has been blocked.'}, status=403)
            return HttpResponseForbidden('Your IP address has been blocked due to suspicious activity.')

        # 4. Identify potential Malicious Payloads (Basic WAF functionality)
        url_to_check = request.build_absolute_uri()
        
        # Check if user is an authenticated Admin (to allow safe HTML saving)
        is_admin = False
        try:
            from apps.admin_panel.views.dashboard import _get_admin_from_session
            if _get_admin_from_session(request):
                is_admin = True
        except Exception:
            pass
        
        safe_html_fields = ['file_content', 'content', 'html_content', 'template', 'email_body', 'email_header', 'html_code']
        
        # Collect request input fields
        payload_dict = {}
        if request.method in ['POST', 'PUT', 'PATCH']:
            # Try to load POST parameters
            for k, v in request.POST.items():
                if is_admin and k in safe_html_fields:
                    payload_dict[k] = "[HTML_CONTENT_REDACTED_FOR_WAF]"
                else:
                    payload_dict[k] = v
            # If JSON body, try parsing it
            try:
                if request.content_type == 'application/json' and request.body:
                    json_data = json.loads(request.body.decode('utf-8', errors='ignore'))
                    if isinstance(json_data, dict):
                        for k, v in json_data.items():
                            if is_admin and k in safe_html_fields:
                                payload_dict[k] = "[HTML_CONTENT_REDACTED_FOR_WAF]"
                            else:
                                payload_dict[k] = v
            except Exception:
                pass
        
        # Include GET parameters too
        for k, v in request.GET.items():
            payload_dict[k] = v

        input_str = json.dumps(payload_dict)

        # Hardened WAF regex patterns (Identical to Laravel's signatures)
        patterns = {
            'SQL Injection': r"(union select\s|select\s+\*\s+from|insert\s+into|update\s+\w+\s+set|'\s*or\s*'1'\s*=\s*'1|sleep\(\d+\)|benchmark\s*\(|group_concat|information_schema)",
            'Cross Site Scripting (XSS)': r"(<script\b[^>]*>|javascript:|onerror=|onload=|eval\(|setTimeout\(|setInterval\(|alert\(|document\.cookie|document\.domain|window\.location)",
            'Path Traversal / LFI': r"(\.\.\/|\.\.\\\\|\/etc\/passwd|\/etc\/shadow|\/etc\/group|\/etc\/hosts|\/proc\/self|php:\/\/filter|php:\/\/input|expect:\/\/)",
            'RCE / Shell Injection': r"(system\(|exec\(|passthru\(|shell_exec\(|proc_open\(|pcntl_exec\(|python\s+-c|perl\s+-e|ruby\s+-e|bash\s+-i|nc\s+-e)",
            'SSRF / Metadata API': r"(169\.254\.169\.254|metadata\.google\.internal|\/latest\/meta-data\/)",
            'XML External Entity (XXE)': r"(<!ENTITY\s+|SYSTEM\s+[\"']|PUBLIC\s+[\"'])",
            'Server-Side Template Injection': r"({{\s*[\s\S]*\s*}}|{%\s*[\s\S]*\s*%}|\[\[\s*[\s\S]*\s*\]\])",
            'CRLF / Header Injection': r"(\%0d\%0a|\r\n|Set-Cookie:|Content-Type:)",
        }

        matched_type = None
        for threat_type, pattern in patterns.items():
            if re.search(pattern, input_str, re.IGNORECASE) or re.search(pattern, url_to_check, re.IGNORECASE):
                matched_type = threat_type
                break

        if matched_type:
            # 5. Profile Hacker
            hacker_name = 'GUEST / ANONYMOUS'
            hacker_email = None
            hacker_mobile = None

            # Get admin credentials from session if present
            try:
                if hasattr(request, 'session') and request.session and request.session.get('admin_id'):
                    hacker_name = f"Admin: {request.session.get('admin_name', 'N/A')}"
                    hacker_email = request.session.get('admin_email')
            except Exception:
                pass

            # Fallback to general django auth user if present
            if hacker_name == 'GUEST / ANONYMOUS' and hasattr(request, 'user') and request.user.is_authenticated:
                hacker_name = request.user.get_full_name() or request.user.username
                hacker_email = request.user.email
                # Try to fetch mobile from Client profile if it exists
                try:
                    from apps.agents.models import Client
                    client = Client.objects.filter(user=request.user).first()
                    if client:
                        hacker_mobile = client.mobile
                except Exception:
                    pass

            # 6. Retrieve Location / Geo-IP Details
            location = "Unknown Location"
            isp = "Unknown ISP"
            try:
                # Safe HTTP request using Python's standard library
                with urllib.request.urlopen(f"http://ip-api.com/json/{ip}?fields=status,country,regionName,city,isp", timeout=2.0) as conn:
                    geo_data = json.loads(conn.read().decode('utf-8'))
                    if geo_data.get('status') == 'success':
                        location = f"{geo_data.get('city', '')}, {geo_data.get('regionName', '')}, {geo_data.get('country', '')}".strip(', ')
                        isp = geo_data.get('isp', 'N/A')
                    else:
                        # Fallback to ipwho.is if ip-api fails
                        with urllib.request.urlopen(f"https://ipwho.is/{ip}", timeout=2.0) as conn2:
                            geo_data2 = json.loads(conn2.read().decode('utf-8'))
                            if geo_data2.get('success'):
                                location = f"{geo_data2.get('city', '')}, {geo_data2.get('region', '')}, {geo_data2.get('country', '')}".strip(', ')
                                isp = geo_data2.get('connection', {}).get('isp', 'N/A')
            except Exception as e:
                logger.error(f"ThreatMonitorMiddleware: Geolocation lookup failed: {e}")

            # 7. Auto-Block check (3 offenses in last 1 hour)
            one_hour_ago = timezone.now() - timezone.timedelta(hours=1)
            recent_offenses = SecurityThreatLog.objects.filter(
                ip_address=ip,
                created_at__gte=one_hour_ago
            ).count()

            is_auto_blocked = False
            # If they already have 2 offenses, this current offense is the 3rd, triggering auto-ban
            if recent_offenses >= 2:
                BlockedIp.objects.get_or_create(
                    ip_address=ip,
                    defaults={'reason': f"Auto-blocked by Threat Monitor due to recurring malicious payloads ({matched_type})."}
                )
                is_auto_blocked = True

            # 8. Save Security Threat Log Record
            SecurityThreatLog.objects.create(
                ip_address=ip,
                event_type=matched_type,
                hacker_name=hacker_name,
                hacker_email=hacker_email,
                hacker_mobile=hacker_mobile,
                location=location,
                isp=isp,
                url=url_to_check,
                payload=input_str[:1000],
                user_agent=request.META.get('HTTP_USER_AGENT', '')
            )

            # 9. Send Security Alert Email to Admin via Brevo service
            try:
                threat_context = {
                    'ip_address': ip,
                    'event_type': matched_type,
                    'timestamp': timezone.now().strftime('%d %b %Y, %I:%M %p'),
                    'url': url_to_check,
                    'payload': input_str[:500],
                    'user_agent': request.META.get('HTTP_USER_AGENT', ''),
                    'hacker_name': hacker_name,
                    'hacker_email': hacker_email,
                    'location': location,
                    'isp': isp,
                    'is_blocked': is_auto_blocked
                }
                html_body = render_to_string('emails/security_threat.html', {'threat': threat_context})
                send_brevo_email(
                    to_email='ashisprajapati131@gmail.com',
                    to_name='Admin',
                    subject='⚠️ SECURITY ALERT: Malicious Activity Detected on PadosiAgent',
                    html_content=html_body
                )
            except Exception as e:
                logger.error(f"ThreatMonitorMiddleware: Failed to send security email alert: {e}")

            # Return 403 response
            if request.headers.get('accept') == 'application/json' or request.path.startswith('/api/'):
                return JsonResponse({'error': 'Malicious Activity Detected.'}, status=403)
            return HttpResponseForbidden('Malicious Activity Detected.')

        return self.get_response(request)


from django.shortcuts import redirect
from apps.home.services.portal_messages import PORTAL_ADMIN, portal_error

class AdminIpWhitelistMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path.rstrip('/')
        if path.startswith('/admin') or path.startswith('/padosi-admin') or path.startswith('/django-admin'):
            x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
            ip = x_forwarded_for.split(',')[0].strip() if x_forwarded_for else request.META.get('REMOTE_ADDR')
            
            # Fetch whitelist from settings or fallback
            whitelist = getattr(settings, 'ADMIN_WHITELIST_IPS', [])
            if not whitelist:
                # Laravel fallback
                whitelist = ['127.0.0.1', '::1', '152.58.37.11', '152.58.37.205', '171.61.166.173', '152.58.35.25', '49.36.89.253', '152.59.35.126', '152.58.36.18', '100.83.86.57']
            
            if ip not in whitelist:
                logger.warning(f"Admin IP Whitelist: Blocked request from unauthorized IP: {ip} for path {request.path}")
                return HttpResponseForbidden("Access Denied: IP address not authorized.")
                
        return self.get_response(request)


class IsolateAdminAgentSessionsMiddleware:
    """
    A Django-authenticated agent must not keep an admin session_token cookie.
    That cookie is what AdminPermissionMiddleware uses to grant /admin access.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path.rstrip('/')
        if path in ['/admin', '/admin/login', '/admin/login/post', '/admin/logout']:
            return self.get_response(request)

        token = request.COOKIES.get('session_token')
        user = getattr(request, 'user', None)
        if (
            token
            and user is not None
            and getattr(user, 'is_authenticated', False)
        ):
            from apps.agents.models import Agent
            if Agent.objects.filter(user_id=user.pk).exists():
                from apps.admin_panel.views.dashboard import invalidate_admin_session_token
                invalidate_admin_session_token(token)
                request.COOKIES.pop('session_token', None)
                response = self.get_response(request)
                response.delete_cookie('session_token')
                return response
        return self.get_response(request)


class AdminPermissionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path.rstrip('/')
        if not (path.startswith('/admin') or path.startswith('/padosi-admin')):
            return self.get_response(request)

        # Allow auth endpoints without session or permissions
        if path in ['/admin', '/admin/login', '/admin/login/post', '/admin/logout']:
            return self.get_response(request)

        from apps.admin_panel.views.dashboard import _get_admin_from_session
        from apps.admin_panel.models.admin_auth import Admin
        
        admin_id = _get_admin_from_session(request)
        if not admin_id:
            import logging
            logging.getLogger(__name__).error(f"Unauthorized admin access from path: {request.path}")
            # For AJAX / JSON requests, return a clean 403 JSON — never add flash messages
            # that would leak into the agent login page after logout.
            is_ajax = (
                request.headers.get('X-Requested-With') == 'XMLHttpRequest'
                or 'application/json' in request.headers.get('Accept', '')
                or request.content_type == 'application/json'
            )
            if is_ajax:
                from django.http import JsonResponse
                return JsonResponse({'success': False, 'message': 'Unauthorized. Please sign in to the admin panel.'}, status=403)
            portal_error(request, "Please sign in to access the admin panel.", PORTAL_ADMIN)
            return redirect('admin_login_page')

        try:
            admin = Admin.objects.get(pk=admin_id)
        except Admin.DoesNotExist:
            from apps.admin_panel.views.dashboard import admin_logout
            is_ajax = (
                request.headers.get('X-Requested-With') == 'XMLHttpRequest'
                or 'application/json' in request.headers.get('Accept', '')
                or request.content_type == 'application/json'
            )
            if is_ajax:
                from django.http import JsonResponse
                return JsonResponse({'success': False, 'message': 'Admin account not found.'}, status=403)
            portal_error(request, "Admin account not found. Logged out.", PORTAL_ADMIN)
            return admin_logout(request)

        # Super admins have full access to everything
        if admin.role == 'super':
            request.admin_user = admin
            return self.get_response(request)

        # Helper to redirect to first allowed route or log out
        def get_redirect_response(message):
            allowed_route = self.get_first_allowed_route(admin)
            if allowed_route:
                try:
                    from django.urls import reverse
                    url = reverse(allowed_route)
                    portal_error(request, message, PORTAL_ADMIN)
                    return redirect(url)
                except Exception:
                    pass
            from apps.admin_panel.views.dashboard import admin_logout
            portal_error(request, "Your staff account has no access permissions. Logged out.", PORTAL_ADMIN)
            return admin_logout(request)

        # 1. DELETE ACTION PROTECTION:
        # Staff admins can never delete records.
        try:
            from django.urls import resolve
            url_name = resolve(request.path_info).url_name
        except Exception:
            url_name = ''
        is_delete_request = (
            request.method == 'DELETE' or
            'delete' in url_name.lower() or
            'destroy' in url_name.lower() or
            'delete' in request.path.lower()
        )

        if is_delete_request:
            if request.headers.get('accept') == 'application/json' or request.path.startswith('/api/'):
                return JsonResponse({'success': False, 'message': 'Unauthorized. Staff accounts do not have delete permissions.'}, status=403)
            return get_redirect_response('Unauthorized. Staff accounts do not have delete permissions.')

        # 2. ADMIN USER / STAFF MANAGEMENT PROTECTION:
        # Staff admins can never access admin management routes.
        if url_name.startswith('admin_admins') or url_name.startswith('admin_staff') or '/admin/admins/' in request.path or '/admin/staff/' in request.path:
            if request.headers.get('accept') == 'application/json' or request.path.startswith('/api/'):
                return JsonResponse({'success': False, 'message': 'Unauthorized. Only Super Admins can manage administrator accounts.'}, status=403)
            return get_redirect_response('Unauthorized. Only Super Admins can manage administrator accounts.')

        # 3. SECTION/MODULE PERMISSION CHECK (exact lookup, deny-by-default):
        # get_required_permission() does a direct dict lookup — no prefix matching.
        # If url_name is a non-empty string not in the map, staff admins are denied.
        # If url_name is empty (resolver_match is None → genuine 404), pass through.
        required_permission = self.get_required_permission(url_name)
        if required_permission is None:
            if url_name:
                # Known URL pattern but not in our permission map → deny by default.
                if request.headers.get('accept') == 'application/json' or request.path.startswith('/api/'):
                    return JsonResponse({'success': False, 'message': 'Unauthorized. Access to this section is not permitted for your staff account.'}, status=403)
                return get_redirect_response('Access to this section is not permitted for your staff account.')
            # url_name is empty → unresolved URL; let Django render the 404.
            return self.get_response(request)

        permissions_list = admin.permissions if isinstance(admin.permissions, list) else []
        
        has_permission = required_permission in permissions_list
        if required_permission == 'approvals':
            has_permission = 'approvals_awaiting_verification' in permissions_list or 'approvals_missing_licenses' in permissions_list

        if not has_permission:
            if request.headers.get('accept') == 'application/json' or request.path.startswith('/api/'):
                return JsonResponse({'success': False, 'message': 'Unauthorized. You do not have permission to access this module.'}, status=403)
            perm_name = required_permission.replace('_', ' ').title()
            return get_redirect_response(f'Unauthorized. You do not have permission to access the {perm_name} module.')

        request.admin_user = admin
        return self.get_response(request)

    def get_required_permission(self, url_name):
        """
        Returns the canonical permission key required to access the given URL name,
        or None if url_name is empty or not in the map.

        Uses EXACT url_name matching — no startswith prefix matching — to eliminate
        prefix-overlap bugs (e.g. 'admin_agents' vs 'admin_agents_approvals').

        When None is returned for a non-empty url_name the __call__ deny-by-default
        block redirects staff admins instead of silently allowing access.

        Intentionally excluded from this map (handled by other rules or not admin-gated):
          - Auth routes (admin_login, admin_login_page, admin_login_post, admin_logout)
          - Admin-management routes (admin_admins_*) — caught by rule #2
          - Public routes (qr_download)
        """
        if not url_name:
            return None
        return {
            # ── Dashboard ─────────────────────────────────────────────────
            'admin_dashboard':                          'dashboard',
            # ── Agents ────────────────────────────────────────────────────
            'admin_agents':                             'agents',
            'admin_agents_manage':                      'agents',
            'admin_agents_manage_alt':                  'agents',
            'admin_agents_toggle_status':               'agents',
            'admin_agents_update_badge':                'agents',
            'admin_agents_update_irdai_license':        'agents',
            'admin_agents_save_notes':                  'agents',
            'admin_agents_bulk_action':                 'agents',
            'admin_agents_delete':                      'agents',
            'admin_agents_irdai_verify':                'agents',
            'admin_agents_amfi_verify':                 'agents',
            'admin_agents_update_visibility':           'agents',
            'admin_agents_update_achievement_limit':    'agents',
            'admin_agents_update_plan':                 'agents',
            'admin_agents_toggle_review_approval':      'agents',
            'admin_agents_update_profile':              'agents',
            'admin_agents_get_agent_json':              'agents',
            'admin_agents_get_edit_logs':               'agents',
            'admin_agents_edit_profile':                'agents',
            'admin_agents_full_update_profile':         'agents',
            'admin_agents_verify_pending_payment':      'agents',
            # ── Approvals / Pending / Blacklist ───────────────────────────
            'admin_agents_approvals':                   'approvals',
            'admin_agents_pending_registrations':       'pending_registrations',
            'admin_blacklisted_agents':                 'blacklisted_agents',
            'ajax_blacklist_approve':                   'approvals',
            'ajax_blacklist_confirm':                   'approvals',
            'ajax_blacklist_remove':                    'approvals',
            # ── Distributors ──────────────────────────────────────────────
            'admin_distributors':                       'distributors',
            'admin_distributors_create':                'distributors',
            'admin_distributors_store':                 'distributors',
            'admin_distributor_toggle_status':          'distributors',
            'admin_distributor_detail':                 'distributors',
            # ── Insurance Companies ───────────────────────────────────────
            'admin_insurance_index':                    'insurance',
            'admin_insurance_create':                   'insurance',
            'admin_insurance_store':                    'insurance',
            'admin_insurance_show':                     'insurance',
            'admin_insurance_toggle_status':            'insurance',
            # ── Insurance Approvals ───────────────────────────────────────
            'admin_insurance_approvals_index':                  'insurance_approvals',
            'admin_insurance_approvals_process':                'insurance_approvals',
            'admin_insurance_approvals_approve_onboarding':     'insurance_approvals',
            'admin_insurance_approvals_reject_onboarding':      'insurance_approvals',
            # ── Clients / Users ───────────────────────────────────────────
            'admin_users':                              'users',
            'admin_users_edit':                         'users',
            'admin_users_update':                       'users',
            # ── Events ────────────────────────────────────────────────────
            'admin_events_index':                       'events',
            'admin_events_show':                        'events',
            'admin_events_export':                      'events',
            # ── Subscriptions ─────────────────────────────────────────────
            'admin_subscriptions_index':                'subscriptions',
            'admin_delete_subscription':                'subscriptions',
            'admin_plans_index':                        'subscriptions',
            'admin_plan_create':                        'subscriptions',
            'admin_plan_edit':                          'subscriptions',
            'admin_plan_delete':                        'subscriptions',
            # ── Leads ─────────────────────────────────────────────────────
            'admin_leads_index':                        'leads',
            'admin_leads_update_status':                'leads',
            # ── Contacts ──────────────────────────────────────────────────
            'admin_contacts_index':                     'contacts',
            'admin_contacts_show':                      'contacts',
            'admin_contacts_update_status':             'contacts',
            'admin_contacts_delete':                    'contacts',
            # ── Reviews ───────────────────────────────────────────────────
            'admin_reviews_index':                      'reviews',
            'admin_reviews_toggle_approval':            'reviews',
            'admin_reviews_bulk_approve':               'reviews',
            'admin_reviews_delete':                     'reviews',
            # ── Notifications / Broadcast ─────────────────────────────────
            'agent_notify':                             'notifications',
            'agent_notify_send':                        'notifications',
            'agent_notify_broadcast':                   'notifications',
            'broadcast_index':                          'notifications',
            'broadcast_send':                           'notifications',
            # ── Content & CMS (incl. homepage + hero editors) ─────────────
            # Note: admin_settings_homepage* and admin_settings_hero_section*
            # map to 'content' (sidebar: Content Control), NOT 'site_settings'.
            'admin_content_about':                      'content',
            'admin_content_about_update':               'content',
            'admin_content_faqs':                       'content',
            'admin_content_faqs_settings_update':       'content',
            'admin_content_faqs_store':                 'content',
            'admin_content_faqs_update':                'content',
            'admin_content_faqs_toggle':                'content',
            'admin_content_calculators':                'content',
            'admin_content_calculators_edit':           'content',
            'admin_content_calculators_toggle':         'content',
            'admin_content_calculators_category':       'content',
            'admin_content_calculator_categories_save': 'content',
            'admin_content_calculator_categories_toggle': 'content',
            'admin_content_calculator_categories_delete': 'content',
            'admin_content_contact':                    'content',
            'admin_content_contact_update':             'content',
            'admin_content_banners':                    'content',
            'admin_content_banners_update':             'content',
            'admin_content_registration_cards':         'content',
            'admin_content_registration_cards_update':  'content',
            'admin_content_plans':                      'content',
            'admin_content_plans_update':               'content',
            'admin_content_plans_update_features':      'content',
            'admin_content_exclusive_plans_update':     'content',
            'admin_content_plans_update_unlock_rules':  'content',
            'admin_content_plans_update_qr_service':    'content',
            'admin_content_plans_update_review_growth': 'content',
            'admin_content_plans_manage_agent':         'content',
            'admin_content_plans_manage_agent_toggle':  'content',
            'admin_settings_homepage':                  'content',
            'admin_settings_homepage_update':           'content',
            'admin_settings_hero_section':              'content',
            'admin_settings_hero_section_update':       'content',
            'admin_pages_index':                        'content',
            'admin_pages_create':                       'content',
            'admin_pages_store':                        'content',
            'admin_pages_edit':                         'content',
            'admin_pages_update':                       'content',
            'admin_pages_delete':                       'content',
            # ── Revenue ───────────────────────────────────────────────────
            'admin_revenue':                            'revenue',
            'admin_search':                             'dashboard',
            # ── Invoices ──────────────────────────────────────────────────
            'admin_invoices':                           'invoices',
            'admin_invoices_create':                    'invoices',
            'admin_invoices_verify_promo':              'invoices',
            'admin_invoice_preview':                    'invoices',
            'admin_invoice_download':                   'invoices',
            'admin_invoice_save_sheet_url':             'invoices',
            'admin_invoice_sync_sheet':                 'invoices',
            'admin_invoice_open_sheet':                 'invoices',
            # ── Promo Codes ───────────────────────────────────────────────
            'admin_promo_codes':                        'promo_codes',
            'admin_promo_code_store':                   'promo_codes',
            'admin_promo_code_update':                  'promo_codes',
            'admin_promo_code_toggle_status':           'promo_codes',
            # ── Free Trial ────────────────────────────────────────────────
            'admin_free_trial':                         'free_trial',
            'admin_ft_update_config':                   'free_trial',
            'admin_ft_update_discount':                 'free_trial',
            'admin_ft_update_referral_config':          'free_trial',
            'admin_ft_force_test_credit':               'free_trial',
            'admin_ft_generate_promo':                  'free_trial',
            'admin_ft_update_promo':                    'free_trial',
            'admin_ft_toggle_promo':                    'free_trial',
            'admin_ft_delete_promo':                    'free_trial',
            'admin_ft_history':                         'free_trial',
            'admin_ft_analytics_data':                  'free_trial',
            # ── Referrals ─────────────────────────────────────────────────
            'admin_referrals_index':                    'referrals',
            'admin_referrals_toggle_code':              'referrals',
            'admin_referrals_mark_claimed':             'referrals',
            'admin_referrals_generate_missing':         'referrals',
            'admin_referrals_update_tiers':             'referrals',
            # ── Finance & Accounts ────────────────────────────────────────
            'admin_finance_index':                      'finance_accounts',
            'admin_finance_mark_payment':               'finance_accounts',
            # ── Export Center ─────────────────────────────────────────────
            'export_index':                             'export',
            'export_agents':                            'export',
            'export_leads':                             'export',
            'export_contacts':                          'export',
            'export_subscriptions':                     'export',
            'export_reviews':                           'export',
            'export_pending':                           'export',
            # ── QR Generator ──────────────────────────────────────────────
            'admin_qr_files_index':                     'qr_generator',
            'admin_qr_files_store':                     'qr_generator',
            'admin_qr_files_update':                    'qr_generator',
            'admin_qr_files_delete':                    'qr_generator',
            # ── Geocoding ─────────────────────────────────────────────────
            'admin_geocoding_index':                    'geocoding',
            'admin_geocoding_single':                   'geocoding',
            'admin_geocoding_batch':                    'geocoding',
            'admin_geocoding_stats':                    'geocoding',
            # ── Pincode ───────────────────────────────────────────────────
            'admin_pincode_index':                      'pincode',
            'admin_pincode_upload':                     'pincode',
            'admin_pincode_import':                     'pincode',
            'admin_pincode_districts':                  'pincode',
            'admin_pincode_sample':                     'pincode',
            'admin_pincode_export':                     'pincode',
            'admin_pincode_delete_state':               'pincode',
            # ── Analytics / Advanced / Error Logs / Threats ───────────────
            'advanced_analytics':                       'analytics',
            'advanced_activity_logs':                   'analytics',
            'advanced_activity_logs_delete':            'analytics',
            'admin_error_logs_index':                   'error_logs',
            'admin_error_logs_show':                    'error_logs',
            'admin_error_logs_delete':                  'error_logs',
            'security_threat_logs':                     'analytics',
            'security_threat_logs_delete':              'analytics',
            # ── Investment Types ──────────────────────────────────────────
            'admin_investment_types_index':             'content',
            'admin_investment_types_store':             'content',
            'admin_investment_types_update':            'content',
            'admin_investment_types_delete':            'content',
            'admin_investment_types_toggle':            'content',
            # ── Site Settings / Security (blocked IPs) ────────────────────
            'admin_settings_general':                   'site_settings',
            'admin_settings_seo':                       'site_settings',
            'admin_settings_security':                  'site_settings',
            'admin_settings_templates':                 'email_templates',
            'admin_settings_templates_update':          'email_templates',
            'admin_settings_update':                    'site_settings',
            'security_blocked_ips':                     'site_settings',
            'security_block_ip':                        'site_settings',
            'security_unblock_ip':                      'site_settings',
            # ── System ────────────────────────────────────────────────────
            'admin_system_health':                      'server_health',
            'admin_system_logs':                        'logs',
            'admin_system_api_logs':                    'api_logs',
            'admin_system_backups':                     'backups',
            'admin_system_run_backup':                  'backups',
            'admin_system_download_backup':             'backups',
            'admin_system_clear_cache':                 'server_health',
        }.get(url_name)

    def get_first_allowed_route(self, admin):
        permission_to_route = {
            'dashboard': 'admin_dashboard',
            'agents': 'admin_agents',
            'approvals': 'admin_agents_approvals',
            'approvals_awaiting_verification': 'admin_agents_approvals',
            'approvals_missing_licenses': 'admin_agents_approvals',
            'blacklisted_agents': 'admin_blacklisted_agents',
            'pending_registrations': 'admin_agents_pending_registrations',
            'distributors': 'admin_distributors',
            'insurance': 'admin_insurance_index',
            'insurance_approvals': 'admin_insurance_approvals_index',
            'users': 'admin_users',
            'events': 'admin_events_index',
            'subscriptions': 'admin_subscriptions_index',
            'leads': 'admin_leads_index',
            'contacts': 'admin_contacts_index',
            'reviews': 'admin_reviews_index',
            'notifications': 'agent_notify',
            'content': 'admin_content_about',
            'revenue': 'admin_revenue',
            'invoices': 'admin_invoices',
            'promo_codes': 'admin_promo_codes',
            'free_trial': 'admin_free_trial',
            'referrals': 'admin_referrals_index',
            'finance_accounts': 'admin_finance_index',
            'export': 'export_index',
            'qr_generator': 'admin_qr_files_index',
            'geocoding': 'admin_geocoding_index',
            'pincode': 'admin_pincode_index',
            'analytics': 'advanced_analytics',
            'error_logs': 'admin_error_logs_index',
            'site_settings': 'admin_settings_general',
            'email_templates': 'admin_settings_templates',
            'server_health': 'admin_system_health',
            'logs': 'admin_system_logs',
            'api_logs': 'admin_system_api_logs',
            'backups': 'admin_system_backups',
            'fastapi_services': 'admin_dashboard',
        }
        
        permissions_list = admin.permissions if isinstance(admin.permissions, list) else []
        for permission, route in permission_to_route.items():
            if permission in permissions_list:
                return route
        return None


import traceback
import sys
from apps.admin_panel.models.error_log import ErrorLog

class ExceptionLoggerMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        try:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            tb_lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
            stack_trace = "".join(tb_lines)
            
            # Identify user
            user_info = None
            try:
                if hasattr(request, 'session') and request.session and request.session.get('admin_id'):
                    user_info = f"Admin: {request.session.get('admin_name', 'N/A')} ({request.session.get('admin_email', 'N/A')})"
                elif hasattr(request, 'user') and request.user.is_authenticated:
                    user_info = f"User: {request.user.username}"
            except Exception:
                pass

                
            # Get IP address
            x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
            ip = x_forwarded_for.split(',')[0].strip() if x_forwarded_for else request.META.get('REMOTE_ADDR')

            # Log to Database
            ErrorLog.objects.create(
                level='ERROR',
                module=exception.__class__.__module__,
                exception_type=exception.__class__.__name__,
                message=str(exception),
                stack_trace=stack_trace,
                url=request.build_absolute_uri(),
                method=request.method,
                user_info=user_info,
                status_code=500,
                ip_address=ip
            )
        except Exception:
            pass
        return None

