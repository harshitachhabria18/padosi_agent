import logging
from urllib.parse import quote as urlencode
from django.shortcuts import render, redirect
from django.contrib.auth import login, logout
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from django.urls import reverse
from django.views.decorators.csrf import csrf_protect, csrf_exempt
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET
from apps.home.services.portal_messages import (
    PORTAL_AGENT,
    PORTAL_DISTRIBUTOR,
    PORTAL_INSURANCE,
    portal_error,
    portal_success,
)
from django.core.cache import cache
from django.http import HttpResponse, JsonResponse
from apps.agents.models import Agent
from apps.agents.services.brevo import email_service
from apps.agents.services.account_auth import (
    DJANGO_AUTH_BACKEND,
    INCOMPLETE_STATUSES,
    agent_can_access_dashboard,
    agent_needs_payment,
    create_or_link_django_user,
    find_agent,
    find_laravel_user,
    resolve_agent_for_user,
    sync_verified_password,
    verify_agent_password,
)
from password_hashing import hash_password

logger = logging.getLogger(__name__)

def get_client_ip(request):
    """
    Safely retrieve the client's real IP address from request headers.

    X-Forwarded-For is only trusted from the local reverse proxy (same rule as
    the admin WAF); from anywhere else it is attacker-controlled and made the
    per-IP login throttle trivially bypassable.
    """
    from apps.admin_panel.middleware import ThreatMonitorMiddleware
    return ThreatMonitorMiddleware.get_client_ip(request)


# Per-account throttle: independent of IP, so rotating/spoofed IPs cannot
# brute-force one password. Generous enough that a real user is not locked out.
EMAIL_LOGIN_MAX_FAILURES = 10
EMAIL_LOGIN_WINDOW_SECONDS = 15 * 60


def _email_throttle_key(email):
    return f"login_throttle_email_{(email or '').strip().lower()}"


def check_email_login_throttle(email):
    if not email:
        return True
    return (cache.get(_email_throttle_key(email), 0) or 0) < EMAIL_LOGIN_MAX_FAILURES


def record_email_login_failure(email):
    if not email:
        return
    key = _email_throttle_key(email)
    try:
        if not cache.add(key, 1, timeout=EMAIL_LOGIN_WINDOW_SECONDS):
            cache.incr(key)
    except Exception:
        pass

def check_login_throttle(ip):
    """
    Check if the client's IP has exceeded the 6 login attempts per minute rate limit.
    """
    key = f"login_throttle_{ip}"
    attempts = cache.get(key, 0)
    if attempts >= 6:
        return False
    return True

def record_login_attempt(ip):
    """
    Record a failed login attempt and increment the count in cache.
    """
    key = f"login_throttle_{ip}"
    try:
        attempts = cache.get(key, 0)
        if attempts == 0:
            cache.set(key, 1, timeout=60)
        else:
            try:
                cache.incr(key)
            except (ValueError, Exception):
                cache.set(key, (attempts or 0) + 1, timeout=60)
    except Exception:
        pass

def clear_login_throttle(ip):
    """
    Clear login throttling for a given IP upon successful authentication.
    """
    key = f"login_throttle_{ip}"
    cache.delete(key)


def _clear_admin_session_on(response, request):
    from apps.admin_panel.views.dashboard import clear_admin_session
    return clear_admin_session(request, response)


def _finish_agent_session_login(request, django_user, ip, agent=None):
    clear_login_throttle(ip)
    cache.delete(_email_throttle_key(getattr(django_user, 'email', '')))
    if agent is not None and getattr(agent, 'email', None):
        cache.delete(_email_throttle_key(agent.email))
    keys_to_clear = [
        'current_draft_id', 'email_verified', 'verified_email',
        'email_otp', 'otp_email', 'otp_expires_at',
        'applied_promo_code', 'promo_id', 'ref_code',
    ]
    for key in keys_to_clear:
        request.session.pop(key, None)
    login(request, django_user, backend=DJANGO_AUTH_BACKEND)
    logger.info("Agent/Admin user %s logged in successfully.", getattr(django_user, 'email', ''))

    if agent is None:
        agent = resolve_agent_for_user(django_user) or find_agent(getattr(django_user, 'email', ''))
    
    is_admin = getattr(django_user, 'is_staff', False) or getattr(django_user, 'is_superuser', False)
    if not is_admin:
        if not agent or not agent_can_access_dashboard(agent):
            portal_error(
                request,
                "Payment is pending. Please complete your plan payment to continue.",
                PORTAL_AGENT,
            )
            response = redirect('agents:chooseplan')
            return _clear_admin_session_on(response, request)

    response = redirect('agents:agent_dashboard')
    return _clear_admin_session_on(response, request)


@csrf_protect
@never_cache
def agent_login(request):
    """
    Handle rendering the agent login view and authenticating agent users.
    Enforces a role guard check and rate limiting of 6 attempts per minute.

    Password check matches admin login: bcrypt against `users` (and leftover
    auth_user hashes). Django authenticate() is not used because those hashes
    are not PBKDF2.
    """
    # If already logged in, route by verified payment status.
    if request.user.is_authenticated:
        is_admin = request.user.is_staff or request.user.is_superuser
        if is_admin:
            return redirect('agents:agent_dashboard')

        # A distributor or insurance-company user may open the agent login page to
        # sign in as an agent. Their Django session is shared across portals, so the
        # "already authenticated" shortcut below would trap them on chooseplan and
        # never let them reach the agent login form. Detect that case and fall
        # through to render/process the agent login instead.
        is_other_portal_user = (
            request.user.groups.filter(name='distributor').exists()
            or hasattr(request.user, 'insurance_profile')
        )

        if not is_other_portal_user:
            try:
                agent = resolve_agent_for_user(request.user) or find_agent(request.user.email or '')
            except Exception as e:
                logger.error("Already-authenticated agent lookup failed: %s", e)
                agent = None

            if agent:
                try:
                    from apps.agents.views.registration import verify_and_activate_pending_payment
                    verify_and_activate_pending_payment(agent)
                    agent.refresh_from_db()
                except Exception:
                    pass

                if agent_can_access_dashboard(agent):
                    return redirect('agents:agent_dashboard')
                else:
                    return redirect('agents:chooseplan')

            # If user is authenticated but not an admin or paid agent
            return redirect('agents:chooseplan')
        # Cross-portal user: fall through to the agent login form / POST handler.

    if request.method == 'POST':
        ip = get_client_ip(request)

        # Enforce rate limiting
        if not check_login_throttle(ip):
            portal_error(request, "Too many login attempts. Please try again after 1 minute.", PORTAL_AGENT)
            return render(request, 'agents/login.html', {'hide_site_nav': True, 'hide_footer': True, 'hide_chatbot': True})

        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')

        if not email or not password:
            record_login_attempt(ip)
            portal_error(request, "Please enter both email and password.", PORTAL_AGENT)
            return render(request, 'agents/login.html', {'email': email, 'hide_site_nav': True, 'hide_footer': True, 'hide_chatbot': True})

        if not check_email_login_throttle(email):
            portal_error(request, "Too many failed attempts for this account. Please try again in 15 minutes or reset your password.", PORTAL_AGENT)
            return render(request, 'agents/login.html', {'email': email, 'hide_site_nav': True, 'hide_footer': True, 'hide_chatbot': True})

        try:
            agent = find_agent(email)
            password_ok, laravel_user, django_user = verify_agent_password(email, password, agent=agent)
        except Exception as e:
            logger.error("Database error during login email lookup: %s", e)
            portal_error(request, "Login service is temporarily unavailable. Please try again.", PORTAL_AGENT)
            return render(request, 'agents/login.html', {'email': email, 'hide_site_nav': True, 'hide_footer': True, 'hide_chatbot': True})

        if not password_ok:
            record_login_attempt(ip)
            record_email_login_failure(email)
            logger.warning("Failed login attempt for email: %s from IP: %s", email, ip)
            portal_error(request, "Please Enter Valid Login Details", PORTAL_AGENT)
            return render(request, 'agents/login.html', {'email': email, 'hide_site_nav': True, 'hide_footer': True, 'hide_chatbot': True})

        canonical_email = (agent.email if agent else None) or (laravel_user.email if laravel_user else email)
        fullname = (agent.fullname if agent else None) or (laravel_user.fullname if laravel_user else canonical_email)
        laravel_role = (laravel_user.role or '').lower() if laravel_user else ''

        if laravel_role and laravel_role != 'agent' and not agent:
            record_login_attempt(ip)
            logger.warning("Login rejected for user %s: Incorrect role/type", email)
            portal_error(request, "Please use the correct login page for your account type.", PORTAL_AGENT)
            return render(request, 'agents/login.html', {'email': email, 'hide_site_nav': True, 'hide_footer': True, 'hide_chatbot': True})

        is_admin = bool(
            django_user
            and (getattr(django_user, 'is_staff', False) or getattr(django_user, 'is_superuser', False))
        )
        if not agent and not is_admin:
            record_login_attempt(ip)
            logger.warning("Login rejected for user %s: Incorrect role/type", email)
            portal_error(request, "Please use the correct login page for your account type.", PORTAL_AGENT)
            return render(request, 'agents/login.html', {'email': email, 'hide_site_nav': True, 'hide_footer': True, 'hide_chatbot': True})

        try:
            if agent:
                django_user = sync_verified_password(
                    canonical_email, fullname, password, role='agent', agent=agent
                )
                try:
                    agent.refresh_from_db()
                except Exception:
                    pass

                if agent.status in ['suspended', 'blacklisted', 'rejected']:
                    portal_error(request, f"Your account is currently {agent.status}.", PORTAL_AGENT)
                    return render(request, 'agents/login.html', {'email': email, 'hide_site_nav': True, 'hide_footer': True, 'hide_chatbot': True})

                if agent.status in INCOMPLETE_STATUSES:
                    try:
                        from apps.agents.views.registration import verify_and_activate_pending_payment
                        verify_and_activate_pending_payment(agent)
                        agent.refresh_from_db()
                    except Exception as e:
                        logger.warning(
                            "Pending-payment check failed for %s: %s",
                            canonical_email, e,
                        )

            if not django_user:
                django_user = sync_verified_password(
                    canonical_email, fullname, password, role='agent', agent=agent
                )

            if agent and not agent_can_access_dashboard(agent):
                clear_login_throttle(ip)
                cache.delete(_email_throttle_key(email))
                login(request, django_user, backend=DJANGO_AUTH_BACKEND)
                portal_error(
                    request,
                    "Payment is pending. Please complete your plan payment to continue.",
                    PORTAL_AGENT,
                )
                return redirect('agents:chooseplan')

            return _finish_agent_session_login(request, django_user, ip, agent=agent)
        except Exception as e:
            logger.exception("Agent login session setup failed for %s: %s", email, e)
            portal_error(request, "Login service is temporarily unavailable. Please try again.", PORTAL_AGENT)
            return render(request, 'agents/login.html', {'email': email, 'hide_site_nav': True, 'hide_footer': True, 'hide_chatbot': True})

    return render(request, 'agents/login.html', {'hide_site_nav': True, 'hide_footer': True, 'hide_chatbot': True})


@require_GET
@never_cache
def app_upgrade_handoff(request):
    """
    Open the website upgrade checkout from a one-time app link.

    The token identifies the agent. The password is never sent. A valid token
    starts a Django session and sends a paid agent to the dashboard with the
    upgrade payment open.
    """
    from apps.agents.services.account_auth import (
        BLOCKED_DASHBOARD_STATUSES,
        create_or_link_django_user,
        find_django_user,
    )
    from apps.agents.services.plan_upgrade_handoff import consume_plan_upgrade_handoff

    row = consume_plan_upgrade_handoff(request.GET.get('token'))
    if row is None or row.agent is None:
        portal_error(
            request,
            "This upgrade link has expired. Open the app and try again.",
            PORTAL_AGENT,
        )
        return redirect('agents:agent_login')

    agent = row.agent
    if agent.status in BLOCKED_DASHBOARD_STATUSES:
        portal_error(request, f"Your account is currently {agent.status}.", PORTAL_AGENT)
        return redirect('agents:agent_login')

    django_user = find_django_user(agent.email)
    if django_user is None:
        try:
            django_user = create_or_link_django_user(agent)
        except Exception:
            logger.exception("App upgrade handoff could not open a session for agent #%s", agent.pk)
            portal_error(
                request,
                "We could not open your upgrade checkout. Please log in and try again.",
                PORTAL_AGENT,
            )
            return redirect('agents:agent_login')

    if request.user.is_authenticated:
        logout(request)
    login(request, django_user, backend=DJANGO_AUTH_BACKEND)
    logger.info("App upgrade handoff logged in agent #%s for plan %s.", agent.pk, row.plan_slug)

    if agent_can_access_dashboard(agent):
        destination = reverse('agents:agent_dashboard') + '?upgrade=' + row.plan_slug
    else:
        destination = reverse('agents:chooseplan')
    return _clear_admin_session_on(redirect(destination), request)


def _is_cross_site_get(request):
    """A GET started by another website (e.g. <img src=/logout/>).

    Logout links on our own pages send Sec-Fetch-Site: same-origin (typed URLs:
    none), so only forced logouts from other sites are ignored.
    """
    return (
        request.method == 'GET'
        and (request.headers.get('Sec-Fetch-Site') or '').lower() == 'cross-site'
    )


@csrf_exempt
def agent_logout(request):
    """
    Log out the agent, invalidate session, and redirect to the login page.
    """
    if _is_cross_site_get(request):
        return redirect('home:home')
    logout(request)
    portal_success(request, "You have been logged out successfully.", PORTAL_AGENT)
    response = redirect('agents:agent_login')
    return _clear_admin_session_on(response, request)

def _resolve_logout_role(request):
    from apps.admin_panel.views.dashboard import _get_admin_from_session
    if _get_admin_from_session(request):
        return 'admin'

    user = getattr(request, 'user', None)
    if not user or not getattr(user, 'is_authenticated', False):
        return 'agent'

    role = (getattr(user, 'role', None) or '').lower()
    if role in ('admin', 'agent', 'client', 'distributor', 'insurance_company'):
        return role
    if user.groups.filter(name='distributor').exists():
        return 'distributor'
    if getattr(user, 'is_staff', False) or getattr(user, 'is_superuser', False):
        return 'admin'
    try:
        if Agent.objects.filter(user_id=user.pk).exists():
            return 'agent'
    except Exception:
        pass
    return 'agent'


@csrf_exempt
@never_cache
def logout_view(request):
    """
    General logout view mirroring Laravel's AuthController@logout.
    Handles logout for all user roles (agent, admin, client, distributor).
    """
    if _is_cross_site_get(request):
        return redirect('home:home')
    role = _resolve_logout_role(request)

    if role == 'admin':
        from apps.admin_panel.views.dashboard import admin_logout
        return admin_logout(request)

    logout(request)

    if role == 'client':
        referer = request.META.get('HTTP_REFERER')
        host = request.get_host()
        if referer and host in referer:
            return _clear_admin_session_on(redirect(referer), request)
        return _clear_admin_session_on(redirect('home:find_agents'), request)

    if role == 'distributor':
        portal_success(request, "You have been logged out successfully.", PORTAL_DISTRIBUTOR)
        return _clear_admin_session_on(redirect('/distributor-login'), request)

    if role == 'insurance_company':
        portal_success(request, "You have been logged out successfully.", PORTAL_INSURANCE)
        return _clear_admin_session_on(redirect('insurance_login'), request)

    portal_success(request, "You have been logged out successfully.", PORTAL_AGENT)
    return _clear_admin_session_on(redirect('agents:agent_login'), request)

@login_required(login_url='agents:agent_login')
def agent_dashboard(request):
    """
    A temporary placeholder dashboard for agents to verify authentication holds.
    """
    # Enforce role guard check for dashboard access
    is_agent = Agent.objects.filter(user=request.user).exists()
    is_admin = request.user.is_staff or request.user.is_superuser
    if not (is_agent or is_admin):
        logout(request)
        portal_error(request, "Unauthorized access. Gated area.", PORTAL_AGENT)
        return redirect('agents:agent_login')

    agent = None
    if is_agent:
        agent = Agent.objects.get(user=request.user)

    return render(request, 'agents/dashboard_placeholder.html', {
        'agent': agent,
        'user': request.user
    })


def redirectToGoogle(request):
    """
    Redirect the user to Google's OAuth consent screen.
    """
    from django.conf import settings
    import urllib.parse
    
    client_id = getattr(settings, 'GOOGLE_CLIENT_ID', '')
    redirect_uri = getattr(settings, 'GOOGLE_REDIRECT_URI', '')
    
    if not client_id or not redirect_uri:
        logger.error("Google OAuth configuration is missing (GOOGLE_CLIENT_ID or GOOGLE_REDIRECT_URI).")
        return HttpResponse("Google OAuth client configuration is missing in settings/env.", status=500)

    import secrets
    # Random per-session state, checked in the callback (login-CSRF protection).
    state = secrets.token_urlsafe(24)
    request.session['google_oauth_state'] = state
    params = {
        'client_id': client_id,
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': 'openid email profile',
        'state': state,
        'prompt': 'select_account',
    }
    auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)
    return redirect(auth_url)


def handleGoogleCallback(request):
    """
    Receive authorization code, retrieve user details from Google userinfo API,
    and save google_user dict into request session.
    """
    from django.conf import settings
    import requests
    
    code = request.GET.get('code')
    if not code:
        logger.warning("Google callback invoked without authorization code.")
        return HttpResponse("Authorization code missing from callback.", status=400)

    import hmac
    expected_state = request.session.pop('google_oauth_state', None)
    received_state = request.GET.get('state') or ''
    if not expected_state or not hmac.compare_digest(str(expected_state), str(received_state)):
        logger.warning("Google callback rejected: OAuth state mismatch.")
        return HttpResponse("Invalid or expired sign-in request. Please try again.", status=400)

    client_id = getattr(settings, 'GOOGLE_CLIENT_ID', '')
    client_secret = getattr(settings, 'GOOGLE_CLIENT_SECRET', '')
    redirect_uri = getattr(settings, 'GOOGLE_REDIRECT_URI', '')
    
    try:
        # Exchange code for access token
        token_url = "https://oauth2.googleapis.com/token"
        payload = {
            'code': code,
            'client_id': client_id,
            'client_secret': client_secret,
            'redirect_uri': redirect_uri,
            'grant_type': 'authorization_code'
        }
        token_response = requests.post(token_url, data=payload, timeout=10)
        if not token_response.ok:
            logger.error(f"Google Token Exchange Failed: {token_response.text}")
            return HttpResponse("Failed to retrieve Google token.", status=400)
            
        tokens = token_response.json()
        access_token = tokens.get('access_token')
        
        # Request user profile details
        userinfo_url = "https://www.googleapis.com/oauth2/v3/userinfo"
        userinfo_response = requests.get(userinfo_url, headers={'Authorization': f"Bearer {access_token}"}, timeout=10)
        if not userinfo_response.ok:
            logger.error(f"Google UserInfo Request Failed: {userinfo_response.text}")
            return HttpResponse("Failed to retrieve Google user information.", status=400)
            
        google_user = userinfo_response.json()
        
        # Save credentials in session
        request.session['google_user'] = {
            'email': google_user.get('email'),
            'fullname': google_user.get('name'),
            'google_id': google_user.get('sub')
        }
        
        # Return success popup closure HTML
        html_content = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Authentication Complete</title>
            <script>
                window.close();
            </script>
        </head>
        <body>
            Authentication Successful! Closing window...
        </body>
        </html>
        """
        return HttpResponse(html_content)
    except Exception as e:
        logger.error(f"Google OAuth Callback Error: {e}")
        return HttpResponse("An error occurred during authentication.", status=500)


def getGoogleSessionData(request):
    """
    Get the google user details from session and clear it.
    """
    google_user = request.session.pop('google_user', None)
    if google_user:
        return JsonResponse({
            'success': True,
            'user': google_user
        })
    return JsonResponse({'success': False})


def getGoogleUserData(request):
    """
    Get the google user details from session without clearing it.
    """
    google_user = request.session.get('google_user')
    if google_user:
        return JsonResponse({
            'success': True,
            'user': {
                'email': google_user.get('email'),
                'fullname': google_user.get('fullname')
            }
        })
    return JsonResponse({'success': False})


def clearGoogleSession(request):
    """
    Remove google user details from session.
    """
    request.session.pop('google_user', None)
    return JsonResponse({'success': True})


@csrf_protect
def forgot_password(request):
    """
    Handle rendering the forgot password form and sending the reset link via email.
    Matches PHP AuthController::showLinkRequestForm and sendResetLinkEmail.
    """
    if request.user.is_authenticated:
        return redirect('agents:agent_dashboard')

    login_type = request.GET.get('type') or request.POST.get('login_type') or 'agent'

    if request.method == 'POST':
        email = request.POST.get('email', '').strip().lower()
        login_type = request.POST.get('login_type', 'agent').strip().lower()

        if not email or '@' not in email:
            portal_error(request, "Please enter a valid email address.", PORTAL_AGENT)
            return render(request, 'agents/forgot_password.html', {'email': email, 'type': login_type, 'hide_site_nav': True, 'hide_footer': True, 'hide_chatbot': True})

        agent = find_agent(email)
        laravel_user = find_laravel_user(email)
        user = User.objects.filter(email__iexact=email).first()

        if login_type == 'agent' and agent and not user:
            user = create_or_link_django_user(agent)

        # Generic response to prevent email enumeration (matching PHP logic)
        if not user and not agent:
            portal_success(request, "If that email is registered, you will receive a reset link shortly.", PORTAL_AGENT)
            return render(request, 'agents/forgot_password.html', {'type': login_type, 'hide_site_nav': True, 'hide_footer': True, 'hide_chatbot': True})

        if not user:
            portal_success(request, "If that email is registered, you will receive a reset link shortly.", PORTAL_AGENT)
            return render(request, 'agents/forgot_password.html', {'type': login_type, 'hide_site_nav': True, 'hide_footer': True, 'hide_chatbot': True})

        if user.is_staff or user.is_superuser:
            # Same generic reply as unknown emails: don't reveal staff accounts.
            logger.warning("Password reset requested for staff account %s via agent flow; ignored.", email)
            portal_success(request, "If that email is registered, you will receive a reset link shortly.", PORTAL_AGENT)
            return render(request, 'agents/forgot_password.html', {'type': login_type, 'hide_site_nav': True, 'hide_footer': True, 'hide_chatbot': True})

        # Check if user role matches login_type
        is_agent = bool(agent) or Agent.objects.filter(user=user).exists()
        laravel_role = (laravel_user.role or '').lower() if laravel_user else ''
        if login_type == 'agent' and not is_agent:
            portal_error(request, "This email belongs to a Distributor account. Please use the Distributor login page.", PORTAL_AGENT)
            return render(request, 'agents/forgot_password.html', {'email': email, 'type': login_type, 'hide_site_nav': True, 'hide_footer': True, 'hide_chatbot': True})
        if login_type == 'agent' and laravel_role and laravel_role != 'agent' and not is_agent:
            portal_error(request, "This email belongs to a Distributor account. Please use the Distributor login page.", PORTAL_AGENT)
            return render(request, 'agents/forgot_password.html', {'email': email, 'type': login_type, 'hide_site_nav': True, 'hide_footer': True, 'hide_chatbot': True})

        try:
            token = default_token_generator.make_token(user)
            uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
            
            from django.urls import reverse
            reset_path = reverse('agents:reset_password', kwargs={'uidb64': uidb64, 'token': token})
            reset_url = request.build_absolute_uri(reset_path) + f"?email={urlencode(user.email)}&type={login_type}"

            role_name = "Distributor" if login_type == "distributor" else "Agent"
            user_name = user.get_full_name() or user.username or "User"

            success = email_service.send_password_reset(user.email, user_name, reset_url, "60", role_name)
            if not success:
                logger.error(f"Failed to send password reset email to {user.email}")

            portal_success(request, "Password reset link has been sent to your email address!", PORTAL_AGENT)
            return render(request, 'agents/forgot_password.html', {'type': login_type, 'hide_site_nav': True, 'hide_footer': True, 'hide_chatbot': True})
        except Exception as e:
            logger.error(f"Error sending password reset email: {e}")
            portal_error(request, "Unable to send reset email. Please try again later.", PORTAL_AGENT)
            return render(request, 'agents/forgot_password.html', {'email': email, 'type': login_type, 'hide_site_nav': True, 'hide_footer': True, 'hide_chatbot': True})

    return render(request, 'agents/forgot_password.html', {'type': login_type, 'hide_site_nav': True, 'hide_footer': True, 'hide_chatbot': True})


@csrf_protect
def reset_password(request, uidb64=None, token=None):
    """
    Handle rendering the password reset form and setting the new password.
    Matches PHP AuthController::showResetForm and reset.
    """
    if request.user.is_authenticated:
        return redirect('agents:agent_dashboard')

    email = request.GET.get('email') or request.POST.get('email', '')
    login_type = request.GET.get('type') or request.POST.get('login_type') or 'agent'

    user = None
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    if user is None or not default_token_generator.check_token(user, token):
        portal_error(request, "This password reset link is invalid or has expired. Please request a new one.", PORTAL_AGENT)
        return redirect('agents:forgot_password')

    if request.method == 'POST':
        password = request.POST.get('password', '')
        password_confirmation = request.POST.get('password_confirmation', '')

        if not password or len(password) < 8:
            portal_error(request, "Password must be at least 8 characters long.", PORTAL_AGENT)
            return render(request, 'agents/reset_password.html', {
                'token': token, 'uidb64': uidb64, 'email': email, 'type': login_type,
                'hide_site_nav': True, 'hide_footer': True, 'hide_chatbot': True,
            })

        if password != password_confirmation:
            portal_error(request, "Passwords do not match.", PORTAL_AGENT)
            return render(request, 'agents/reset_password.html', {
                'token': token, 'uidb64': uidb64, 'email': email, 'type': login_type,
                'hide_site_nav': True, 'hide_footer': True, 'hide_chatbot': True,
            })

        bcrypt_hash = hash_password(password)
        user.password = bcrypt_hash
        user.save(update_fields=['password'])
        from apps.agents.services.account_auth import ensure_laravel_user, find_agent as _find_agent
        agent = _find_agent(user.email)
        fullname = (agent.fullname if agent else '') or user.get_full_name() or user.username
        # role=None keeps an existing users.role (a distributor resetting via this
        # flow was silently converted to 'agent' and locked out of their portal);
        # a missing row is still created with the default 'agent' role.
        ensure_laravel_user(user.email, fullname, bcrypt_hash, role=None, overwrite_password=True)

        portal_success(request, "Your password has been reset successfully! Please log in.", PORTAL_AGENT)
        return redirect('agents:agent_login')

    return render(request, 'agents/reset_password.html', {
        'token': token, 'uidb64': uidb64, 'email': email, 'type': login_type,
        'hide_site_nav': True, 'hide_footer': True, 'hide_chatbot': True,
    })

