        # PadosiAgent — Project Bible for Claude Code

        > Read this fully before touching ANY file. This project has multiple auth systems, a hybrid Django+FastAPI stack, and shared database tables. One wrong assumption breaks production.

        ---

        ## 1. What This Project Does

        **PadosiAgent** (`padosiagent.com`) is an **insurance agent marketplace** in India.
        - Public users search for nearby insurance agents by pincode/city/type
        - Insurance agents register, pay a subscription, and get a profile card + leads
        - Admin manages all agents, subscriptions, approvals, referrals
        - Insurance companies onboard and manage their agents via a separate portal
        - Distributors onboard agents on behalf of companies
        - Chatbot (AI) helps users find agents

        **Original stack:** Laravel + PHP → **Ported to Django + FastAPI** (this repo)

        ---

        ## 2. Technology Stack

        | Layer | Technology |
        |---|---|
        | Framework | Django 5.2 (web), FastAPI 0.139 (mobile API) |
        | Language | Python 3.11+ |
        | Database | MySQL / MariaDB |
        | ORM | Django ORM (web), SQLAlchemy 2.0 (FastAPI) |
        | Schema migration | Django migrations (web), Alembic (FastAPI — rarely used) |
        | Payments | Razorpay |
        | Email | Brevo (primary API) → Django SMTP (fallback) |
        | Push notifications | Firebase FCM |
        | Image storage | Cloudinary (agent photos) + local `media/` |
        | LLM / AI | Groq (primary) → Gemini → OpenRouter (fallback chain) |
        | Chatbot | Groq/Gemini LLM via `apps/chatbot/llm_client.py` |
        | Static files | WhiteNoise (compressed + hashed manifests) |
        | Session | `cached_db` (file cache + MySQL) |
        | Cache | File-based cache (`cache/` dir, 5-min TTL) |
        | Auth tokens | bcrypt (agent/admin) + JWT via python-jose (FastAPI) |
        | ASGI server | Daphne (production) |
        | WSGI server | Gunicorn |
        | Deployment | GoDaddy shared hosting, Apache reverse proxy, SSH deploy via GitHub Actions |

        ---

        ## 3. Repository Structure

        ```
        padosi_agent_aws-main/
        ├── manage.py
        ├── requirements.txt
        ├── password_hashing.py          ← SHARED bcrypt helper (Django + FastAPI both use this)
        ├── .env.example                 ← Copy to .env, never commit .env
        ├── padosi_agent/                ← Django project config
        │   ├── settings.py
        │   ├── urls.py                  ← Root URL router
        │   ├── asgi.py                  ← ASGI: FastAPI at /api, Django at /
        │   ├── wsgi.py
        │   ├── middleware.py            ← StaleCookieSanitizer, AutoCsrf, SEO middlewares
        │   ├── razorpay_env.py          ← Razorpay credential loading (multi-env safe)
        │   ├── storage.py               ← SingleThreadedCompressedManifestStaticFilesStorage
        │   ├── sitemaps.py
        │   └── views.py                 ← csrf_failure_view, csrf_refresh_api
        ├── apps/
        │   ├── home/                    ← Public website (homepage, find-agents, calculators, CMS)
        │   ├── agents/                  ← Agent registration, auth, dashboard, payment, profile
        │   ├── admin_panel/             ← Internal admin portal (NOT Django admin)
        │   ├── insurance/               ← Insurance company portal
        │   ├── distributors/            ← Distributor portal
        │   ├── chatbot/                 ← AI chatbot (Groq/Gemini LLM)
        │   └── referral_championship/   ← Gamified referral campaign system
        ├── fastapi_app/                 ← FastAPI mobile API (mounted at /api)
        │   ├── main.py                  ← App factory + router includes
        │   ├── config.py                ← Pydantic Settings (reads same .env)
        │   ├── database.py              ← SQLAlchemy engine (same MySQL DB)
        │   ├── models/                  ← SQLAlchemy models (mirror Django models)
        │   ├── routers/                 ← FastAPI routers (auth, dashboard, profile, etc.)
        │   ├── schemas/                 ← Pydantic request/response schemas
        │   ├── services/                ← Business logic
        │   ├── repositories/            ← DB access layer
        │   ├── middleware/              ← CORS, rate limit, threat monitor, API logger
        │   ├── dependencies/            ← auth.py (JWT), ip_whitelist.py
        │   └── utils/                   ← auth helpers, datetime, image validation
        ├── templates/                   ← Django templates (DTL)
        ├── static/                      ← CSS, JS, images (source)
        ├── staticfiles/                 ← Collected static (WhiteNoise serves this)
        ├── media/                       ← User uploads (agent photos, invoices)
        ├── logs/                        ← Django rotating logs (NOT in media/)
        ├── cache/                       ← File-based cache dir
        └── scripts/
            └── deploy_godaddy.sh        ← SSH deploy script
        ```

        ---

        ## 4. Architecture: How Requests Flow

        ### Web (Django)
        ```
        Browser → Apache → Daphne/Gunicorn → Django ASGI/WSGI
                                            → padosi_agent/urls.py
                                            → App URLconfs (home, agents, admin_panel, etc.)
                                            → Views → Services → Django ORM → MySQL
        ```

        ### Mobile App API (FastAPI)
        ```
        Mobile App → Apache → Daphne → ASGI router (asgi.py)
                                    → /api/** → FastAPI (fastapi_app/main.py)
                                                → Routers → Services → SQLAlchemy → MySQL
                                    → /** → Django
        ```

        **CRITICAL:** Django and FastAPI share the **same MySQL database**. Django ORM models and SQLAlchemy models mirror each other on the same tables.

        ### ASGI Mount (asgi.py)
        ```python
        # FastAPI at /api — Django at /
        application = Starlette(routes=[
            Mount("/api", app=fastapi_application),
            Mount("/", app=django_application),
        ])
        # If FastAPI fails to load → Django-only fallback (graceful degradation)
        ```

        ---

        ## 5. Django Apps — Responsibilities

        | App | URL Prefix | Purpose |
        |---|---|---|
        | `apps.home` | `/` | Public pages: homepage, find-agents, calculators, CMS pages, pincode check |
        | `apps.agents` | `/agent*`, `/profile/*`, `/join/*`, `/participants/*` | Agent auth, registration, payment, dashboard, profile, leads, events |
        | `apps.admin_panel` | `/admin/*` | Internal admin portal (separate from `/django-admin/`) |
        | `apps.insurance` | `/insurance/*` | Insurance company portal (manager/sales/onboarding/accounts roles) |
        | `apps.distributors` | `/distributor/*` | Distributor portal + sub-distributor portal |
        | `apps.chatbot` | `/chatbot-api/` | LLM chatbot endpoint |
        | `apps.referral_championship` | `/agent/championship/*`, `/admin/championship/*` | Gamified referral campaign |

        ---

        ## 6. Database Conventions — READ CAREFULLY

        ### Critical settings
        ```python
        USE_TZ = False           # No timezone awareness on datetimes — NEVER use timezone.now() for comparisons
        TIME_ZONE = 'Asia/Kolkata'
        DEFAULT_AUTO_FIELD = 'django.db.backends.BigAutoField'
        ```

**`USE_TZ = False` means:**
- `auto_now_add=True` / `auto_now=True` → naive datetimes (no tzinfo)
- Use `datetime.datetime.now()` not `timezone.now()` for manual datetime creation
- Exception: the referral_championship app has `if settings.USE_TZ` guards — follow that pattern

### Managed vs Unmanaged tables

| Pattern | Meaning |
|---|---|
| `managed = True` (default) | Django controls the table. Run `makemigrations` when model changes. |
| `managed = False` | Table was created by Laravel or manually. Django reads/writes but NEVER creates/alters it. |

**Unmanaged tables** (do NOT migrate): `admins`, `security_threat_logs`, `users` (LaravelUser), `blocked_ips`

**Partially mirrored tables**: `agents`, `agent_profiles`, `agent_subscriptions` — both Django ORM and SQLAlchemy models exist for the same table.

### Key models and their tables

| Django Model | Table | Notes |
|---|---|---|
| `Agent` (apps.agents) | `agents` | Core agent row, links to `auth.User` via FK |
| `AgentDraft` | `agent_drafts` | Registration in-progress |
| `AgentProfile` (admin_panel) | `agent_profiles` | Extended profile (OneToOne with Agent) |
| `AgentSubscription` | `agent_subscriptions` | Payment records |
| `Invoice` | `invoices` | PDF invoice records |
| `SubscriptionPlan` | `subscription_plans` | Admin-configured plans |
| `Admin` | `admins` | **managed=False**, bcrypt passwords, Laravel legacy |
| `User` (LaravelUser) | `users` | **managed=False**, PHP Laravel users table |
| `InsuranceProfile` | `insurance_profiles` | OneToOne with `auth.User` for insurance portal |
| `SubDistributor` | `sub_distributors` | Distributor sub-accounts |
| `ChampionshipCampaign` | `championship_campaigns` | Referral championship |
| `ChatSession/ChatMessage` | `chatbot_*` | AI chatbot sessions |

### Adding a new model
1. Add to `apps/<app>/models.py` (or `models/<file>.py`)
2. Export in `models/__init__.py` if model-per-file pattern
3. `python manage.py makemigrations <app>`
4. `python manage.py migrate`
5. Mirror in `fastapi_app/models/<name>.py` (SQLAlchemy) if mobile API needs it

---

## 7. Authentication Systems — THREE SEPARATE SYSTEMS

### 7.1 Agent Authentication (Web)
- **Table:** `agents` + `auth_user` (linked via `Agent.user` FK)
- **Password:** bcrypt via `password_hashing.py` — NOT Django PBKDF2
- **Login flow:** `apps/agents/views/auth.py` → `account_auth.py` → `check_password_hash()` → `login(request, django_user)`
- **Session key:** `request.session['agent_id']`
- **Dashboard gate:** `agent_can_access_dashboard(agent)` — requires real Razorpay payment (not mock)
- **Decorator:** `@login_required` + check `request.session.get('agent_id')`
- **Google OAuth:** `/auth/google/` → `/auth/google/callback/`
- **Agent status flow:** `incomplete` → `pending_payment` → `pending_accounts_payment` → `active`

### 7.2 Admin Panel Authentication
- **Table:** `admins` (managed=False, Laravel table)
- **Password:** bcrypt via `password_hashing.py`
- **Login flow:** `apps/admin_panel/views/admins.py` → raw SQL on `admins` table → session
- **Session keys:** `admin_id`, `admin_name`, `admin_role`, `admin_permissions`
- **Roles:** `superadmin`, `staff` (with JSON permissions)
- **Decorator:** `apps/admin_panel/decorators.py` → `@admin_required`
- **IP whitelist:** `ADMIN_WHITELIST_IPS` env var (middleware: `AdminIpWhitelistMiddleware` — commented out)
- **Session isolation:** `IsolateAdminAgentSessionsMiddleware` prevents cookie conflicts

### 7.3 Insurance Portal Authentication
- **Table:** `auth_user` + `insurance_profiles` (OneToOne)
- **Login:** Django's built-in `LoginView` at `/insurance-login/`
- **Roles:** `manager`, `onboarding`, `sales`, `accounts` (from `InsuranceProfile.insurance_sub_role`)
- **Permission check:** `decorators.py` in insurance app

### 7.4 Distributor Authentication
- **Table:** `users` (LaravelUser, managed=False) for parent distributors
- **Sub-distributors:** `sub_distributors` table via `SubDistributor` model
- **Password:** bcrypt via `password_hashing.py`
- **Session key:** `distributor_id` or `sub_distributor_id`

### 7.5 FastAPI JWT Authentication
- **Tokens:** JWT (python-jose), `Authorization: Bearer <token>`
- **Config:** `JWT_SECRET_KEY`, `JWT_ALGORITHM=HS256`, expire 120 min access / 7 days refresh
- **Dependency:** `fastapi_app/dependencies/auth.py` → `get_current_agent()`
- **Password:** Same `password_hashing.py` bcrypt

### Reality check (verified in 2026-09-23 security audit)
- Web agent identity is actually `request.user` → `resolve_agent_for_user()` (matches/re-links an Agent by **email**). Nothing sets `session['agent_id']` in normal login and there is no `@agent_required` decorator. Consequence: **any code path that logs a session into an `auth_user` whose email equals an agent's email hands over that agent's dashboard.**
- Sub-distributor portal auth: `_portal_sub_distributor_id()` — `session['sub_distributor_portal_id']` (set only by `_start_sub_distributor_session`), or a pre-upgrade login session holding matching `sub_distributor_id` + `sub_distributor_code`. `session['sub_distributor_id']` alone is referral attribution written by public `/join/<code>/` links — never use it for auth.

### Security invariants (do not regress — see `apps/agents/test_audit_security.py`)
1. Payment endpoints never trust a client-supplied `agent_id` / `plan_type` / `plan_name`. The agent comes from the paid order; login only when the session owns the checkout (`_session_owns_agent()`) or the request carries a valid Razorpay signature for that order (`_payer_signature_valid()`); the plan comes from `subscription.selected_plan` (`_order_plan_slug`).
2. Passwordless flows (`client_quick_register`, `fb_ad_signup`) must never `login()` a portal user (`_is_portal_user`) or create an `auth_user` for an email owned by an agent/portal account (`_email_belongs_to_portal_account`).
3. (Owner decision) New agents' temporary password is their email and the welcome email says so — intentionally unchanged.
4. Client IP = `ThreatMonitorMiddleware.get_client_ip()` (Django) / `fastapi_app.utils.client_ip.get_client_ip()` — never `X-Forwarded-For.split(',')[0]`.
5. Data embedded in `<script>`: use `{% load json_tags %}{{ value|safe_json }}`, never `json.dumps(...)|safe`. Server JSON that JS inserts via `innerHTML` must be HTML-escaped at the source. Admin/CMS-authored HTML renders with `{% load html_tags %}{{ value|clean_html }}`, never `|safe` or `{% autoescape off %}`. Raw HTML CMS pages (`Page.is_raw_code`) are served as-is; only a Super Admin may save script-enabled raw content (`raw_script_save_blocked` in `admin_panel/views/pages.py`).
6. Changing an agent's email must be rejected if the address belongs to any other `auth_user`/`users` row.
7. Private files: normalise the path before any ownership check (`serve_private_file`).

### NEVER mix auth systems
- Do NOT use `request.user.is_authenticated` to check if an agent is logged in
- Do NOT use Django sessions to pass data to FastAPI
- Admin session and Agent session are **intentionally isolated** by middleware

---

## 8. Password Hashing — CRITICAL

**File:** `password_hashing.py` (project root, imported everywhere)

```python
from password_hashing import hash_password, check_password_hash, is_bcrypt_hash
```

- Handles: `$2a$`, `$2b$`, `$2x$`, `$2y$` bcrypt variants (Laravel compat)
- Also handles Django's `bcrypt$` prefix format
- Falls back to Django's `check_password()` for legacy PBKDF2 hashes
- **NEVER use Django's `make_password()`** for new passwords — use `hash_password()`
- **NEVER use Django's `check_password()`** for agent/admin logins — use `check_password_hash()`

---

## 9. Payment Flow

### Razorpay Online Payment
```
1. Agent clicks "Pay" → /chooseplan/ → creates Razorpay order
2. Razorpay JS checkout → payment captured
3. /payment-success/ (GET, from Razorpay redirect) → verify payment → activate agent
4. /razorpay-webhook/ (POST) → verify HMAC → handle webhook events
5. post_payment.py → threading: generate PDF invoice + send welcome email (non-blocking)
```

### Offline Payment (Insurance portal)
```
/insurance/agents/<id>/checkout/ → record_payment() → status: pending_accounts_payment
→ mark subscription completed (+365 days)
→ payment fields stored: payment_method, payment_reference, payment_recorded_at, payment_recorded_by
```

### Local Dev Mock
- `RAZORPAY_ALLOW_LOCALHOST` unset → mock checkout activated
- Mock IDs have prefix `order_local_` / `pay_local_` → `is_real_razorpay_id()` rejects them
- Dashboard access requires REAL Razorpay IDs

### Post-payment fulfillment
```python
# In agents/services/post_payment.py
queue_invoice_and_welcome(agent_id, subscription_id)
# Runs in background thread via transaction.on_commit()
# Does: PDF invoice generation → Brevo welcome email → Google Sheet sync
# Uses threading (no Celery) — daemon=False so thread completes even if request ends
```

---

## 10. External Integrations

| Integration | Used For | Key Files |
|---|---|---|
| **Razorpay** | Payment gateway | `agents/services/razorpay_checkout.py`, `padosi_agent/razorpay_env.py` |
| **Brevo** | Transactional email (OTP, welcome, invoices) | `agents/services/brevo.py`, `admin_panel/services/brevo.py` |
| **Firebase FCM** | Push notifications | `agents/services/fcm.py`, `admin_panel/services/fcm.py` |
| **Google OAuth** | Agent sign-in with Google | `agents/views/auth.py` |
| **Google Business Profile (GBP)** | Agent GBP connect | `agents/views/gbp.py` |
| **Facebook Graph API v19** | Participant auto-post | `agents/views/participants.py` |
| **Cloudinary** | Agent photo uploads | `fastapi_app/services/cloudinary_service.py` |
| **Groq** | LLM for chatbot + bio generator | `chatbot/llm_client.py`, multiple Groq keys (key rotation) |
| **Gemini** | LLM fallback | `chatbot/llm_client.py` |
| **OpenRouter** | LLM fallback | `chatbot/llm_client.py` |
| **AMFI** | Mutual fund agent data scraper | `admin_panel/services/amfi_scraper.py` |
| **IRDAI** | Insurance agent data scraper (Playwright) | `admin_panel/services/irdai_scraper.py`, `playwright_manager.py` |
| **Google Sheets** | Invoice sync | `admin_panel/services/google_sheet_sync.py` |
| **Postalpincode.in** | Pincode → city/state lookup | `home/views/pages.py` → `_get_or_create_pincode()` |

---

## 11. Key URL Routing Rules

The root `padosi_agent/urls.py` includes in this order (LAST MATCH WINS for catch-alls):
```python
path('admin/championship/', include('apps.referral_championship.urls_admin')),
path('agent/championship/', include('apps.referral_championship.urls')),
path('', include('apps.admin_panel.urls')),    # /admin/*
path('', include('apps.agents.urls')),          # /agent-*, /profile/*, etc.
path('events/', include('apps.agents.urls_events')),
path('chatbot-api/', include('apps.chatbot.urls')),
path('', include('apps.distributors.urls')),    # /distributor/*
path('insurance/', include('apps.insurance.urls')),
path('', include('apps.home.urls')),            # catch-all CMS slugs at bottom
```

**Rule:** `apps.home.urls` is last. Home's CMS `<slug:slug>/` catches anything not matched above. Add new URL patterns ABOVE home's include.

**FastAPI routes:** All under `/api/*` via ASGI mount. Django never sees `/api/**`.

---

## 12. Middleware Stack (Order Matters)

```python
MIDDLEWARE = [
    'padosi_agent.middleware.StaleCookieSanitizerMiddleware',  # ← FIRST: sanitize cookies
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.middleware.gzip.GZipMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'padosi_agent.middleware.AutoCsrfCookieMiddleware',        # auto-set CSRF cookie on GETs
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'apps.agents.middleware.AgentPaymentGateMiddleware',       # redirect unpaid agents
    'apps.admin_panel.middleware.ThreatMonitorMiddleware',     # WAF, IP blocking
    'apps.admin_panel.middleware.IsolateAdminAgentSessionsMiddleware',  # session isolation
    'apps.admin_panel.middleware.AdminPermissionMiddleware',   # admin route gate
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'apps.admin_panel.middleware.ExceptionLoggerMiddleware',   # logs 500s to DB
    'padosi_agent.middleware.SEOMiddleware',                   # X-Robots-Tag
]
```

**CSRF cookie name:** `padosi_csrf_token` (not the default `csrftoken`)

---

## 13. Settings Conventions

- `DEBUG=False` in production — set by `.env`
- `USE_TZ=False` — hard requirement, never change
- Secrets from `.env` via `python-dotenv` — parent `.env` then `src/.env`
- `ADMIN_WHITELIST_IPS` — comma-separated IPs that can access `/admin/`
- `RAZORPAY_ALLOW_LOCALHOST` — unset = mock checkout in dev
- Custom CSRF cookie: `CSRF_COOKIE_NAME = "padosi_csrf_token"`
- Cache: file-based, `cache/` dir, 300s TTL, 2000 max entries
- Sessions: `cached_db` backend (cache-first, MySQL fallback)
- Static: `STATIC_ROOT = BASE_DIR / "staticfiles"` — run `collectstatic` before deploy

---

## 14. How to Add a New Feature (Correct Pattern)

### New Django view + URL

1. **Create view** in `apps/<app>/views/<feature>.py`
2. **Import in** `apps/<app>/views/__init__.py` (if using package pattern)
3. **Add URL** in `apps/<app>/urls.py` — use `name=` for all URLs
4. **Add template** in `templates/<app>/<feature>.html` (extends `base.html` or portal layout)
5. If it needs auth, use the correct decorator:
   - Agent views: `@login_required` + `@agent_required` (from agents decorators)
   - Admin views: `@admin_required` (from admin_panel.decorators)
   - Insurance views: `@insurance_required` (from insurance.decorators)

### New Django model + migration

1. Add model to `apps/<app>/models.py` (or `models/<name>.py` + export from `__init__`)
2. `python manage.py makemigrations <appname>`
3. Review generated migration — check for `managed=False` if it's a legacy table
4. `python manage.py migrate`
5. If FastAPI also needs this model, add SQLAlchemy model in `fastapi_app/models/<name>.py`

### New FastAPI route

1. Create or add to `fastapi_app/routers/<name>.py`
2. Import `APIRouter`, define endpoints with proper Pydantic schemas
3. Include router in `fastapi_app/main.py`
4. Use `get_current_agent` dependency from `fastapi_app/dependencies/auth.py` for protected routes
5. DB access via `get_db` session dependency (SQLAlchemy)

### New Email

Use `email_service` from `apps/agents/services/brevo.py` (primary Brevo API + SMTP fallback):
```python
from apps.agents.services.brevo import email_service
email_service.send_otp(to_email, to_name, otp)
email_service.send_welcome(to_email, to_name, temp_password, plan_name, attachment_path)
```

---

## 15. What NEVER to Do

| ❌ Never | ✅ Instead |
|---|---|
| Use `make_password()` for agents/admins | Use `hash_password()` from `password_hashing.py` |
| Use `check_password()` from Django auth for agent login | Use `check_password_hash()` from `password_hashing.py` |
| Use `timezone.now()` for datetime comparisons | Use `datetime.datetime.now()` (USE_TZ=False) |
| Add URL above admin_panel/agents include without checking conflicts | Check all URL files — home is catch-all at end |
| Set `managed=False` on a new model you control | Only for pre-existing Laravel/legacy tables |
| Run `migrate` without `makemigrations` first | Always `makemigrations` → review → `migrate` |
| Store secrets in code | Only in `.env` / environment variables |
| Use `admin.site.register()` for the main admin portal | The `/admin/` portal is custom, not Django admin |
| Use `request.user` to identify agents | Use `request.session.get('agent_id')` → `Agent.objects.get(id=...)` |
| Hardcode `padosiagent.com` in Python code | Use `settings.APP_URL` or `fastapi_app/config.py get_base_url()` |
| Put logs in `media/` dir | Use `logs/` dir (LOGS_DIR in settings) |
| Block in post-payment | Use `queue_invoice_and_welcome()` (background thread) |

---

## 16. Testing

```bash
python manage.py test apps.home      # Home app tests
python manage.py test apps.agents    # Agent tests (multiple test_*.py files)
python manage.py check              # Django system check (run before deploy)
python manage.py makemigrations --check --dry-run  # Verify no pending migrations
```

Test files:
- `apps/home/tests/` — agent_filters, calculators, pincode, portal_messages
- `apps/agents/test_*.py` — bio_generator, dashboard_json, feature_unlock, password_auth, payment_flow, post_payment, qr_review_growth, audit_security, registration_e2e (full signup → Razorpay → dashboard; run it after any registration/payment change)
- `fastapi_app/test_*.py` — championship, hybrid_fixes

Custom test runner: `apps.home.test_runner.ManagedModelsTestRunner` (handles unmanaged models in tests)

---

## 17. Deployment

### GitHub Actions → GoDaddy
1. Push to `main` → workflow triggers
2. `python manage.py check` runs in CI (uses dummy DB settings)
3. SSH into GoDaddy → `scripts/deploy_godaddy.sh`
4. Script: `git pull` → `pip install` → `collectstatic` → `migrate` → restart app

### Production checklist
- `DEBUG=False` in production `.env`
- `SECRET_KEY` must be set (no fallback in production)
- `ALLOWED_HOSTS` must include the domain
- `CSRF_TRUSTED_ORIGINS` must include `https://padosiagent.com`
- `python manage.py collectstatic --noinput`
- `python manage.py migrate`
- `python manage.py check --deploy`

---

## 18. Referral Championship App

Located: `apps/referral_championship/`

A gamified referral campaign where agents earn rewards by referring new paying agents.

**Models:**
- `ChampionshipCampaign` — configures campaign duration, pricing, unlock rules
- `ChampionshipParticipant` — agent participating (has `referral_id` like `PA-XXXXXX`)
- `ChampionshipReferral` — tracks registration state of a referred agent
- `ChampionshipRewardSlab` — reward tiers (5 refs = fee back, 10 = Pro plan, 25 = silver coin, etc.)
- `ChampionshipRewardClaim` — claim status per participant+slab
- `ChampionshipLeaderboardCache` — cached rank table

**URLs:** `/agent/championship/*` (agent views) + `/admin/championship/*` (admin views)

---

## 19. Chatbot

- **Entry:** `POST /chatbot-api/` → `apps/chatbot/views.py`
- **LLM:** `apps/chatbot/llm_client.py` — rotates through Groq keys → Gemini → OpenRouter
- **Session:** `ChatSession` (UUID) + `ChatMessage` rows
- **Groq key rotation:** `GROQ_API_KEY_1` through `GROQ_API_KEY_6` for rate limit management
- **Latency tracked:** `LatencyLog` model with token counts

---

## 20. FastAPI App Deep-Dive

**Mount point:** `/api` (via `asgi.py` Starlette router)

**Routers available at `/api/...`:**
- `/api/auth/*` — login, register, OTP, password reset, Google OAuth
- `/api/dashboard/*` — agent dashboard data
- `/api/profile/*` — agent profile CRUD
- `/api/public-profile/*` — public profile view
- `/api/pincode/*` — pincode lookup
- `/api/leads/*` — agent leads management
- `/api/notifications/*` — FCM push notifications
- `/api/analytics/*` — agent analytics
- `/api/qr/*` — QR code generation
- `/api/visibility/*` — profile/card visibility toggle
- `/api/referral/*` — referral codes
- `/api/find-agents/*` — agent search/directory
- `/api/championship/*` — referral championship
- `/api/plans/*` — subscription plans

**Auth in FastAPI:** JWT Bearer token. `get_current_agent()` dependency extracts agent from token.

**Database in FastAPI:** SQLAlchemy `AsyncSession` via `get_db` dependency. Same MySQL database as Django.

---

## 21. Feature Unlock System

File: `apps/agents/services/feature_unlock.py`

Plans: `free_trial` < `starter` < `professional` < `exclusive`

Features are gated by plan. `SiteSetting['feature_unlock_rules']` can ADD features dynamically based on agent metrics (reviews, profile %). Admin controls this from admin panel.

Key features: `edit_profile_basic`, `edit_profile_professional`, `manage_portfolio`, `upload_achievements`, `show_claims_stats`, `is_listed_in_directory`, `show_profile_section`, `is_card_visible`

---

## 22. Common Gotchas

1. **CSRF token name is `padosi_csrf_token`** not `csrftoken` — AJAX calls must use the right name
2. **Agent dashboard needs real Razorpay IDs** — mock `order_local_*` IDs do NOT grant access
3. **Post-payment runs in a background thread** — do NOT call `queue_invoice_and_welcome()` inside an already-background thread
4. **`USE_TZ=False` everywhere** — comparisons with naive datetimes work fine; mixing aware datetimes will break things
5. **The `admins` table is managed=False** — migrations will NOT touch it
6. **Admin portal ≠ Django admin** — `/admin/*` is the custom admin panel, `/django-admin/` is the Django built-in admin
7. **Home app is last in URL routing** — its CMS `<slug:slug>/` catch-all will match anything not handled above
8. **FastAPI is optional** — `asgi.py` catches FastAPI import errors and falls back to Django-only
9. **Groq key rotation** — chatbot has 6+ Groq API keys; add to `.env` as `GROQ_API_KEY_1` through `GROQ_API_KEY_6`
10. **GoBaddy Apache** proxies HTTPS; `SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')` is required

---

## 23. Environment Variables Reference

```bash
# Core
DEBUG=True
SECRET_KEY=
ALLOWED_HOSTS=localhost,127.0.0.1
CSRF_TRUSTED_ORIGINS=http://127.0.0.1:8000

# Database
DB_NAME=  DB_USER=  DB_PASSWORD=  DB_HOST=127.0.0.1  DB_PORT=3306

# Email (Brevo)
BREVO_API_KEY=  BREVO_FROM_EMAIL=  BREVO_FROM_NAME=  BREVO_OTP_FALLBACK=true

# Payments
RAZORPAY_KEY=  RAZORPAY_SECRET=  RAZORPAY_WEBHOOK_SECRET=
RAZORPAY_ALLOW_LOCALHOST=   # leave empty on localhost for mock checkout

# Firebase
FCM_PROJECT_ID=  FCM_SERVICE_ACCOUNT_JSON=  FCM_VAPID_KEY=

# Google
GOOGLE_CLIENT_ID=  GOOGLE_CLIENT_SECRET=  GOOGLE_REDIRECT_URI=  GBP_REDIRECT_URI=

# Facebook
FACEBOOK_APP_ID=  FACEBOOK_APP_SECRET=

# Auth
JWT_SECRET_KEY=

# Admin security
ADMIN_WHITELIST_IPS=
SECURITY_ALERT_EMAIL=
APP_URL=https://padosiagent.com

# Cloudinary
CLOUDINARY_CLOUD_NAME=  CLOUDINARY_API_KEY=  CLOUDINARY_API_SECRET=

# LLM (Groq key rotation)
GROQ_API_KEY=  GROQ_API_KEY_1=  GROQ_API_KEY_2=  ... GROQ_API_KEY_6=
GEMINI_API_KEY=
OPENROUTER_API_KEY=
```
