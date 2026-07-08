"""
apps/admin_panel/views/dashboard.py

Phase 2 — Admin Dashboard Backend

Laravel source: app/Http/Controllers/Admin/AdminDashboardController.php
Migration rules: padosi_migration_plan.md, PROJECT_STRUCTURE.md

Conversion notes:
  - All DB queries are raw SQL via django.db.connection (no ORM models exist yet for
    agents/subscriptions/leads/reviews — models are managed=False placeholders for Phase 3+).
  - Authentication: uses the custom session system (user_sessions + user_session_data tables).
    No Django auth, no django_session. Session token validated via cookie on every protected view.
  - Period filter (?period=3|6|12) preserved exactly as in Laravel.
  - Plan breakdown JSON-decode logic mirrors PHP json_decode() fallback.
  - All MySQL-specific SQL (DATE_FORMAT, DATE_SUB, LAST_DAY, UTC_TIMESTAMP, INTERVAL) is
    preserved as-is — the project uses MySQL (see settings.py).
  - Error handling wraps all DB operations, returning safe zero-defaults on failure —
    matching Laravel's try/catch pattern exactly.
"""

import json
import logging
import secrets
from datetime import datetime, date, timedelta, timezone

import bcrypt

from django.db import connection
from django.shortcuts import render, redirect

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Session Authentication Helper
# ---------------------------------------------------------------------------

def _get_admin_from_session(request):
    """
    Validate the admin session from the session_token cookie.

    Checks:
      1. session_token cookie present
      2. Matching record exists in user_sessions
      3. Session has not expired (expires_at > UTC now)
      4. admin_id stored in user_session_data

    Returns the admin_id (int) if valid, else None.

    Laravel equivalent: App\Http\Middleware\AdminMiddleware (auth guard 'admin').
    """
    token = request.COOKIES.get("session_token")
    if not token:
        return None

    now_utc = datetime.now(timezone.utc)

    try:
        with connection.cursor() as cursor:
            # Validate token against user_sessions
            cursor.execute(
                """
                SELECT id
                FROM user_sessions
                WHERE session_token = %s
                  AND expires_at > %s
                LIMIT 1
                """,
                [token, now_utc],
            )
            row = cursor.fetchone()
            if not row:
                return None

            session_id = row[0]

            # Retrieve admin_id from user_session_data
            # Column names match actual schema: data_key / data_value
            cursor.execute(
                """
                SELECT data_value
                FROM user_session_data
                WHERE session_id = %s
                  AND data_key = 'admin_id'
                LIMIT 1
                """,
                [session_id],
            )
            data_row = cursor.fetchone()
            if not data_row:
                return None

            return int(data_row[0])

    except Exception as exc:
        logger.error("Session validation error: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Auth Views  (login / logout)  — preserved from Phase 1 stubs
# ---------------------------------------------------------------------------

def show_login_form(request):
    """
    Display the admin login page.
    Laravel: AdminAuthController@showLoginForm  →  GET /admin/login
    """
    return render(request, "admin/login.html")


def admin_login(request):
    """
    Handle admin login POST.

    Laravel source: AdminAuthController@login  →  POST /admin/login
    Django route:   POST /admin/login/post/     →  name='admin_login_post'

    Flow:
      1. Read email + password from POST.
      2. Query admins table (raw SQL — no Django auth).
      3. Verify password with bcrypt.checkpw().
      4. On failure  → re-render login.html with error + old_email.
      5. On success  → create user_sessions + user_session_data rows,
                       set session_token cookie, redirect to dashboard.

    Session architecture: custom cookie + user_sessions / user_session_data tables.
    No Django sessions (request.session) are used.
    """
    if request.method != "POST":
        return render(request, "admin/login.html")

    # --- 1. Read credentials ---
    email    = request.POST.get("email",    "").strip()
    password = request.POST.get("password", "")

    if not email or not password:
        return render(request, "admin/login.html", {
            "error":     "Email and password are required.",
            "old_email": email,
        })

    # --- 2. Look up admin by email ---
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, password FROM admins WHERE email = %s LIMIT 1",
                [email],
            )
            row = cursor.fetchone()
    except Exception as exc:
        logger.error("Login DB lookup error: %s", exc)
        return render(request, "admin/login.html", {
            "error":     "A database error occurred. Please try again.",
            "old_email": email,
        })

    if not row:
        return render(request, "admin/login.html", {
            "error":     "Invalid email or password.",
            "old_email": email,
        })

    admin_db_id, stored_hash = row

    # --- 3. Verify password with bcrypt ---
    # stored_hash is a PHP $2y$ bcrypt hash; bcrypt treats $2y$ identically to $2b$
    try:
        password_valid = bcrypt.checkpw(
            password.encode("utf-8"),
            stored_hash.encode("utf-8"),
        )
    except Exception as exc:
        logger.error("bcrypt verification error: %s", exc)
        return render(request, "admin/login.html", {
            "error":     "Authentication error. Please try again.",
            "old_email": email,
        })

    if not password_valid:
        return render(request, "admin/login.html", {
            "error":     "Invalid email or password.",
            "old_email": email,
        })

    # --- 4. Create session ---
    token      = secrets.token_hex(32)                        # 64-char hex string
    now_utc    = datetime.now(timezone.utc)
    expires_at = now_utc + timedelta(days=30)
    ip_address = request.META.get("REMOTE_ADDR", "")[:45]
    user_agent = request.META.get("HTTP_USER_AGENT", "")[:255]

    try:
        with connection.cursor() as cursor:
            # Insert into user_sessions
            cursor.execute(
                """
                INSERT INTO user_sessions
                    (session_token, admin_id, agent_id, distributor_id,
                     ip_address, user_agent, last_activity,
                     expires_at, created_at, updated_at)
                VALUES
                    (%s, %s, NULL, NULL, %s, %s, %s, %s, %s, %s)
                """,
                [
                    token, admin_db_id, ip_address, user_agent,
                    now_utc, expires_at, now_utc, now_utc,
                ],
            )
            session_id = cursor.lastrowid

            # Insert admin_id into user_session_data
            cursor.execute(
                """
                INSERT INTO user_session_data
                    (session_id, data_key, data_value, created_at, updated_at)
                VALUES
                    (%s, %s, %s, %s, %s)
                """,
                [session_id, "admin_id", str(admin_db_id), now_utc, now_utc],
            )
    except Exception as exc:
        logger.error("Session creation error: %s", exc)
        return render(request, "admin/login.html", {
            "error":     "Could not create session. Please try again.",
            "old_email": email,
        })

    # --- 5. Set cookie and redirect ---
    response = redirect("admin_dashboard")
    response.set_cookie(
        "session_token",
        token,
        max_age=30 * 24 * 60 * 60,   # 30 days in seconds
        httponly=True,
        samesite="Lax",
    )
    return response


def admin_logout(request):
    """
    Handle admin logout.

    Laravel source: AdminAuthController@logout  →  GET /admin/logout
    Django route:   GET /admin/logout/           →  name='admin_logout'

    Flow:
      1. Read session_token cookie.
      2. Look up matching user_sessions row.
      3. Delete related user_session_data rows.
      4. Delete the user_sessions row.
      5. Delete the cookie from the browser.
      6. Redirect to login.
    """
    token = request.COOKIES.get("session_token")

    if token:
        try:
            with connection.cursor() as cursor:
                # Find the session row
                cursor.execute(
                    "SELECT id FROM user_sessions WHERE session_token = %s LIMIT 1",
                    [token],
                )
                row = cursor.fetchone()
                if row:
                    session_id = row[0]
                    # Delete session data first (FK child)
                    cursor.execute(
                        "DELETE FROM user_session_data WHERE session_id = %s",
                        [session_id],
                    )
                    # Delete session record
                    cursor.execute(
                        "DELETE FROM user_sessions WHERE id = %s",
                        [session_id],
                    )
        except Exception as exc:
            logger.error("Logout session cleanup error: %s", exc)
            # Continue to delete cookie and redirect even if DB cleanup fails

    response = redirect("admin_login")
    response.delete_cookie("session_token")
    return response


# ---------------------------------------------------------------------------
# Dashboard Statistics Helpers
# ---------------------------------------------------------------------------

def _fetch_agent_counts():
    """
    Fetch total agents, active count, active percent, new this month,
    last month count, growth percent, and distributors count.

    Laravel equivalent (lines 17–35 of AdminDashboardController):
        $totalAgents    = DB::table('agents')->count();
        $activeCount    = DB::table('agents')->where('status', 'active')->count();
        $activePercent  = $totalAgents > 0 ? round(($activeCount / $totalAgents) * 100) : 0;
        $newThisMonth   = DB::table('agents')->whereMonth(...)->whereYear(...)->count();
        $lastMonthCount = DB::table('agents')->whereMonth(sub1)->whereYear(...)->count();
        $growthPercent  = ...
        $distributors   = DB::table('agents')->where('user_types', 'LIKE', '%distributor%')...->count();
    """
    now = datetime.now(timezone.utc)
    this_month = now.month
    this_year = now.year

    # Previous month
    first_of_this_month = now.replace(day=1)
    last_month_dt = first_of_this_month - timedelta(days=1)
    last_month = last_month_dt.month
    last_month_year = last_month_dt.year

    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM agents")
        total_agents = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM agents WHERE status = 'active'")
        active_count = cursor.fetchone()[0]

        active_percent = round((active_count / total_agents) * 100) if total_agents > 0 else 0

        cursor.execute(
            "SELECT COUNT(*) FROM agents WHERE MONTH(created_at) = %s AND YEAR(created_at) = %s",
            [this_month, this_year],
        )
        new_this_month = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(*) FROM agents WHERE MONTH(created_at) = %s AND YEAR(created_at) = %s",
            [last_month, last_month_year],
        )
        last_month_count = cursor.fetchone()[0]

        growth_percent = (
            round(((new_this_month - last_month_count) / last_month_count) * 100)
            if last_month_count > 0
            else 0
        )

        cursor.execute(
            """
            SELECT COUNT(*) FROM agents
            WHERE user_types LIKE %s OR profession LIKE %s
            """,
            ["%distributor%", "%distributor%"],
        )
        distributors = cursor.fetchone()[0]

    return {
        "total_agents": total_agents,
        "active_count": active_count,
        "active_percent": active_percent,
        "new_this_month": new_this_month,
        "last_month_count": last_month_count,
        "growth_percent": growth_percent,
        "distributors": distributors,
        "retention_rate": active_percent,  # Same as activePercent in Laravel
    }


def _fetch_plan_breakdown():
    """
    Fetch subscription plan distribution and compute upgrade rate.

    Laravel equivalent (lines 39–61 of AdminDashboardController):
        $rawPlans = DB::table('agent_subscriptions')
            ->select('selected_plan', DB::raw('count(*) as c'))
            ->groupBy('selected_plan')
            ->pluck('c', 'selected_plan')
            ->toArray();

    The selected_plan column may contain:
      - A plain string:  "Professional's Plan"
      - A JSON string:   '{"name": "Professional\'s Plan", "type": "professional"}'
    Both cases are handled by trying json.loads() first, then falling back to
    the raw string — exactly as PHP json_decode() + json_last_error() does.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT selected_plan, COUNT(*) as c
            FROM agent_subscriptions
            GROUP BY selected_plan
            """
        )
        raw_rows = cursor.fetchall()

    plan_breakdown = {}
    for plan_key, count in raw_rows:
        plan_key = (plan_key or "").strip()
        name = plan_key
        if plan_key.startswith("{"):
            try:
                decoded = json.loads(plan_key)
                name = decoded.get("name") or decoded.get("type") or "Other"
            except (json.JSONDecodeError, ValueError):
                pass
        plan_breakdown[name] = plan_breakdown.get(name, 0) + count

    total_subs = sum(plan_breakdown.values())

    # Exact Laravel logic for counting Professional / Starter plans
    prof_count = plan_breakdown.get("Professional's Plan") or plan_breakdown.get("Professional Plan") or 0
    starter_count = plan_breakdown.get("Starter's Plan") or plan_breakdown.get("Starter Plan") or 0
    upgrade_rate = round((prof_count / total_subs) * 100) if total_subs > 0 else 0

    return {
        "plan_breakdown": plan_breakdown,
        "total_subs": total_subs,
        "prof_count": prof_count,
        "starter_count": starter_count,
        "upgrade_rate": upgrade_rate,
    }


def _fetch_engagement_stats():
    """
    Fetch page views, leads, reviews, contacts, and profile views.

    Laravel equivalent (lines 63–76 of AdminDashboardController):
        $pageViews     = DB::table('sessions')->count();
        $totalLeads    = DB::table('agent_leads')->count();
        $newLeadsToday = DB::table('agent_leads')->whereDate('created_at', today())->count();
        $pendingReviews= DB::table('agent_reviews')->where('is_approved', 0)->count();
        $totalReviews  = DB::table('agent_reviews')->count();
        $pendingContacts = DB::table('contact_submissions')->where('status', 'pending')->count();
        $profileViews  = 0;
        try { $profileViews = DB::table('agent_profile_views')->count(); } catch (\Exception $e) {}

    Note: In Laravel 'sessions' refers to the framework's session table.
    Here we use user_sessions (the custom session table already built in Phase 1).
    """
    today_str = date.today().isoformat()

    with connection.cursor() as cursor:
        # Page views → count from custom session table (equivalent to Laravel's sessions table)
        cursor.execute("SELECT COUNT(*) FROM user_sessions")
        page_views = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM agent_leads")
        total_leads = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(*) FROM agent_leads WHERE DATE(created_at) = %s",
            [today_str],
        )
        new_leads_today = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM agent_reviews WHERE is_approved = 0")
        pending_reviews = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM agent_reviews")
        total_reviews = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(*) FROM contact_submissions WHERE status = 'pending'"
        )
        pending_contacts = cursor.fetchone()[0]

    # profile_views: guarded separately — table may not exist yet
    profile_views = 0
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM agent_profile_views")
            profile_views = cursor.fetchone()[0]
    except Exception as exc:
        logger.debug("agent_profile_views not available: %s", exc)

    return {
        "page_views": page_views,
        "total_leads": total_leads,
        "new_leads_today": new_leads_today,
        "pending_reviews": pending_reviews,
        "total_reviews": total_reviews,
        "pending_contacts": pending_contacts,
        "profile_views": profile_views,
    }


def _fetch_top_agents_by_leads():
    """
    Fetch top 5 agents ranked by total lead count, with WhatsApp/call breakdown.

    Laravel equivalent (lines 79–92 of AdminDashboardController):
        $topAgentsByLeads = DB::table('agent_leads as l')
            ->leftJoin('agents as a', 'l.agent_id', '=', 'a.id')
            ->leftJoin('agent_profiles as ap', 'a.id', '=', 'ap.agent_id')
            ->select('a.id', 'a.fullname', 'ap.display_name',
                     DB::raw('COUNT(*) as lead_count'),
                     DB::raw("SUM(CASE WHEN l.interaction_type = 'whatsapp' THEN 1 ELSE 0 END) as whatsapp_count"),
                     DB::raw("SUM(CASE WHEN l.interaction_type = 'call' THEN 1 ELSE 0 END) as call_count"))
            ->groupBy('a.id', 'a.fullname', 'ap.display_name')
            ->orderByDesc('lead_count')
            ->limit(5)
            ->get();
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                a.id,
                a.fullname,
                ap.display_name,
                COUNT(*) AS lead_count,
                SUM(CASE WHEN l.interaction_type = 'whatsapp' THEN 1 ELSE 0 END) AS whatsapp_count,
                SUM(CASE WHEN l.interaction_type = 'call'     THEN 1 ELSE 0 END) AS call_count
            FROM agent_leads AS l
            LEFT JOIN agents AS a        ON l.agent_id = a.id
            LEFT JOIN agent_profiles AS ap ON a.id     = ap.agent_id
            GROUP BY a.id, a.fullname, ap.display_name
            ORDER BY lead_count DESC
            LIMIT 5
            """
        )
        columns = [col[0] for col in cursor.description]
        rows = cursor.fetchall()

    # Return list of dicts so template accesses work identically to Laravel's $agent->lead_count
    return [dict(zip(columns, row)) for row in rows]


def _fetch_recent_leads():
    """
    Fetch last 5 leads with agent name joined.

    Laravel equivalent (lines 95–100 of AdminDashboardController):
        $recentLeads = DB::table('agent_leads as l')
            ->leftJoin('agents as a', 'l.agent_id', '=', 'a.id')
            ->select('l.*', 'a.fullname as agent_name')
            ->orderByDesc('l.created_at')
            ->limit(5)
            ->get();
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT l.*, a.fullname AS agent_name
            FROM agent_leads AS l
            LEFT JOIN agents AS a ON l.agent_id = a.id
            ORDER BY l.created_at DESC
            LIMIT 5
            """
        )
        columns = [col[0] for col in cursor.description]
        rows = cursor.fetchall()

    return [dict(zip(columns, row)) for row in rows]


def _fetch_mom_data(period_months):
    """
    Fetch month-over-month registration counts for the chart.

    Laravel equivalent (lines 104–110 of AdminDashboardController):
        $momData = DB::select("
            SELECT DATE_FORMAT(created_at, '%b %y') as label, COUNT(*) as total
            FROM agents
            WHERE created_at >= DATE_SUB(LAST_DAY(UTC_TIMESTAMP()), INTERVAL ? MONTH)
            GROUP BY label, YEAR(created_at), MONTH(created_at)
            ORDER BY YEAR(created_at) ASC, MONTH(created_at) ASC
        ", [$periodMonths]);

    The raw MySQL SQL is preserved as-is (project uses MySQL).
    Returns list of dicts: [{'label': 'Jan 24', 'total': 12}, ...]
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT DATE_FORMAT(created_at, '%%b %%y') AS label, COUNT(*) AS total
            FROM agents
            WHERE created_at >= DATE_SUB(LAST_DAY(UTC_TIMESTAMP()), INTERVAL %s MONTH)
            GROUP BY label, YEAR(created_at), MONTH(created_at)
            ORDER BY YEAR(created_at) ASC, MONTH(created_at) ASC
            """,
            [period_months],
        )
        rows = cursor.fetchall()

    return [{"label": row[0], "total": row[1]} for row in rows]


def _fetch_city_data():
    """
    Fetch top 8 cities by agent count.

    Laravel equivalent (lines 113–120 of AdminDashboardController):
        $cityData = DB::select("
            SELECT COALESCE(ap.address, 'Other') as label, COUNT(*) as total
            FROM agents a
            LEFT JOIN agent_profiles ap ON a.id = ap.agent_id
            GROUP BY label
            ORDER BY total DESC
            LIMIT 8
        ");
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT COALESCE(ap.address, 'Other') AS label, COUNT(*) AS total
            FROM agents AS a
            LEFT JOIN agent_profiles AS ap ON a.id = ap.agent_id
            GROUP BY label
            ORDER BY total DESC
            LIMIT 8
            """
        )
        rows = cursor.fetchall()

    return [{"label": row[0], "total": row[1]} for row in rows]


def _fetch_renewal_stats():
    """
    Fetch subscription renewal alert counts (expired, due in 30/60/90 days).

    Laravel equivalent (lines 123–128 of AdminDashboardController):
        $renewalStats = collect(DB::select("SELECT
            SUM(CASE WHEN expires_at < UTC_TIMESTAMP() THEN 1 ELSE 0 END) as expired,
            SUM(CASE WHEN expires_at BETWEEN UTC_TIMESTAMP() AND DATE_ADD(UTC_TIMESTAMP(), INTERVAL 30 DAY) THEN 1 ELSE 0 END) as next_30,
            SUM(CASE WHEN expires_at BETWEEN DATE_ADD(UTC_TIMESTAMP(), INTERVAL 31 DAY) AND DATE_ADD(UTC_TIMESTAMP(), INTERVAL 60 DAY) THEN 1 ELSE 0 END) as next_60,
            SUM(CASE WHEN expires_at BETWEEN DATE_ADD(UTC_TIMESTAMP(), INTERVAL 61 DAY) AND DATE_ADD(UTC_TIMESTAMP(), INTERVAL 90 DAY) THEN 1 ELSE 0 END) as next_90
          FROM agent_subscriptions"))->first();

    Returns dict with keys: expired, next_30, next_60, next_90.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                SUM(CASE WHEN expires_at < UTC_TIMESTAMP() THEN 1 ELSE 0 END) AS expired,
                SUM(CASE WHEN expires_at BETWEEN UTC_TIMESTAMP()
                                              AND DATE_ADD(UTC_TIMESTAMP(), INTERVAL 30 DAY)
                         THEN 1 ELSE 0 END) AS next_30,
                SUM(CASE WHEN expires_at BETWEEN DATE_ADD(UTC_TIMESTAMP(), INTERVAL 31 DAY)
                                              AND DATE_ADD(UTC_TIMESTAMP(), INTERVAL 60 DAY)
                         THEN 1 ELSE 0 END) AS next_60,
                SUM(CASE WHEN expires_at BETWEEN DATE_ADD(UTC_TIMESTAMP(), INTERVAL 61 DAY)
                                              AND DATE_ADD(UTC_TIMESTAMP(), INTERVAL 90 DAY)
                         THEN 1 ELSE 0 END) AS next_90
            FROM agent_subscriptions
            """
        )
        row = cursor.fetchone()

    if row:
        return {
            "expired": int(row[0] or 0),
            "next_30": int(row[1] or 0),
            "next_60": int(row[2] or 0),
            "next_90": int(row[3] or 0),
        }
    return {"expired": 0, "next_30": 0, "next_60": 0, "next_90": 0}


# ---------------------------------------------------------------------------
# Dashboard View
# ---------------------------------------------------------------------------

def admin_dashboard(request):
    """
    Admin dashboard view — aggregates all statistics and renders the dashboard.

    Laravel source:  AdminDashboardController@index  →  GET /admin/dashboard
    Django route:    GET  /admin/dashboard/           →  name='admin_dashboard'

    Session protection:
      Reads session_token cookie → validates against user_sessions / user_session_data.
      If invalid or expired → redirects to admin login.
      (Laravel equivalent: Route::middleware(['admin']) wrapping all admin routes)

    Period filter:
      ?period=3|6|12  (default: 12)
      Controls the MoM registration chart range, exactly as in Laravel.

    Context variables sent to template (identical names to Laravel's compact() call):
      period_months, total_agents, active_count, active_percent,
      new_this_month, growth_percent, distributors, retention_rate,
      upgrade_rate, page_views, total_leads, plan_breakdown,
      starter_count, prof_count, total_subs,
      mom_data, city_data, renewal_stats,
      new_leads_today, pending_reviews, total_reviews,
      pending_contacts, profile_views, top_agents_by_leads, recent_leads
    """
    # --- Session Authentication ---
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return redirect("admin_login")

    # --- Period Filter (Laravel: $periodMonths = in_array(...) ? ... : 12) ---
    try:
        period_months = int(request.GET.get("period", 12))
        if period_months not in (3, 6, 12):
            period_months = 12
    except (ValueError, TypeError):
        period_months = 12

    # --- Default Safe Values (mirrors Laravel catch block, lines 137–160) ---
    context = {
        "period_months":      period_months,
        "total_agents":       0,
        "active_count":       0,
        "active_percent":     0,
        "new_this_month":     0,
        "growth_percent":     0,
        "distributors":       0,
        "retention_rate":     0,
        "plan_breakdown":     {},
        "total_subs":         0,
        "prof_count":         0,
        "starter_count":      0,
        "upgrade_rate":       0,
        "avg_leads_per_agent": 0,
        "page_views":         0,
        "total_leads":        0,
        "new_leads_today":    0,
        "pending_reviews":    0,
        "total_reviews":      0,
        "pending_contacts":   0,
        "profile_views":      0,
        "top_agents_by_leads": [],
        "recent_leads":       [],
        "mom_data":           [],
        "city_data":          [],
        "renewal_stats":      {"expired": 0, "next_30": 0, "next_60": 0, "next_90": 0},
        # JSON-serialised for Chart.js (mirrors @json() in Blade)
        "mom_labels_json":    "[]",
        "mom_totals_json":    "[]",
        "plan_keys_json":     "[]",
        "plan_values_json":   "[]",
    }

    try:
        # Agent counts
        agent_data = _fetch_agent_counts()
        context.update(agent_data)

        # Plan breakdown
        plan_data = _fetch_plan_breakdown()
        context.update(plan_data)

        # Engagement stats
        engagement_data = _fetch_engagement_stats()
        context.update(engagement_data)

        # Avg leads per agent — mirrors Blade: number_format($totalLeads / max(1, $totalAgents), 1)
        _ta = context.get("total_agents", 0) or 1
        context["avg_leads_per_agent"] = round(context.get("total_leads", 0) / _ta, 1)

        # Top agents by leads
        context["top_agents_by_leads"] = _fetch_top_agents_by_leads()

        # Recent leads
        context["recent_leads"] = _fetch_recent_leads()

        # Month-over-month chart data
        mom_data = _fetch_mom_data(period_months)
        context["mom_data"] = mom_data

        # City data
        context["city_data"] = _fetch_city_data()

        # Renewal stats
        context["renewal_stats"] = _fetch_renewal_stats()

        # --- JSON-safe chart data for Chart.js (mirrors @json() in Blade) ---
        context["mom_labels_json"] = json.dumps([row["label"] for row in mom_data])
        context["mom_totals_json"] = json.dumps([row["total"] for row in mom_data])
        context["plan_keys_json"]  = json.dumps(list(context["plan_breakdown"].keys()))
        context["plan_values_json"] = json.dumps(list(context["plan_breakdown"].values()))

    except Exception as exc:
        # Mirrors Laravel: Log::error("Dashboard Data Fetch Error: " . $e->getMessage())
        logger.error("Dashboard Data Fetch Error: %s", exc)
        # context already has safe defaults set above

    return render(request, "admin/dashboard.html", context)