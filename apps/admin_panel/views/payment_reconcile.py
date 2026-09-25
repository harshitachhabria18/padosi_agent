import json
import logging
from decimal import Decimal
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.contrib import messages
from django.utils import timezone
from django.db import transaction

from apps.agents.models import Agent, AgentDraft, AgentSubscription, Invoice
from apps.agents.services.razorpay_checkout import razorpay_client
from apps.agents.services.post_payment import fulfill_invoice_and_welcome
from apps.agents.views.registration import (
    create_agent_from_draft,
    create_or_link_django_user,
    verify_and_activate_pending_payment,
)
from .dashboard import _get_admin_from_session

logger = logging.getLogger(__name__)


def _plan_details_from_amount(amount_rupees: float, notes: dict = None) -> tuple[str, str]:
    """
    Infer plan slug and plan name from paid amount or Razorpay order notes.
    """
    if notes and isinstance(notes, dict):
        if notes.get('plan_type'):
            slug = str(notes.get('plan_type')).strip().lower()
            name = str(notes.get('plan_name') or slug.title())
            return slug, name

    amt = round(float(amount_rupees or 0), 2)
    if amt <= 1.00:
        return 'free_trial', 'Trial Plan'
    if 2000 <= amt <= 3000:
        return 'starter', "Starter's Plan"
    if 5000 <= amt <= 9000:
        return 'professional', "Professional's Plan"
    if amt > 9000:
        return 'exclusive', "Exclusive Plan"

    return 'professional', "Professional's Plan"


@require_http_methods(["GET"])
def payment_reconcile_dashboard(request):
    """
    Admin dashboard for payment reconciliation, recovery, and manual verification.
    Strictly restricted to authenticated admins.
    """
    admin = _get_admin_from_session(request)
    if not admin:
        return redirect("admin_login_page")

    # 1. Agents with pending or failed payment subscriptions
    pending_agents = Agent.objects.filter(
        subscriptions__payment_status__in=['pending', 'failed']
    ).distinct().order_by('-created_at')[:30]

    # 2. Agent drafts with registration step >= 1 where an Agent record was not yet created
    existing_agent_emails = Agent.objects.values_list('email', flat=True)
    pending_drafts = AgentDraft.objects.filter(
        registration_step__gte=1
    ).exclude(
        email__in=existing_agent_emails
    ).order_by('-created_at')[:30]

    # 3. Overall Reconciliation KPIs
    total_invoices_paid = Invoice.objects.filter(payment_status='paid').count()
    total_pending_subs = AgentSubscription.objects.filter(payment_status__in=['pending', 'failed']).count()
    total_orphan_drafts = pending_drafts.count()

    context = {
        'admin': admin,
        'pending_agents': pending_agents,
        'pending_drafts': pending_drafts,
        'stats': {
            'total_invoices_paid': total_invoices_paid,
            'total_pending_subs': total_pending_subs,
            'total_orphan_drafts': total_orphan_drafts,
        }
    }
    return render(request, "admin/payments/reconcile.html", context)


@require_http_methods(["POST"])
def reconcile_inspect_payment(request):
    """
    Secure AJAX endpoint to inspect a Razorpay Payment ID, Order ID, or Agent Email.
    Queries Razorpay live and matches with database records (Agent, Draft, Invoice).
    """
    admin = _get_admin_from_session(request)
    if not admin:
        return JsonResponse({'success': False, 'message': 'Unauthorized admin session'}, status=403)

    try:
        body = json.loads(request.body) if request.body else request.POST
        query = str(body.get('query', '')).strip()
    except Exception:
        query = str(request.POST.get('query', '')).strip()

    if not query:
        return JsonResponse({'success': False, 'message': 'Please provide a Payment ID, Order ID, or Email.'}, status=400)

    client = razorpay_client()
    if not client:
        return JsonResponse({
            'success': False,
            'message': 'Razorpay client is not configured. Please check RAZORPAY_KEY and RAZORPAY_SECRET in environment.'
        }, status=500)

    payment_data = None
    order_id = ''
    payment_id = ''

    # Case A: User entered Razorpay Payment ID (e.g. pay_XXXXX)
    if query.startswith('pay_'):
        try:
            payment_data = client.payment.fetch(query)
            payment_id = query
            order_id = payment_data.get('order_id') or ''
        except Exception as e:
            return JsonResponse({'success': False, 'message': f'Failed to fetch Payment from Razorpay: {str(e)}'}, status=400)

    # Case B: User entered Razorpay Order ID (e.g. order_XXXXX)
    elif query.startswith('order_'):
        try:
            order_id = query
            order_payments = client.order.payments(query)
            items = order_payments.get('items', []) if order_payments else []
            if items:
                # Pick the latest captured/authorized payment or the first one
                successful = [p for p in items if p.get('status') in ('captured', 'authorized')]
                payment_data = successful[0] if successful else items[0]
                payment_id = payment_data.get('id') or ''
            else:
                return JsonResponse({'success': False, 'message': f'No payments found for Order ID {query} on Razorpay.'}, status=404)
        except Exception as e:
            return JsonResponse({'success': False, 'message': f'Failed to fetch Order from Razorpay: {str(e)}'}, status=400)

    # Case C: User entered an Email address
    elif '@' in query:
        email = query.lower()
        # Find order_id from Agent or Draft
        agent = Agent.objects.filter(email__iexact=email).first()
        sub = None
        if agent:
            sub = AgentSubscription.objects.filter(agent=agent).order_by('-created_at').first()

        draft = AgentDraft.objects.filter(email__iexact=email).first()

        target_order_id = (sub.razorpay_order_id if sub and sub.razorpay_order_id else '')
        if not target_order_id and draft and hasattr(draft, 'registration_draft') and isinstance(draft.registration_draft, dict):
            target_order_id = draft.registration_draft.get('razorpay_order_id', '')

        if target_order_id and target_order_id.startswith('order_'):
            try:
                order_id = target_order_id
                order_payments = client.order.payments(target_order_id)
                items = order_payments.get('items', []) if order_payments else []
                if items:
                    successful = [p for p in items if p.get('status') in ('captured', 'authorized')]
                    payment_data = successful[0] if successful else items[0]
                    payment_id = payment_data.get('id') or ''
            except Exception as e:
                logger.warning(f"Could not fetch order {target_order_id} payments: {e}")

        if not payment_data:
            # Check if agent or draft exists in DB anyway to show local details
            db_agent_data = {
                'id': agent.id,
                'name': agent.fullname,
                'email': agent.email,
                'mobile': agent.mobile,
                'status': agent.status,
                'has_paid_invoice': Invoice.objects.filter(agent_email__iexact=email, payment_status='paid').exists()
            } if agent else None

            db_draft_data = {
                'id': draft.id,
                'name': draft.fullname,
                'email': draft.email,
                'mobile': draft.mobile,
                'step': draft.registration_step
            } if draft else None

            return JsonResponse({
                'success': True,
                'has_razorpay': False,
                'message': 'Found database record for email, but no completed Razorpay order found.',
                'agent': db_agent_data,
                'draft': db_draft_data,
            })

    if not payment_data:
        return JsonResponse({'success': False, 'message': 'Payment record not found on Razorpay.'}, status=404)

    # Format Razorpay payload
    amt_paise = payment_data.get('amount', 0)
    amt_rupees = round(amt_paise / 100.0, 2)
    cust_email = str(payment_data.get('email') or '').strip().lower()
    cust_contact = str(payment_data.get('contact') or '').strip()
    status = payment_data.get('status', 'unknown')
    notes = payment_data.get('notes') or {}
    method = payment_data.get('method', 'N/A')

    inferred_slug, inferred_name = _plan_details_from_amount(amt_rupees, notes)

    # Match in Database
    matched_agent = None
    if cust_email:
        matched_agent = Agent.objects.filter(email__iexact=cust_email).first()
    if not matched_agent and order_id:
        sub_match = AgentSubscription.objects.filter(razorpay_order_id=order_id).first()
        if sub_match:
            matched_agent = sub_match.agent

    matched_draft = None
    if not matched_agent and cust_email:
        matched_draft = AgentDraft.objects.filter(email__iexact=cust_email).first()

    existing_invoice = None
    if payment_id:
        existing_invoice = Invoice.objects.filter(razorpay_payment_id=payment_id).first()
    if not existing_invoice and order_id:
        existing_invoice = Invoice.objects.filter(razorpay_order_id=order_id).first()

    return JsonResponse({
        'success': True,
        'has_razorpay': True,
        'razorpay': {
            'payment_id': payment_id,
            'order_id': order_id,
            'amount_rupees': amt_rupees,
            'amount_paise': amt_paise,
            'status': status,
            'is_captured': status in ('captured', 'authorized'),
            'email': cust_email,
            'contact': cust_contact,
            'method': method,
            'notes': notes,
            'inferred_plan_type': inferred_slug,
            'inferred_plan_name': inferred_name,
        },
        'db_match': {
            'agent': {
                'id': matched_agent.id,
                'name': matched_agent.fullname,
                'email': matched_agent.email,
                'mobile': matched_agent.mobile,
                'status': matched_agent.status,
            } if matched_agent else None,
            'draft': {
                'id': matched_draft.id,
                'name': matched_draft.fullname,
                'email': matched_draft.email,
                'mobile': matched_draft.mobile,
                'step': matched_draft.registration_step,
            } if matched_draft else None,
            'invoice': {
                'id': existing_invoice.id,
                'invoice_number': existing_invoice.invoice_number,
                'amount': float(existing_invoice.total_amount),
                'synced_to_sheet': existing_invoice.synced_to_sheet,
            } if existing_invoice else None,
        }
    })


@require_http_methods(["POST"])
def reconcile_execute_payment(request):
    """
    Executes the full recovery pipeline for a verified payment:
    1. Activates or creates Agent
    2. Completes subscription
    3. Generates Invoice record and PDF
    4. Synchronizes to Google Sheets & Drive
    5. Sends welcome email
    """
    admin = _get_admin_from_session(request)
    if not admin:
        return JsonResponse({'success': False, 'message': 'Unauthorized admin session'}, status=403)

    try:
        body = json.loads(request.body) if request.body else request.POST
        payment_id = str(body.get('payment_id', '')).strip()
        order_id = str(body.get('order_id', '')).strip()
        email = str(body.get('email', '')).strip().lower()
        plan_type = str(body.get('plan_type', '')).strip().lower()
        plan_name = str(body.get('plan_name', '')).strip()
        custom_amount = body.get('amount')
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Invalid request data: {str(e)}'}, status=400)

    if not payment_id and not order_id and not email:
        return JsonResponse({'success': False, 'message': 'Payment ID, Order ID, or Email required.'}, status=400)

    client = razorpay_client()
    if not client:
        return JsonResponse({'success': False, 'message': 'Razorpay client is not configured.'}, status=500)

    # 1. Fetch live payment from Razorpay for rock-solid security verification
    payment_record = None
    if payment_id:
        try:
            payment_record = client.payment.fetch(payment_id)
        except Exception as e:
            return JsonResponse({'success': False, 'message': f'Could not verify Payment {payment_id} on Razorpay: {e}'}, status=400)
    elif order_id:
        try:
            order_payments = client.order.payments(order_id)
            items = order_payments.get('items', []) if order_payments else []
            successful = [p for p in items if p.get('status') in ('captured', 'authorized')]
            if successful:
                payment_record = successful[0]
                payment_id = payment_record.get('id')
            else:
                return JsonResponse({'success': False, 'message': f'No captured payments found for Order {order_id}'}, status=400)
        except Exception as e:
            return JsonResponse({'success': False, 'message': f'Could not verify Order {order_id} on Razorpay: {e}'}, status=400)

    if not payment_record or payment_record.get('status') not in ('captured', 'authorized'):
        return JsonResponse({'success': False, 'message': 'Payment is not in captured or authorized status on Razorpay.'}, status=400)

    paid_rupees = round(payment_record.get('amount', 0) / 100.0, 2)
    cust_email = (payment_record.get('email') or email).strip().lower()
    cust_contact = payment_record.get('contact') or ''
    order_id = payment_record.get('order_id') or order_id

    if not plan_type:
        plan_type, plan_name = _plan_details_from_amount(paid_rupees, payment_record.get('notes'))

    logger.info(f"[Reconciliation] Admin #{admin['id']} executing reconciliation for email={cust_email}, payment={payment_id}, amount=₹{paid_rupees}")

    try:
        with transaction.atomic():
            # 2. Check if Agent already exists
            agent = Agent.objects.filter(email__iexact=cust_email).first()

            # 3. If no Agent, check if AgentDraft exists
            if not agent:
                draft = AgentDraft.objects.filter(email__iexact=cust_email).first()
                if draft:
                    agent = create_agent_from_draft(draft, plan_type=plan_type, plan_name=plan_name, status='pending_approval')
                else:
                    # Create basic draft from Razorpay customer info
                    draft = AgentDraft.objects.create(
                        fullname=cust_email.split('@')[0].replace('.', ' ').title(),
                        email=cust_email,
                        mobile=cust_contact or '0000000000',
                        registration_step=2,
                        state='Gujarat',
                    )
                    agent = create_agent_from_draft(draft, plan_type=plan_type, plan_name=plan_name, status='pending_approval')

            # Ensure Agent fields
            agent.status = 'pending_approval'
            agent.plan_type = plan_type
            agent.save(update_fields=['status', 'plan_type', 'updated_at'])

            # 4. Find or create Subscription
            subscription = AgentSubscription.objects.filter(agent=agent).order_by('-created_at').first()
            if not subscription:
                subscription = AgentSubscription.objects.create(
                    agent=agent,
                    selected_plan=plan_name or plan_type.title(),
                    registration_amount=paid_rupees,
                    payment_status='completed',
                    status='active',
                    razorpay_order_id=order_id,
                    razorpay_payment_id=payment_id,
                    starts_at=timezone.now(),
                    expires_at=timezone.now() + timezone.timedelta(days=365)
                )
            else:
                subscription.selected_plan = plan_name or subscription.selected_plan
                subscription.registration_amount = paid_rupees
                subscription.payment_status = 'completed'
                subscription.status = 'active'
                subscription.razorpay_order_id = order_id or subscription.razorpay_order_id
                subscription.razorpay_payment_id = payment_id
                if not subscription.starts_at:
                    subscription.starts_at = timezone.now()
                if not subscription.expires_at:
                    subscription.expires_at = timezone.now() + timezone.timedelta(days=365)
                subscription.save()

            # 5. Link Django User account
            create_or_link_django_user(agent)

            # 6. Execute Fulfill: Invoice generation, PDF, Drive/Sheets sync, Welcome email
            invoice = fulfill_invoice_and_welcome(agent, subscription)

            invoice_number = invoice.invoice_number if invoice else 'Generated'
            sheet_synced = getattr(invoice, 'synced_to_sheet', False)

            return JsonResponse({
                'success': True,
                'message': f"Payment reconciled successfully! Agent {agent.fullname} is activated, Invoice #{invoice_number} generated, and Google Sheet & Drive synced.",
                'agent_id': agent.id,
                'agent_name': agent.fullname,
                'invoice_number': invoice_number,
                'synced_to_sheet': sheet_synced,
            })

    except Exception as e:
        logger.exception(f"[Reconciliation Error] Admin #{admin['id']} failed to reconcile {cust_email}: {e}")
        return JsonResponse({'success': False, 'message': f'Reconciliation transaction failed: {str(e)}'}, status=500)
