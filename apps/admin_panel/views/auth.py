import json
import bcrypt
from django.shortcuts import render, redirect
from django.contrib import messages
from django.utils import timezone
from apps.admin_panel.models import Admin, SecurityThreatLog
from apps.agents.models import BlockedIp

def verify_password(plain_password, hashed_password):
    try:
        if hashed_password.startswith('$2y$'):
            hashed_password = '$2b$' + hashed_password[4:]
        return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
    except Exception:
        return False

def admin_login(request):
    # Redirect if already logged in as admin
    if request.session.get('admin_id'):
        return redirect('admin_panel:settings_homepage')

    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '').strip()

        if not email or not password:
            messages.error(request, 'Please enter both email and password.')
            return render(request, 'admin/login.html', {'email': email})

        admin = Admin.objects.filter(email=email).first()

        if admin and verify_password(password, admin.password):
            # Successful Authentication
            request.session['admin_id'] = admin.id
            request.session['admin_name'] = admin.name
            request.session['admin_email'] = admin.email
            return redirect('admin_panel:settings_homepage')

        # --- SECURITY LOGGING & AUTO BLOCK ---
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        ip = x_forwarded_for.split(',')[0].strip() if x_forwarded_for else request.META.get('REMOTE_ADDR')

        # Save Security Log
        SecurityThreatLog.objects.create(
            ip_address=ip,
            event_type='Failed Admin Login',
            url=request.build_absolute_uri(),
            payload=json.dumps({'email': email}),
            user_agent=request.META.get('HTTP_USER_AGENT', '')
        )

        # Auto-Block on 5 failed attempts within last 1 hour
        one_hour_ago = timezone.now() - timezone.timedelta(hours=1)
        recent_failures = SecurityThreatLog.objects.filter(
            ip_address=ip,
            event_type='Failed Admin Login',
            created_at__gte=one_hour_ago
        ).count()

        if recent_failures >= 5:
            BlockedIp.objects.get_or_create(
                ip_address=ip,
                defaults={'reason': 'Auto-blocked due to recurring failed admin login attempts (Potential Brute Force).'}
            )

        messages.error(request, 'Invalid email or password.')
        return render(request, 'admin/login.html', {'email': email})

    return render(request, 'admin/login.html')


def admin_logout(request):
    # Clear session keys
    for key in ['admin_id', 'admin_name', 'admin_email']:
        if key in request.session:
            del request.session[key]
    messages.success(request, 'You have been successfully logged out.')
    return redirect('admin_panel:login')
