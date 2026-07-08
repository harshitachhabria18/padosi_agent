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
