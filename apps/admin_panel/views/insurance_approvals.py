import os
import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.core.paginator import Paginator
from django.contrib import messages
from django.utils import timezone
from django.db import transaction
from apps.admin_panel.views.dashboard import _get_admin_from_session
from apps.admin_panel.models.insurance_approval import AgentApprovalRequest
from apps.admin_panel.models.agent import Agent
from apps.admin_panel.models.users import User
from apps.admin_panel.models.referral_code import ReferralCode

logger = logging.getLogger(__name__)

def insurance_approvals_index(request):
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return redirect('admin_login')

    # Query status toggle requests
    status_filter = request.GET.get('status', 'all').strip()
    query = AgentApprovalRequest.objects.all()
    if status_filter != 'all':
        query = query.filter(status=status_filter)
    
    # Order: pending first, then by -created_at
    query = query.order_by('status', '-created_at')

    paginator = Paginator(query, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    pending_count = AgentApprovalRequest.objects.filter(status='pending').count()

    # Query new agent onboarding applications awaiting admin approval
    pending_onboardings = Agent.objects.filter(status='pending_admin_approval').order_by('-created_at')

    # Load associated details for onboarding agents
    for agent in pending_onboardings:
        # Load user
        try:
            agent.associated_user = User.objects.get(id=agent.user_id)
        except User.DoesNotExist:
            agent.associated_user = None

        # Load insurance company user
        if agent.insurance_id:
            try:
                agent.insurance_company_user = User.objects.get(id=agent.insurance_id, role='insurance')
            except User.DoesNotExist:
                agent.insurance_company_user = None
        else:
            agent.insurance_company_user = None

        # Load onboarded_by
        onboarded_by_id = getattr(agent, 'onboarded_by', None)
        if onboarded_by_id:
            try:
                agent.onboarder = User.objects.get(id=onboarded_by_id)
            except User.DoesNotExist:
                agent.onboarder = None
        else:
            agent.onboarder = None

        # Load subscription details
        from apps.admin_panel.models.agent_subscription import AgentSubscription
        agent.completed_sub = AgentSubscription.objects.filter(agent=agent, payment_status='completed').first()

    return render(request, 'admin/insurance_approvals.html', {
        'requests': page_obj,
        'pendingCount': pending_count,
        'pendingOnboardings': pending_onboardings,
        'selected_status': status_filter
    })

def insurance_approvals_process(request, id):
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return redirect('admin_login')

    approval_request = get_object_or_404(AgentApprovalRequest, id=id)

    if not approval_request.is_pending():
        messages.error(request, 'This request has already been processed.')
        return redirect('admin_insurance_approvals_index')

    if request.method == 'POST':
        decision = request.POST.get('decision')
        admin_note = request.POST.get('admin_note', '').strip()

        if decision not in ['approved', 'rejected']:
            messages.error(request, 'Invalid decision value.')
            return redirect('admin_insurance_approvals_index')

        with transaction.atomic():
            approval_request.status = decision
            approval_request.admin_note = admin_note
            approval_request.processed_by_id = admin_id
            approval_request.processed_at = timezone.now()
            approval_request.save()

            if decision == 'approved':
                agent = approval_request.agent
                new_status = 'active' if approval_request.action == 'activate' else 'inactive'
                agent.status = new_status
                agent.save()
                logger.info(f"Admin approved insurance status change: agent #{agent.id} -> {new_status}")

        label = 'approved' if decision == 'approved' else 'rejected'
        messages.success(request, f"Request has been {label} successfully.")
        return redirect('admin_insurance_approvals_index')

    return redirect('admin_insurance_approvals_index')

def insurance_approvals_approve_onboarding(request, id):
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return redirect('admin_login')

    agent = get_object_or_404(Agent, id=id)

    if request.method == 'POST':
        try:
            with transaction.atomic():
                # 1. Activate Agent status
                agent.status = 'active'
                agent.save()

                # 2. Activate User account
                try:
                    user = User.objects.get(id=agent.user_id)
                    user.status = 'active'
                    user.save()
                except User.DoesNotExist:
                    user = None

                # 3. Activate associated subscription
                from apps.admin_panel.models.agent_subscription import AgentSubscription
                subscription = AgentSubscription.objects.filter(agent=agent, payment_status='completed').first()
                if subscription:
                    subscription.status = 'active'
                    subscription.save()

                # 4. Generate referral code
                try:
                    ReferralCode.generateForAgent(agent)
                except Exception as e:
                    logger.error(f"Failed to generate referral code: {e}")

            # 5. Generate Invoice and send welcome credentials email
            try:
                from apps.agents.services.invoice import invoice_service
                from apps.agents.services.brevo import email_service
                from django.conf import settings

                pdf_path = None
                if subscription:
                    invoice = invoice_service.generate_from_subscription(agent, subscription)
                    if invoice and invoice.pdf_path:
                        pdf_path = os.path.join(settings.MEDIA_ROOT, 'app', 'private', invoice.pdf_path)

                email_service.send_welcome(
                    to_email=agent.email,
                    to_name=agent.fullname,
                    temp_password=agent.email,
                    plan_name=subscription.selected_plan if subscription else "Basic Plan",
                    attachment_path=pdf_path
                )
            except Exception as mail_err:
                logger.error(f"Failed to generate invoice/send welcome email during approval: {mail_err}")

            messages.success(request, f"Agent {agent.fullname} onboarding approved and account activated successfully.")
        except Exception as err:
            logger.error(f"Admin onboarding approval failed: {err}")
            messages.error(request, 'Failed to approve onboarding. Please try again.')

        return redirect('admin_insurance_approvals_index')

    return redirect('admin_insurance_approvals_index')

def insurance_approvals_reject_onboarding(request, id):
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return redirect('admin_login')

    agent = get_object_or_404(Agent, id=id)

    if request.method == 'POST':
        admin_note = request.POST.get('admin_note', '').strip()
        if not admin_note:
            messages.error(request, 'Specify the reason for rejection.')
            return redirect('admin_insurance_approvals_index')

        try:
            with transaction.atomic():
                agent.status = 'rejected'
                agent.admin_notes = f"Rejected Onboarding: {admin_note}"
                agent.save()

                # Deactivate user account
                try:
                    user = User.objects.get(id=agent.user_id)
                    user.status = 'inactive'
                    user.save()
                except User.DoesNotExist:
                    pass

                # Mark subscription failed
                from apps.admin_panel.models.agent_subscription import AgentSubscription
                subscription = AgentSubscription.objects.filter(agent=agent, payment_status='completed').first()
                if subscription:
                    subscription.payment_status = 'failed'
                    subscription.status = 'inactive'
                    subscription.save()

            messages.success(request, f"Agent {agent.fullname} onboarding has been rejected.")
        except Exception as err:
            logger.error(f"Admin onboarding rejection failed: {err}")
            messages.error(request, 'Failed to reject onboarding. Please try again.')

        return redirect('admin_insurance_approvals_index')

    return redirect('admin_insurance_approvals_index')
