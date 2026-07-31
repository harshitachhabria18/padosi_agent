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
        from django.conf import settings
        whitelisted_ips = getattr(settings, 'SECURITY_WHITELISTED_IPS', ['127.0.0.1', '::1'])
        if ip in whitelisted_ips:
            return self.get_response(request)

        # 3. Check if IP is already explicitly Blocked
        if BlockedIp.objects.filter(ip_address=ip).exists():
            if request.headers.get('accept') == 'application/json' or request.path.startswith('/api/'):
                return JsonResponse({'error': 'Forbidden', 'message': 'Your IP address has been blocked.'}, status=403)
            return HttpResponseForbidden('Your IP address has been blocked due to suspicious activity.')

        # 4. Identify potential Malicious Payloads (Basic WAF functionality)
        url_to_check = request.build_absolute_uri()
        
        # Collect request input fields
        payload_dict = {}
        if request.method in ['POST', 'PUT', 'PATCH']:
            # Try to load POST parameters
            for k, v in request.POST.items():
                payload_dict[k] = v
            # If JSON body, try parsing it
            try:
                if request.content_type == 'application/json' and request.body:
                    json_data = json.loads(request.body.decode('utf-8', errors='ignore'))
                    if isinstance(json_data, dict):
                        payload_dict.update(json_data)
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
            if request.session.get('admin_id'):
                hacker_name = f"Admin: {request.session.get('admin_name', 'N/A')}"
                hacker_email = request.session.get('admin_email')
            # Fallback to general django auth user if present
            elif hasattr(request, 'user') and request.user.is_authenticated:
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
                    to_email='parth.ramanujj@gmail.com',
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
from django.contrib import messages

class AdminIpWhitelistMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path.rstrip('/')
        if path.startswith('/admin') or path.startswith('/django-admin'):
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


class AdminPermissionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path.rstrip('/')
        if not path.startswith('/admin'):
            return self.get_response(request)

        # Allow auth endpoints without session or permissions
        if path in ['/admin', '/admin/login', '/admin/login/post', '/admin/logout']:
            return self.get_response(request)

        from apps.admin_panel.views.dashboard import _get_admin_from_session
        from apps.admin_panel.models.admin_auth import Admin
        
        admin_id = _get_admin_from_session(request)
        if not admin_id:
            messages.error(request, "Please sign in to access the admin panel.")
            return redirect('admin_login_page')

        try:
            admin = Admin.objects.get(pk=admin_id)
        except Admin.DoesNotExist:
            from apps.admin_panel.views.dashboard import admin_logout
            messages.error(request, "Admin account not found. Logged out.")
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
                    messages.error(request, message)
                    return redirect(url)
                except Exception:
                    pass
            from apps.admin_panel.views.dashboard import admin_logout
            messages.error(request, "Your staff account has no access permissions. Logged out.")
            return admin_logout(request)

        # 1. DELETE ACTION PROTECTION:
        # Staff admins can never delete records.
        url_name = request.resolver_match.url_name if request.resolver_match else ''
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

        # 3. SECTION/MODULE PERMISSION CHECK:
        required_permission = self.get_required_permission(url_name)
        if required_permission:
            # Check permissions
            permissions_list = admin.permissions if isinstance(admin.permissions, list) else []
            if required_permission not in permissions_list:
                if request.headers.get('accept') == 'application/json' or request.path.startswith('/api/'):
                    return JsonResponse({'success': False, 'message': 'Unauthorized. You do not have permission to access this module.'}, status=403)
                perm_name = required_permission.replace('_', ' ').title()
                return get_redirect_response(f'Unauthorized. You do not have permission to access the {perm_name} module.')

        request.admin_user = admin
        return self.get_response(request)

    def get_required_permission(self, url_name):
        if not url_name:
            return None
            
        mappings = {
            'admin_dashboard': 'dashboard',
            'admin_agents': 'agents',
            'admin_approvals': 'approvals',
            'admin_pending_registrations': 'pending_registrations',
            'admin_distributors': 'distributors',
            'admin_insurance': 'insurance',
            'admin_insurance_approvals': 'insurance_approvals',
            'admin_users': 'users',
            'admin_events': 'events',
            'admin_subscriptions': 'subscriptions',
            'admin_leads': 'leads',
            'admin_contacts': 'contacts',
            'admin_reviews': 'reviews',
            'admin_notifications': 'notifications',
            'admin_broadcast': 'notifications',
            'admin_free_trial': 'free_trial',
            'admin_revenue': 'revenue',
            'admin_invoices': 'invoices',
            'admin_promo_codes': 'promo_codes',
            'admin_referrals': 'referrals',
            'admin_finance': 'finance_accounts',
            'admin_export': 'export',
            'admin_qr_files': 'qr_generator',
            'admin_geocoding': 'geocoding',
            'admin_pincode': 'pincode',
            'admin_advanced_analytics': 'analytics',
            'admin_advanced_activity_logs': 'analytics',
            'admin_security_threat_logs': 'analytics',
            'admin_security_blocked_ips': 'site_settings',
            'admin_settings_general': 'site_settings',
            'admin_settings_seo': 'site_settings',
            'admin_settings_security': 'site_settings',
            'admin_settings_templates': 'site_settings',
        }
        
        for prefix, permission in mappings.items():
            if url_name.startswith(prefix):
                return permission
        return None

    def get_first_allowed_route(self, admin):
        permission_to_route = {
            'dashboard': 'admin_dashboard',
            'agents': 'admin_agents',
            'approvals': 'admin_agents',
            'pending_registrations': 'admin_agents',
            'distributors': 'admin_distributors',
            'insurance': 'admin_agents',
            'insurance_approvals': 'admin_agents',
            'users': 'admin_agents',
            'events': 'admin_agents',
            'subscriptions': 'admin_agents',
            'leads': 'admin_agents',
            'contacts': 'admin_agents',
            'reviews': 'admin_agents',
            'notifications': 'admin_agents',
            'content': 'admin_dashboard',
            'revenue': 'admin_dashboard',
            'invoices': 'admin_agents',
            'promo_codes': 'admin_agents',
            'free_trial': 'admin_agents',
            'referrals': 'admin_agents',
            'finance_accounts': 'admin_dashboard',
            'export': 'admin_dashboard',
            'qr_generator': 'admin_dashboard',
            'geocoding': 'admin_dashboard',
            'pincode': 'admin_dashboard',
            'analytics': 'admin_dashboard',
            'site_settings': 'admin_dashboard',
        }
        
        permissions_list = admin.permissions if isinstance(admin.permissions, list) else []
        for permission, route in permission_to_route.items():
            if permission in permissions_list:
                return route
        return None
