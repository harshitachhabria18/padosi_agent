"""
Shared agent password lookup.

Admin login is the source of truth: bcrypt via password_hashing against the
PHP/Laravel tables. Agent passwords live in `users` as `$2y$`/`$2b$` hashes.
Django authenticate() cannot verify those hashes, so agent login uses the
same check_password_hash() helper as admin login.
"""
import logging
import re
from types import SimpleNamespace

from django.contrib.auth.models import User as DjangoUser
from django.db import connection

from password_hashing import check_password_hash, hash_password, is_bcrypt_hash

logger = logging.getLogger(__name__)

INCOMPLETE_STATUSES = ('incomplete', 'pending_payment', 'pending_accounts_payment')
BLOCKED_DASHBOARD_STATUSES = ('suspended', 'blacklisted', 'rejected', 'deleted')
DJANGO_AUTH_BACKEND = 'django.contrib.auth.backends.ModelBackend'


def is_real_razorpay_id(value, prefix):
    """Reject local mock IDs (order_local_ / pay_local_)."""
    raw = str(value or '').strip()
    if not raw.startswith(prefix):
        return False
    if raw.startswith(f'{prefix}local_'):
        return False
    return True


def agent_has_completed_payment(agent):
    """True only after a real Razorpay-captured payment (not mock / pending / failed)."""
    if not agent:
        return False
    from apps.agents.models import AgentSubscription, Invoice

    completed = AgentSubscription.objects.filter(
        agent=agent,
        payment_status='completed',
    )
    for sub in completed:
        if is_real_razorpay_id(sub.razorpay_payment_id, 'pay_'):
            return True
        if is_real_razorpay_id(sub.razorpay_order_id, 'order_'):
            return True

    invoices = Invoice.objects.filter(agent=agent, payment_status='paid')
    for invoice in invoices:
        if is_real_razorpay_id(invoice.razorpay_payment_id, 'pay_'):
            return True
        if is_real_razorpay_id(invoice.razorpay_order_id, 'order_'):
            return True
    return False


def agent_can_access_dashboard(agent):
    """
    Dashboard access requires a verified captured payment.
    Pending, failed, or mock checkout records never grant access.
    """
    if not agent:
        return False
    if agent.status in BLOCKED_DASHBOARD_STATUSES:
        return False
    if agent_has_completed_payment(agent):
        return True
    if agent.status in INCOMPLETE_STATUSES:
        return False
    return False


def agent_needs_payment(agent):
    """True when the agent must complete payment before dashboard access."""
    if not agent:
        return False
    if agent.status in BLOCKED_DASHBOARD_STATUSES:
        return False
    return not agent_has_completed_payment(agent)


def _split_name(fullname):
    parts = (fullname or '').strip().split(' ', 1)
    first = parts[0] if parts and parts[0] else ''
    last = parts[1] if len(parts) > 1 else ''
    return first, last


def find_django_user(email):
    if not email:
        return None
    return DjangoUser.objects.filter(email__iexact=email).first()


def fetch_users_row(email=None, user_id=None):
    """
    Read PHP `users` the same way admin reads `admins`: raw SQL + bcrypt hash.
    Email match is preferred so a Django auth_user id in agents.user_id cannot
    pick the wrong users row.
    """
    if not email and not user_id:
        return None
    try:
        with connection.cursor() as cursor:
            if email:
                cursor.execute(
                    """
                    SELECT id, fullname, email, password, role, status
                    FROM users
                    WHERE LOWER(email) = LOWER(%s)
                    LIMIT 1
                    """,
                    [email],
                )
            else:
                cursor.execute(
                    """
                    SELECT id, fullname, email, password, role, status
                    FROM users
                    WHERE id = %s
                    LIMIT 1
                    """,
                    [user_id],
                )
            row = cursor.fetchone()
    except Exception as exc:
        logger.warning("users table lookup failed: %s", exc)
        return None
    if not row:
        return None
    return SimpleNamespace(
        id=row[0],
        fullname=row[1] or '',
        email=row[2] or '',
        password=row[3] or '',
        role=(row[4] or ''),
        status=(row[5] or ''),
    )


def find_laravel_user(email):
    if not email:
        return None
    row = fetch_users_row(email=email)
    if row:
        return row
    try:
        from apps.admin_panel.models.users import User as LaravelUser
        return LaravelUser.objects.filter(email__iexact=email).first()
    except Exception as exc:
        logger.warning("Laravel users lookup failed for agent login: %s", exc)
        return None


def find_agent(email):
    if not email:
        return None
    from django.db.models import Case, IntegerField, When
    from apps.agents.models import Agent

    qs = Agent.objects.filter(email__iexact=email)
    if not qs.exists():
        return None
    status_rank = Case(
        When(status='active', then=0),
        When(status='pending_approval', then=1),
        When(status='pending_payment', then=2),
        When(status='pending_accounts_payment', then=3),
        When(status='inactive', then=4),
        default=5,
        output_field=IntegerField(),
    )
    return qs.annotate(_status_rank=status_rank).order_by('_status_rank', '-id').first()


def resolve_agent_for_user(user):
    """Match a Django session user to an imported PHP agent.

    PHP stored Laravel ``users.id`` on ``agents.user_id``. After import that
    id is not ``auth_user.id``, so filter(user=user) misses and ``agent.user``
    raises DoesNotExist. Prefer the linked row, then email, then relink.
    """
    if not user or not getattr(user, 'is_authenticated', False):
        return None
    from apps.agents.models import Agent

    agent = Agent.objects.filter(user=user).first()
    if not agent and user.email:
        agent = find_agent(user.email)
    if agent and agent.user_id != user.id:
        agent.user = user
        agent.save(update_fields=['user'])
    return agent


def _usable_hash(stored):
    value = (stored or '').strip()
    if not value or value.startswith('!'):
        return None
    return value


def _unique_username(email):
    username = (email or '').strip() or 'agent'
    if not DjangoUser.objects.filter(username=username).exists():
        return username
    base = email.split('@')[0][:20] or 'agent'
    candidate = base
    counter = 1
    while DjangoUser.objects.filter(username=candidate).exists():
        candidate = f"{base}{counter}"
        counter += 1
    return candidate


def ensure_django_user(email, fullname, password_hash, overwrite_password=False):
    """Create or update auth_user with a raw bcrypt hash (not set_password)."""
    user = find_django_user(email)
    first_name, last_name = _split_name(fullname)
    if not user:
        user = DjangoUser(
            username=_unique_username(email),
            email=email,
            first_name=first_name,
            last_name=last_name,
            is_active=True,
        )
        user.password = password_hash
        user.save()
        return user

    updates = []
    if first_name and user.first_name != first_name:
        user.first_name = first_name
        updates.append('first_name')
    if last_name and user.last_name != last_name:
        user.last_name = last_name
        updates.append('last_name')
    if password_hash and (
        overwrite_password
        or not _usable_hash(user.password)
        or (is_bcrypt_hash(password_hash) and not is_bcrypt_hash(user.password))
    ):
        user.password = password_hash
        updates.append('password')
    if updates:
        user.save(update_fields=updates)
    return user


def ensure_laravel_user(email, fullname, password_hash, role='agent', status='active', overwrite_password=False):
    """Create or update the Laravel `users` row used by FastAPI and admin bcrypt checks."""
    try:
        from django.utils import timezone
        from apps.admin_panel.models.users import User as LaravelUser
    except Exception as exc:
        logger.warning("Cannot import Laravel User model: %s", exc)
        return None

    user = LaravelUser.objects.filter(email__iexact=email).first()
    now = timezone.now()
    if not user:
        if not password_hash:
            return None
        user = LaravelUser(
            fullname=fullname or email,
            email=email,
            password=password_hash,
            role=(role or 'agent')[:11],
            status=(status or 'active')[:9],
            email_verified_at=now,
            created_at=now,
            updated_at=now,
        )
        user.save()
        return user

    updates = []
    if fullname and user.fullname != fullname:
        user.fullname = fullname
        updates.append('fullname')
    if password_hash and (
        overwrite_password
        or not _usable_hash(user.password)
        or (is_bcrypt_hash(password_hash) and not is_bcrypt_hash(user.password))
    ):
        user.password = password_hash
        updates.append('password')
    if role and user.role != role:
        user.role = role[:11]
        updates.append('role')
    if updates:
        user.updated_at = now
        updates.append('updated_at')
        user.save(update_fields=updates)
    return user


def sync_agent_email_change(previous_email, new_email, fullname=None):
    """Carry an agents.email change over to the credential tables.

    Login resolves the account by email against `users` first and `auth_user`
    second. Renaming only `agents.email` leaves both lookups on the old address
    and the agent can no longer sign in with either one.
    """
    previous = (previous_email or '').strip()
    new = (new_email or '').strip()
    if not new or previous.lower() == new.lower():
        return

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE users SET email = %s, fullname = COALESCE(NULLIF(%s, ''), fullname) "
                "WHERE LOWER(email) = LOWER(%s)",
                [new, fullname or '', previous],
            )
    except Exception as exc:
        logger.warning("Could not move users.email from %s to %s: %s", previous, new, exc)

    django_user = find_django_user(previous)
    if not django_user:
        return
    updates = ['email']
    django_user.email = new
    if django_user.username == previous and not DjangoUser.objects.filter(username=new).exists():
        django_user.username = new
        updates.append('username')
    first_name, last_name = _split_name(fullname)
    if first_name and django_user.first_name != first_name:
        django_user.first_name = first_name
        updates.append('first_name')
    if last_name and django_user.last_name != last_name:
        django_user.last_name = last_name
        updates.append('last_name')
    django_user.save(update_fields=updates)


def restore_soft_deleted_agent(agent):
    """Clear agents.deleted_at when the column exists (Laravel soft deletes)."""
    if not agent or not getattr(agent, 'id', None):
        return
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE agents SET deleted_at = NULL WHERE id = %s AND deleted_at IS NOT NULL",
                [agent.id],
            )
    except Exception:
        pass


def link_agent_to_django_user(agent, django_user):
    """Point agents.user_id at Django auth_user.id.

    PHP stored Laravel ``users.id`` on this FK. That value is not
    ``auth_user.id``, so login must overwrite it or the dashboard cannot
    resolve the session user.
    """
    if not agent or not django_user:
        return agent
    if agent.user_id != django_user.id:
        agent.user = django_user
        agent.save(update_fields=['user'])
    restore_soft_deleted_agent(agent)
    return agent


def normalize_agent_mobile(mobile):
    """Return a 10-digit Indian mobile or empty string."""
    raw = re.sub(r'[^0-9]', '', str(mobile or ''))
    if len(raw) == 12 and raw.startswith('91'):
        raw = raw[2:]
    if len(raw) == 11 and raw.startswith('0'):
        raw = raw[1:]
    if len(raw) > 10:
        raw = raw[-10:]
    if len(raw) == 10 and raw[0] in '6789':
        return raw
    return ''


def default_agent_temp_password(agent):
    """
    Default password when a new website agent gets auth rows (no hash yet).
    Uses 10-digit mobile from registration; email only if mobile is missing.
    Existing stored hashes are never overwritten by this helper.
    """
    if not agent:
        return ''
    mobile = normalize_agent_mobile(getattr(agent, 'mobile', None))
    if mobile:
        return mobile
    return (getattr(agent, 'email', None) or '').strip()


def _hash_for_verified_password(password, laravel_user, django_user):
    for stored in (
        getattr(laravel_user, 'password', None),
        getattr(django_user, 'password', None),
    ):
        usable = _usable_hash(stored)
        if usable and is_bcrypt_hash(usable) and check_password_hash(password, usable):
            return usable
    return hash_password(password)


def verify_agent_password(email, password, agent=None):
    """
    Verify an agent password the same way admin login does:

    1. Load hash from PHP `users` (raw SQL)
    2. check_password_hash() → bcrypt.checkpw for $2y$/$2b$
    3. Fall back to leftover Django auth_user hashes
    """
    if not agent:
        agent = find_agent(email)

    laravel_user = fetch_users_row(email=email)
    if (
        laravel_user is None
        and agent
        and getattr(agent, 'user_id', None)
    ):
        by_id = fetch_users_row(user_id=agent.user_id)
        if by_id and (by_id.email or '').lower() == (agent.email or email or '').lower():
            laravel_user = by_id

    django_user = find_django_user(email)

    laravel_hash = _usable_hash(getattr(laravel_user, 'password', None) if laravel_user else None)
    django_hash = _usable_hash(getattr(django_user, 'password', None) if django_user else None)

    if laravel_hash and check_password_hash(password, laravel_hash):
        return True, laravel_user, django_user
    if django_hash and check_password_hash(password, django_hash):
        return True, laravel_user, django_user

    return False, laravel_user, django_user


def sync_verified_password(email, fullname, password, role='agent', agent=None):
    """
    After a successful password check, store one bcrypt hash on both tables
    and link the agent to the Django user used for sessions.
    """
    laravel_user = find_laravel_user(email)
    django_user = find_django_user(email)
    bcrypt_hash = _hash_for_verified_password(password, laravel_user, django_user)
    django_user = ensure_django_user(email, fullname, bcrypt_hash, overwrite_password=True)
    ensure_laravel_user(email, fullname, bcrypt_hash, role=role, overwrite_password=True)
    if agent is None:
        agent = find_agent(email)
    if agent:
        link_agent_to_django_user(agent, django_user)
    return django_user


def create_or_link_django_user(agent, plain_password=None):
    """
    Ensure auth_user + users rows exist for an agent.

    Does not overwrite an existing bcrypt hash unless plain_password is given.
    If no hash exists, stores bcrypt(default_agent_temp_password(agent)).
    """
    if not agent or not agent.email:
        raise ValueError('Agent email is required')

    email = agent.email
    fullname = agent.fullname or email
    laravel_user = find_laravel_user(email)
    django_user = find_django_user(email)

    if plain_password:
        bcrypt_hash = hash_password(plain_password)
        overwrite = True
    else:
        overwrite = False
        stored = _usable_hash(getattr(laravel_user, 'password', None) if laravel_user else None)
        if not stored:
            stored = _usable_hash(getattr(django_user, 'password', None) if django_user else None)
        if stored and is_bcrypt_hash(stored):
            bcrypt_hash = stored
        else:
            bcrypt_hash = hash_password(default_agent_temp_password(agent))
            overwrite = not stored

    django_user = ensure_django_user(email, fullname, bcrypt_hash, overwrite_password=overwrite)
    ensure_laravel_user(email, fullname, bcrypt_hash, role='agent', overwrite_password=overwrite)
    link_agent_to_django_user(agent, django_user)
    return django_user
