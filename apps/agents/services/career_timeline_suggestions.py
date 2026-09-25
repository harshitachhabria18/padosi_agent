import datetime

# Month names in order (1-indexed): used to convert datetime.month to a name string
MONTHS = [
    '', 'January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December'
]

CLIENT_MILESTONES = (
    (100, 'clients_100', '100+ Families Served'),
    (500, 'clients_500', '500+ Families Served'),
    (1000, 'clients_1000', '1000+ Families Served'),
)
CLAIM_MILESTONES = (
    (100, 'claims_100', '100+ Claims Settled'),
    (500, 'claims_500', '500+ Claims Settled'),
)


def get_career_timeline_suggestions(agent):
    """
    Generate auto-detected career timeline suggestions based on agent details.
    Does NOT write to the database. Handles missing/blank fields gracefully.

    Returns a list of dicts:
    [
        {
            'key': str,           # Stable identifier for de-duplication
            'title': str,
            'subtitle': str,
            'event_type': str,    # Maps to career_timelines[idx][type]
            'month': str or '',   # '' means "user must fill in"
            'year': str or '',    # '' means "user must fill in"
            'source_field': str   # Which model field drove this suggestion
        }, ...
    ]

    Suggestions are ordered by conceptual chronology:
      career_start → licensed_agent → arn_distributor →
      clients_100 → clients_500 → clients_1000 → families_current →
      claims_100 → claims_500
    """
    suggestions = []
    now = datetime.datetime.now()
    current_year = now.year
    current_month = MONTHS[now.month]   # e.g. "August"

    # ── 1. Career Start (Year auto-calculated; Month left blank for user) ──────
    try:
        exp_years = agent.experience_years          # property on Agent model
        if exp_years and int(exp_years) > 0:
            start_year = current_year - int(exp_years)
            suggestions.append({
                'key': 'career_start',
                'title': 'Started Insurance Career',
                'subtitle': f'Based on {exp_years} years of experience — year auto-calculated',
                'event_type': 'Career',
                'month': '',            # No issue-month available
                'year': str(start_year),
                'source_field': 'experience_years',
            })
    except Exception:
        pass

    # ── 2. IRDAI License (no issue-date stored → both blank) ─────────────────
    try:
        profile = agent.get_primary_profile()
        if profile and profile.license_number:
            suggestions.append({
                'key': 'licensed_agent',
                'title': 'Licensed Insurance Agent (IRDAI)',
                'subtitle': f'License: {profile.license_number}',
                'event_type': 'Certification',
                'month': '',
                'year': '',
                'source_field': 'license_number',
            })
    except Exception:
        pass

    # ── 3. AMFI ARN (no registration-date stored → both blank) ──────────────
    try:
        profile = agent.get_primary_profile()
        if profile and profile.arn_number:
            suggestions.append({
                'key': 'arn_distributor',
                'title': 'AMFI Registered Mutual Fund Distributor',
                'subtitle': f'ARN: {profile.arn_number}',
                'event_type': 'Certification',
                'month': '',
                'year': '',
                'source_field': 'arn_number',
            })
    except Exception:
        pass

    # ── 4. Families Served — threshold milestones (date unknown → both blank) ─
    #   Independent `if` checks so BOTH fire for clients >= 500.
    try:
        if agent.client_base:
            clients = int(agent.client_base)

            if clients >= 100:
                suggestions.append({
                    'key': 'clients_100',
                    'title': '100+ Families Served',
                    'subtitle': 'Past milestone — pick the month & year it was reached',
                    'event_type': 'Milestone',
                    'month': '',
                    'year': '',
                    'source_field': 'client_base',
                })

            if clients >= 500:
                suggestions.append({
                    'key': 'clients_500',
                    'title': '500+ Families Served',
                    'subtitle': 'Past milestone — pick the month & year it was reached',
                    'event_type': 'Milestone',
                    'month': '',
                    'year': '',
                    'source_field': 'client_base',
                })

            if clients >= 1000:
                suggestions.append({
                    'key': 'clients_1000',
                    'title': '1000+ Families Served',
                    'subtitle': 'Past milestone — pick the month & year it was reached',
                    'event_type': 'Milestone',
                    'month': '',
                    'year': '',
                    'source_field': 'client_base',
                })

            # ── 5. Families Currently Advised (snapshot "as of today") ─────────
            #   This represents the agent's *current* standing, so pre-fill today.
            if clients > 0:
                suggestions.append({
                    'key': 'families_current',
                    'title': f'{clients} Families Advised',
                    'subtitle': f'Current standing as of {current_month} {current_year}',
                    'event_type': 'Achievement',
                    'month': current_month,
                    'year': str(current_year),
                    'source_field': 'client_base',
                })
    except (ValueError, TypeError):
        pass

    # ── 6. Claims Settled — threshold milestones (date unknown → both blank) ──
    #   Independent `if` checks so BOTH fire for claims >= 500.
    try:
        perf = getattr(agent, 'performanceStats', None)
        if perf and perf.claims_settled:
            claims = int(perf.claims_settled)

            if claims >= 100:
                suggestions.append({
                    'key': 'claims_100',
                    'title': '100+ Claims Settled',
                    'subtitle': 'Past milestone — pick the month & year it was reached',
                    'event_type': 'Milestone',
                    'month': '',
                    'year': '',
                    'source_field': 'claims_settled',
                })

            if claims >= 500:
                suggestions.append({
                    'key': 'claims_500',
                    'title': '500+ Claims Settled',
                    'subtitle': 'Past milestone — pick the month & year it was reached',
                    'event_type': 'Milestone',
                    'month': '',
                    'year': '',
                    'source_field': 'claims_settled',
                })
    except (ValueError, TypeError):
        pass

    return suggestions


def get_career_timeline_next_milestones(agent):
    """
    Upcoming client/claims targets the agent has not reached yet (mobile nudges).
    Returns at most one next target per metric.
    """
    hints = []

    try:
        clients = int(agent.client_base or 0)
        for threshold, key, title in CLIENT_MILESTONES:
            if clients < threshold:
                hints.append({
                    'key': key,
                    'title': title,
                    'subtitle': f'You have {clients} — reach {threshold} to unlock this milestone',
                    'event_type': 'Milestone',
                    'target_value': threshold,
                    'current_value': clients,
                    'source_field': 'client_base',
                })
                break
    except (ValueError, TypeError):
        pass

    try:
        perf = getattr(agent, 'performanceStats', None)
        claims = int(perf.claims_settled) if perf and perf.claims_settled else 0
        for threshold, key, title in CLAIM_MILESTONES:
            if claims < threshold:
                hints.append({
                    'key': key,
                    'title': title,
                    'subtitle': f'You have {claims} settled — reach {threshold} to unlock this milestone',
                    'event_type': 'Milestone',
                    'target_value': threshold,
                    'current_value': claims,
                    'source_field': 'claims_settled',
                })
                break
    except (ValueError, TypeError):
        pass

    return hints
