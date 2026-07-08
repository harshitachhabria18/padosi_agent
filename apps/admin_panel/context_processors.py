from django.db import connection


def admin_badge_counts(request):
    """
    Injects dynamic sidebar badge counts for all admin pages.

    Mirrors Laravel's layout.blade.php @php badge queries exactly.
    All queries are run in a single DB connection to minimise round-trips.

    Variables injected into every admin template context:
        pending_agents_count    – Pending Approvals  (bg-success)
        incomplete_agents_count – Registration Pending (bg-dark)
        expiring_soon_count     – Renewal Tracker    (bg-danger)
        new_leads_count         – Agent Leads        (bg-warning text-dark)
        pending_contacts_count  – Contact Inbox      (bg-primary)
        pending_reviews_count   – Review Moderation  (bg-warning text-dark)
        unsynced_invoice_count  – Invoices           (#4f46e5)
        active_trial_count      – Free Trial Manager (bg-success)
        unclaimed_rewards_count – Referral System    (#7c3aed)
        geo_missing_count       – Geocoding Manager  (#0891b2)
        total_pincodes_count    – Pincode Manager    (#7c3aed) — always shown if >0
        notif_count             – Bell badge = sum of non-active agents + pending reviews + pending contacts
    """
    if not request.path.startswith('/admin/'):
        return {}

    counts = {
        'pending_agents_count':    0,
        'incomplete_agents_count': 0,
        'expiring_soon_count':     0,
        'new_leads_count':         0,
        'pending_contacts_count':  0,
        'pending_reviews_count':   0,
        'unsynced_invoice_count':  0,
        'active_trial_count':      0,
        'unclaimed_rewards_count': 0,
        'geo_missing_count':       0,
        'total_pincodes_count':    0,
        'insurance_pending_count': 0,
        'notif_count':             0,
    }

    try:
        with connection.cursor() as cursor:

            # 1. Pending Approvals  ── agents.status = 'pending_approval'
            cursor.execute(
                "SELECT COUNT(*) FROM agents WHERE status = 'pending_approval'"
            )
            counts['pending_agents_count'] = cursor.fetchone()[0]

            # 2. Registration Pending ── agents.status IN ('incomplete','pending_payment')
            cursor.execute(
                "SELECT COUNT(*) FROM agents WHERE status IN ('incomplete', 'pending_payment')"
            )
            counts['incomplete_agents_count'] = cursor.fetchone()[0]

            # 3. Renewal Tracker ── subscriptions expiring within 30 days for active agents
            # Mirrors: DB::table('agent_subscriptions as s')
            #   ->join('agents as a', 's.agent_id', '=', 'a.id')
            #   ->where('a.status', 'active')
            #   ->whereBetween('s.expires_at', [now(), now()->addDays(30)])
            try:
                cursor.execute("""
                    SELECT COUNT(*)
                    FROM agent_subscriptions s
                    JOIN agents a ON s.agent_id = a.id
                    WHERE a.status = 'active'
                      AND s.expires_at BETWEEN NOW() AND DATE_ADD(NOW(), INTERVAL 30 DAY)
                """)
                counts['expiring_soon_count'] = cursor.fetchone()[0]
            except Exception:
                counts['expiring_soon_count'] = 0

            # 4. Agent Leads ── agent_leads.lead_status = 'new'
            try:
                cursor.execute(
                    "SELECT COUNT(*) FROM agent_leads WHERE lead_status = 'new'"
                )
                counts['new_leads_count'] = cursor.fetchone()[0]
            except Exception:
                counts['new_leads_count'] = 0

            # 5. Contact Inbox ── contact_submissions.status = 'pending'
            try:
                cursor.execute(
                    "SELECT COUNT(*) FROM contact_submissions WHERE status = 'pending'"
                )
                counts['pending_contacts_count'] = cursor.fetchone()[0]
            except Exception:
                counts['pending_contacts_count'] = 0

            # 6. Review Moderation ── agent_reviews.is_approved = 0
            try:
                cursor.execute(
                    "SELECT COUNT(*) FROM agent_reviews WHERE is_approved = 0"
                )
                counts['pending_reviews_count'] = cursor.fetchone()[0]
            except Exception:
                counts['pending_reviews_count'] = 0

            # 7. Invoices (unsynced to Google Sheet)
            # Mirrors: Invoice::where('synced_to_sheet', false)->count()
            try:
                cursor.execute(
                    "SELECT COUNT(*) FROM invoices WHERE synced_to_sheet = 0"
                )
                counts['unsynced_invoice_count'] = cursor.fetchone()[0]
            except Exception:
                counts['unsynced_invoice_count'] = 0

            # 8. Free Trial Manager ── active trial agents (trial not yet expired)
            # Mirrors: agents WHERE plan_type='free_trial' AND trial_ends_at > now()
            try:
                cursor.execute(
                    "SELECT COUNT(*) FROM agents "
                    "WHERE plan_type = 'free_trial' AND trial_ends_at > NOW()"
                )
                counts['active_trial_count'] = cursor.fetchone()[0]
            except Exception:
                counts['active_trial_count'] = 0

            # 9. Referral System ── unclaimed rewards
            # Mirrors: referral_codes WHERE reward_type IS NOT NULL AND reward_claimed = false
            try:
                cursor.execute(
                    "SELECT COUNT(*) FROM referral_codes "
                    "WHERE reward_type IS NOT NULL AND reward_claimed = 0"
                )
                counts['unclaimed_rewards_count'] = cursor.fetchone()[0]
            except Exception:
                counts['unclaimed_rewards_count'] = 0

            # 10. Geocoding Manager ── agents with pincode but no lat/lng
            # Mirrors: agents WHERE latitude IS NULL AND agent_pincode IS NOT NULL
            try:
                cursor.execute(
                    "SELECT COUNT(*) FROM agents "
                    "WHERE latitude IS NULL AND agent_pincode IS NOT NULL"
                )
                counts['geo_missing_count'] = cursor.fetchone()[0]
            except Exception:
                counts['geo_missing_count'] = 0

            # 11. Pincode Manager ── total pincodes (always shown if > 0)
            try:
                cursor.execute("SELECT COUNT(*) FROM pincodes")
                counts['total_pincodes_count'] = cursor.fetchone()[0]
            except Exception:
                counts['total_pincodes_count'] = 0

            # 11b. Insurance Approvals Pending
            try:
                cursor.execute("SELECT COUNT(*) FROM agent_approval_requests WHERE status = 'pending'")
                counts['insurance_pending_count'] = cursor.fetchone()[0]
            except Exception:
                counts['insurance_pending_count'] = 0

            # 12. Notification Bell ── sum of:
            #     agents WHERE status != 'active'  (includes pending_approval, incomplete, etc.)
            #   + agent_reviews WHERE is_approved = 0
            #   + contact_submissions WHERE status = 'pending'
            # Mirrors Laravel's $notifCount calculation exactly.
            try:
                cursor.execute(
                    "SELECT COUNT(*) FROM agents WHERE status != 'active'"
                )
                non_active_agents = cursor.fetchone()[0]
            except Exception:
                non_active_agents = 0

            notif_count = (
                non_active_agents
                + counts['pending_reviews_count']
                + counts['pending_contacts_count']
            )
            counts['notif_count'] = min(notif_count, 99)

            # 13. Fetch logged in admin details
            try:
                from apps.admin_panel.models.admin_auth import Admin
                token = request.COOKIES.get("session_token")
                if token:
                    cursor.execute("SELECT id FROM user_sessions WHERE session_token = %s AND expires_at > NOW() LIMIT 1", [token])
                    row = cursor.fetchone()
                    if row:
                        session_id = row[0]
                        cursor.execute("SELECT data_value FROM user_session_data WHERE session_id = %s AND data_key = 'admin_id' LIMIT 1", [session_id])
                        d_row = cursor.fetchone()
                        if d_row:
                            admin_id = int(d_row[0])
                            counts['logged_in_admin'] = Admin.objects.filter(id=admin_id).first()
            except Exception:
                pass

    except Exception:
        pass

    return counts
