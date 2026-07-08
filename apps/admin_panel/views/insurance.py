import bcrypt
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.core.paginator import Paginator
from django.contrib import messages
from apps.admin_panel.views.dashboard import _get_admin_from_session
from apps.admin_panel.models.users import User
from apps.admin_panel.models.agent import Agent

def insurance_index(request):
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return redirect('admin_login')

    query = User.objects.filter(role='insurance')

    # Search filter
    search = request.GET.get('search', '').strip()
    if search:
        query = query.filter(fullname__icontains=search) | query.filter(email__icontains=search)

    # Status filter
    status = request.GET.get('status', 'all').strip()
    if status != 'all':
        query = query.filter(status=status)

    query = query.order_by('-created_at')

    # For each user, annotate the agent count
    for user in query:
        user.agent_count = Agent.objects.filter(insurance_id=user.id).count()

    # Paginate by 15
    paginator = Paginator(query, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'admin/insurance/index.html', {
        'insurances': page_obj,
        'search': search,
        'selected_status': status
    })

def insurance_show(request, id):
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return redirect('admin_login')

    insurance = get_object_or_404(User, role='insurance', id=id)
    insurance.agent_count = Agent.objects.filter(insurance_id=insurance.id).count()

    # Fetch linked agents
    agents_query = Agent.objects.filter(insurance_id=insurance.id).order_by('-created_at')
    
    # Paginate by 10
    paginator = Paginator(agents_query, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # For each agent, try to load active subscription
    from apps.admin_panel.models.agent_subscription import AgentSubscription
    from django.utils import timezone
    for agent in page_obj:
        agent.active_sub = AgentSubscription.objects.filter(
            agent=agent,
            status='active',
            expires_at__gt=timezone.now()
        ).first()

    active_count = Agent.objects.filter(insurance_id=insurance.id, status='active').count()
    inactive_count = Agent.objects.filter(insurance_id=insurance.id, status='inactive').count()

    return render(request, 'admin/insurance/show.html', {
        'insurance': insurance,
        'agents': page_obj,
        'active_count': active_count,
        'inactive_count': inactive_count,
    })

def insurance_create(request):
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return redirect('admin_login')

    return render(request, 'admin/insurance/create.html')

def insurance_store(request):
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return redirect('admin_login')

    if request.method == 'POST':
        fullname = request.POST.get('fullname', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')

        if not fullname or not email or not password:
            messages.error(request, 'Fullname, email, and password are required.')
            return redirect('admin_insurance_create')

        if len(password) < 8:
            messages.error(request, 'Password must be at least 8 characters long.')
            return redirect('admin_insurance_create')

        if User.objects.filter(email=email).exists():
            messages.error(request, 'Email already exists.')
            return redirect('admin_insurance_create')

        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

        User.objects.create(
            fullname=fullname,
            email=email,
            password=hashed_password,
            role='insurance',
            status='active'
        )

        messages.success(request, f"Insurance company user '{fullname}' created successfully.")
        return redirect('admin_insurance_index')

    return redirect('admin_insurance_index')

def insurance_toggle_status(request):
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return JsonResponse({'success': False, 'message': 'Unauthorized'}, status=403)

    if request.method == 'POST':
        user_id = request.POST.get('id')
        status = request.POST.get('status')

        if not user_id or status not in ['active', 'blocked']:
            return JsonResponse({'success': False, 'message': 'Invalid input'}, status=400)

        user = get_object_or_404(User, role='insurance', id=user_id)
        user.status = status
        user.save()

        return JsonResponse({
            'success': True,
            'message': 'Insurance user status updated successfully.',
            'status': user.status
        })

    return JsonResponse({'success': False, 'message': 'Invalid request method'}, status=405)
