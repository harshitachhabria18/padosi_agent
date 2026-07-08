import bcrypt
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.core.paginator import Paginator
from django.contrib import messages
from apps.admin_panel.views.dashboard import _get_admin_from_session
from apps.admin_panel.models.admin_auth import Admin

def get_permissions_list():
    return {
        'dashboard': 'Dashboard View',
        'agents': 'Active Agents',
        'approvals': 'Pending Approvals',
        'pending_registrations': 'Registration Pending',
        'distributors': 'Distributors',
        'insurance': 'Insurance Companies',
        'insurance_approvals': 'Insurance Onboarding Approvals',
        'users': 'Clients / Users Registry',
        'events': 'Event Management',
        'subscriptions': 'Renewal Tracker',
        'leads': 'Agent Leads',
        'contacts': 'Contact Inbox',
        'reviews': 'Review Moderation',
        'notifications': 'Custom Notifications & Broadcasts',
        'content': 'Content & Pages CMS',
        'revenue': 'Revenue Dashboard',
        'invoices': 'Invoices Management',
        'promo_codes': 'Promo Codes',
        'free_trial': 'Free Trial Manager',
        'referrals': 'Referral System Config & Rewards',
        'finance_accounts': 'Finance & Accounts',
        'export': 'Export Center',
        'qr_generator': 'QR Code Generator & File Manager',
        'geocoding': 'Geocoding Manager',
        'pincode': 'Pincode Database Manager',
        'analytics': 'Analytics, Activity Logs & Threat Intelligence',
        'site_settings': 'Site Settings, SEO & Security Rules',
    }

def admins_index(request):
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return redirect('admin_login')

    query = Admin.objects.all()

    # Search filter
    search = request.GET.get('search', '').strip()
    if search:
        query = query.filter(name__icontains=search) | query.filter(email__icontains=search)

    # Role filter
    role = request.GET.get('role', 'all').strip()
    if role != 'all':
        query = query.filter(role=role)

    query = query.order_by('-created_at')

    # Paginate by 15
    paginator = Paginator(query, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'admin/admins/index.html', {
        'admins': page_obj,
        'search': search,
        'selected_role': role
    })

def admins_create(request):
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return redirect('admin_login')

    permissions = get_permissions_list()
    return render(request, 'admin/admins/create.html', {
        'permissionsList': permissions
    })

def admins_store(request):
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return redirect('admin_login')

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        password_confirmation = request.POST.get('password_confirmation', '')
        role = request.POST.get('role', '').strip()
        permissions_selected = request.POST.getlist('permissions[]') or request.POST.getlist('permissions')

        if not name or not email or not password or not role:
            messages.error(request, 'All fields are required.')
            return redirect('admin_admins_create')

        if password != password_confirmation:
            messages.error(request, 'Passwords do not match.')
            return redirect('admin_admins_create')

        if len(password) < 8:
            messages.error(request, 'Password must be at least 8 characters long.')
            return redirect('admin_admins_create')

        if Admin.objects.filter(email=email).exists():
            messages.error(request, 'Email already exists.')
            return redirect('admin_admins_create')

        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        permissions = None if role == 'super' else (permissions_selected or [])

        Admin.objects.create(
            name=name,
            email=email,
            password=hashed_password,
            role=role,
            permissions=permissions
        )

        messages.success(request, 'Administrator created successfully.')
        return redirect('admin_admins_index')

    return redirect('admin_admins_index')

def admins_edit(request, id):
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return redirect('admin_login')

    admin = get_object_or_404(Admin, id=id)
    permissions = get_permissions_list()
    selected_perms = admin.permissions if isinstance(admin.permissions, list) else []
    return render(request, 'admin/admins/edit.html', {
        'admin': admin,
        'permissionsList': permissions,
        'selectedPermissions': selected_perms
    })

def admins_update(request, id):
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return redirect('admin_login')

    admin = get_object_or_404(Admin, id=id)

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        password_confirmation = request.POST.get('password_confirmation', '')
        role = request.POST.get('role', '').strip()
        permissions_selected = request.POST.getlist('permissions[]') or request.POST.getlist('permissions')

        if not name or not email or not role:
            messages.error(request, 'Name, email, and role are required.')
            return redirect('admin_admins_edit', id=id)

        if password:
            if password != password_confirmation:
                messages.error(request, 'Passwords do not match.')
                return redirect('admin_admins_edit', id=id)
            if len(password) < 8:
                messages.error(request, 'Password must be at least 8 characters long.')
                return redirect('admin_admins_edit', id=id)

        if Admin.objects.filter(email=email).exclude(id=id).exists():
            messages.error(request, 'Email already exists.')
            return redirect('admin_admins_edit', id=id)

        admin.name = name
        admin.email = email
        admin.role = role
        admin.permissions = None if role == 'super' else (permissions_selected or [])

        if password:
            admin.password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

        admin.save()

        messages.success(request, 'Administrator updated successfully.')
        return redirect('admin_admins_index')

    return redirect('admin_admins_index')

def admins_destroy(request, id):
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return JsonResponse({'success': False, 'message': 'Unauthorized'}, status=403)

    if admin_id == id:
        return JsonResponse({'success': False, 'message': 'Unauthorized. You cannot delete your own administrator account.'}, status=403)

    admin = get_object_or_404(Admin, id=id)
    admin.delete()

    return JsonResponse({'success': True, 'message': 'Administrator deleted successfully.'})
