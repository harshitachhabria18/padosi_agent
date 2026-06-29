from django.utils import timezone
from apps.agents.models import Agent, AgentSubscription, AgentLead, AgentReview
from apps.admin_panel.models import ContactSubmission
from django.db import connection

def sidebar_counts(request):
    """
    Provides global counts for the admin sidebar so they are available in layout.html
    without having to pass them in every view function.
    """
    # Only compute if user is logged in as admin (session check)
    if not request.session.get('admin_id'):
        return {}

    try:
        now = timezone.now()
        
        # 1. Pending Approvals count (status != active, or status = pending_approval)
        pending_approvals_count = Agent.objects.filter(status='pending_approval').count()
        
        # 2. Checkout Pending Count (incomplete or pending_payment)
        checkout_count = Agent.objects.filter(status__in=['incomplete', 'pending_payment']).count()
        
        # 3. Expiring Soon Count
        expiring_soon_count = AgentSubscription.objects.filter(
            agent__status='active',
            expires_at__range=(now, now + timezone.timedelta(days=30))
        ).count()
        
        # 4. New Leads Count
        new_leads_count = AgentLead.objects.filter(lead_status='new').count()
        
        # 5. Pending Contacts Count
        pending_contacts_count = ContactSubmission.objects.filter(status='pending').count()
        
        # 6. Pending Reviews Count
        pending_reviews_count = AgentReview.objects.filter(is_approved=False).count()
        
        # 7. Active Trial Count
        active_trial_count = Agent.objects.filter(
            plan_type='free_trial',
            trial_ends_at__gt=now
        ).count()
        
        # 8. Unclaimed Rewards Count
        unclaimed_rewards_count = 0
        try:
            from apps.admin_panel.models import ReferralCode
            unclaimed_rewards_count = ReferralCode.objects.filter(reward_claimed=False).exclude(reward_type=None).count()
        except Exception:
            pass
            
        # 9. Geo Missing Count
        geo_missing_count = Agent.objects.filter(latitude__isnull=True).exclude(agent_pincode=None).exclude(agent_pincode='').count()
        
        # 10. Total Pincodes Count
        total_pincodes_count = 0
        with connection.cursor() as cursor:
            try:
                cursor.execute("SELECT COUNT(*) FROM pincodes")
                total_pincodes_count = cursor.fetchone()[0]
            except Exception:
                pass

        # Sum total notifications count for the top navbar bell badge
        notif_count = pending_approvals_count + pending_reviews_count + pending_contacts_count

        return {
            'sidebar_pending_approvals_count': pending_approvals_count,
            'sidebar_checkout_count': checkout_count,
            'sidebar_expiring_soon_count': expiring_soon_count,
            'sidebar_new_leads_count': new_leads_count,
            'sidebar_pending_contacts_count': pending_contacts_count,
            'sidebar_pending_reviews_count': pending_reviews_count,
            'sidebar_active_trial_count': active_trial_count,
            'sidebar_unclaimed_rewards_count': unclaimed_rewards_count,
            'sidebar_geo_missing_count': geo_missing_count,
            'sidebar_total_pincodes_count': total_pincodes_count,
            'sidebar_notif_count': notif_count,
        }

    except Exception:
        return {}
