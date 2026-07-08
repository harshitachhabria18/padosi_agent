import logging
from urllib.parse import quote as urlencode
from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.cache import never_cache
from django.contrib import messages
from django.core.cache import cache
from django.http import HttpResponse, JsonResponse
from apps.agents.models import Agent
from apps.agents.services.brevo import email_service

logger = logging.getLogger(__name__)

def get_client_ip(request):
    """
    Safely retrieve the client's real IP address from request headers.
    """
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip

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
    attempts = cache.get(key, 0)
    if attempts == 0:
        cache.set(key, 1, timeout=60)
    else:
        cache.incr(key)

def clear_login_throttle(ip):
    """
    Clear login throttling for a given IP upon successful authentication.
    """
    key = f"login_throttle_{ip}"
    cache.delete(key)

@csrf_protect
@never_cache
def agent_login(request):
    """
    Handle rendering the agent login view and authenticating agent users.
    Enforces a role guard check and rate limiting of 6 attempts per minute.
    """
    # If already logged in, redirect them
    if request.user.is_authenticated:
        is_agent = Agent.objects.filter(user=request.user).exists()
        is_admin = request.user.is_staff or request.user.is_superuser
        if is_agent or is_admin:
            return redirect('agents:agent_dashboard')
        return redirect('/')

    if request.method == 'POST':
        ip = get_client_ip(request)
        
        # Enforce rate limiting
        if not check_login_throttle(ip):
            messages.error(request, "Too many login attempts. Please try again after 1 minute.")
            return render(request, 'agents/login.html')

        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '').strip()

        if not email or not password:
            record_login_attempt(ip)
            messages.error(request, "Please enter both email and password.")
            return render(request, 'agents/login.html', {'email': email})

        # Try to retrieve User by email address (case-insensitive)
        try:
            user = User.objects.filter(email__iexact=email).first()
        except Exception as e:
            logger.error(f"Database error during login email lookup: {e}")
            messages.error(request, "Login service is temporarily unavailable. Please try again.")
            return render(request, 'agents/login.html', {'email': email})

        if user:
            # Verify credentials using Django authenticate
            authenticated_user = authenticate(username=user.username, password=password)
            if authenticated_user:
                is_agent = Agent.objects.filter(user=authenticated_user).exists()
                is_admin = authenticated_user.is_staff or authenticated_user.is_superuser

                if is_agent:
                    agent = Agent.objects.get(user=authenticated_user)
                    if agent.status != 'active':
                        record_login_attempt(ip)
                        logger.warning(f"Login rejected for agent {email}: Account status is '{agent.status}' (not active)")
                        messages.error(request, "Your agent account is not yet active. Please complete registration or contact support.")
                        return render(request, 'agents/login.html', {'email': email})

                if is_agent or is_admin:
                    # Successful login
                    clear_login_throttle(ip)
                    
                    # Clean up stale session keys from registration flow
                    keys_to_clear = [
                        'current_draft_id', 'email_verified', 'verified_email',
                        'email_otp', 'otp_email', 'otp_expires_at',
                        'applied_promo_code', 'promo_id', 'ref_code'
                    ]
                    for key in keys_to_clear:
                        request.session.pop(key, None)

                    login(request, authenticated_user)
                    logger.info(f"Agent/Admin user {authenticated_user.email} logged in successfully.")
                    return redirect('agents:agent_dashboard')
                
                # Correct credentials but not an agent/admin user (e.g. distributor page user)
                record_login_attempt(ip)
                logger.warning(f"Login rejected for user {email}: Incorrect role/type")
                messages.error(request, "Please use the correct login page for your account type.")
                return render(request, 'agents/login.html', {'email': email})

        # Generic authentication failure path (prevent email enumeration)
        record_login_attempt(ip)
        logger.warning(f"Failed login attempt for email: {email} from IP: {ip}")
        messages.error(request, "Please Enter Valid Login Details")
        return render(request, 'agents/login.html', {'email': email})

    return render(request, 'agents/login.html')

def agent_logout(request):
    """
    Log out the agent, invalidate session, and redirect to the login page.
    """
    logout(request)
    messages.success(request, "You have been logged out successfully.")
    return redirect('agents:agent_login')

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
        messages.error(request, "Unauthorized access. Gated area.")
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

    params = {
        'client_id': client_id,
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': 'openid email profile',
        'state': 'padosi_state',
        'access_type': 'offline',
        'prompt': 'consent'
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
        token_response = requests.post(token_url, data=payload)
        if not token_response.ok:
            logger.error(f"Google Token Exchange Failed: {token_response.text}")
            return HttpResponse("Failed to retrieve Google token.", status=400)
            
        tokens = token_response.json()
        access_token = tokens.get('access_token')
        
        # Request user profile details
        userinfo_url = "https://www.googleapis.com/oauth2/v3/userinfo"
        userinfo_response = requests.get(userinfo_url, headers={'Authorization': f"Bearer {access_token}"})
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
            messages.error(request, "Please enter a valid email address.")
            return render(request, 'agents/forgot_password.html', {'email': email, 'type': login_type})

        # Look up user by email
        user = User.objects.filter(email__iexact=email).first()

        # Generic response to prevent email enumeration (matching PHP logic)
        if not user:
            messages.success(request, "If that email is registered, you will receive a reset link shortly.")
            return render(request, 'agents/forgot_password.html', {'type': login_type})

        if user.is_staff or user.is_superuser:
            messages.error(request, "Admin accounts cannot use this reset flow.")
            return render(request, 'agents/forgot_password.html', {'email': email, 'type': login_type})

        # Check if user role matches login_type
        is_agent = Agent.objects.filter(user=user).exists()
        if login_type == 'agent' and not is_agent:
            messages.error(request, "This email belongs to a Distributor account. Please use the Distributor login page.")
            return render(request, 'agents/forgot_password.html', {'email': email, 'type': login_type})

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

            messages.success(request, "Password reset link has been sent to your email address!")
            return render(request, 'agents/forgot_password.html', {'type': login_type})
        except Exception as e:
            logger.error(f"Error sending password reset email: {e}")
            messages.error(request, "Unable to send reset email. Please try again later.")
            return render(request, 'agents/forgot_password.html', {'email': email, 'type': login_type})

    return render(request, 'agents/forgot_password.html', {'type': login_type})


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
        messages.error(request, "This password reset link is invalid or has expired. Please request a new one.")
        return redirect('agents:forgot_password')

    if request.method == 'POST':
        password = request.POST.get('password', '')
        password_confirmation = request.POST.get('password_confirmation', '')

        if not password or len(password) < 8:
            messages.error(request, "Password must be at least 8 characters long.")
            return render(request, 'agents/reset_password.html', {
                'token': token, 'uidb64': uidb64, 'email': email, 'type': login_type
            })

        if password != password_confirmation:
            messages.error(request, "Passwords do not match.")
            return render(request, 'agents/reset_password.html', {
                'token': token, 'uidb64': uidb64, 'email': email, 'type': login_type
            })

        # Set new password
        user.set_password(password)
        user.save()

        messages.success(request, "Your password has been reset successfully! Please log in.")
        return redirect('agents:agent_login')

    return render(request, 'agents/reset_password.html', {
        'token': token, 'uidb64': uidb64, 'email': email, 'type': login_type
    })

