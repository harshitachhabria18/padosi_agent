"""Razorpay order helpers with a DEBUG-only local checkout fallback."""
import logging
import os
import re
import time
import uuid
from pathlib import Path

from django.conf import settings
from padosi_agent.razorpay_env import (
    USER_PAYMENT_UNAVAILABLE,
    clean_razorpay_credential,
    credential_pair_from_mapping,
)

logger = logging.getLogger(__name__)

MOCK_ORDER_PREFIX = 'order_local_'
MOCK_PAYMENT_PREFIX = 'pay_local_'
MOCK_SIGNATURE = 'test_signature_skip'
LOCAL_HOSTS = {'127.0.0.1', 'localhost', '::1', '0.0.0.0'}


def _dotenv_file_maps():
    maps = []
    try:
        from dotenv import dotenv_values
        base = Path(getattr(settings, 'BASE_DIR', '.') or '.')
    except Exception:
        return maps
    for path in (base / '.env', base.parent / '.env'):
        try:
            if path.is_file():
                maps.append(dotenv_values(path) or {})
        except Exception:
            logger.warning('Could not read Razorpay env file %s', path)
    return maps


def razorpay_credentials(file_maps=None, environ=None):
    """
    Never mix a key from one source with a secret from another.
    cPanel live keys plus .env test secrets cause Authentication failed in production.
    """
    sources = list(file_maps if file_maps is not None else _dotenv_file_maps())
    env = environ if environ is not None else os.environ
    sources.append(env)
    sources.append({
        'RAZORPAY_KEY': getattr(settings, 'RAZORPAY_KEY', ''),
        'RAZORPAY_SECRET': getattr(settings, 'RAZORPAY_SECRET', ''),
        'RAZORPAY_KEY_ID': getattr(settings, 'RAZORPAY_KEY_ID', ''),
        'RAZORPAY_KEY_SECRET': getattr(settings, 'RAZORPAY_KEY_SECRET', ''),
    })
    for mapping in sources:
        key, secret = credential_pair_from_mapping(mapping)
        if key and secret:
            return key, secret
    return '', ''


def razorpay_webhook_secret():
    """Return configured Razorpay webhook secret from settings or dotenv files."""
    secret = clean_razorpay_credential(getattr(settings, 'RAZORPAY_WEBHOOK_SECRET', ''))
    if secret:
        return secret
    for mapping in list(_dotenv_file_maps()) + [os.environ]:
        raw = mapping.get('RAZORPAY_WEBHOOK_SECRET')
        if raw:
            cleaned = clean_razorpay_credential(raw)
            if cleaned:
                return cleaned
    return ''


def razorpay_client():
    key, secret = razorpay_credentials()
    if not key or not secret:
        return None
    try:
        import razorpay
    except ImportError:
        logger.error('razorpay package is not installed')
        return None
    return razorpay.Client(auth=(key, secret))


def gateway_failure_message():
    logger.error('Payment checkout is unavailable (mode=%s)', razorpay_key_mode())
    return USER_PAYMENT_UNAVAILABLE


def razorpay_key_mode():
    key, secret = razorpay_credentials()
    if not key or not secret:
        return 'missing'
    if key.startswith('rzp_test_'):
        return 'test'
    if key.startswith('rzp_live_'):
        return 'live'
    return 'unknown'


def is_local_request(request):
    host = (request.get_host() or '').split(':')[0].lower()
    return host in LOCAL_HOSTS


def is_unsafe_localhost_checkout(request):
    """
    Real Razorpay iframe (HTTPS) cannot reach localhost HTTP assets/callbacks.
    Browsers block this via Private Network Access — breaks EMI, netbanking, etc.
    """
    if not getattr(settings, 'DEBUG', False):
        return False
    return is_local_request(request) and not request.is_secure()


def localhost_checkout_allowed():
    """Opt-in: set RAZORPAY_ALLOW_LOCALHOST=1 to try real Razorpay on localhost HTTP."""
    return os.environ.get('RAZORPAY_ALLOW_LOCALHOST', '').strip().lower() in ('1', 'true', 'yes')


def checkout_uses_redirect_callback(request):
    """
    Netbanking/UPI require callback_url with redirect=true.
    HTTPS always; localhost HTTP only with Razorpay test keys (or opt-in).
    """
    if request is None:
        return False
    if request.is_secure():
        return True
    if not is_local_request(request):
        return False
    if razorpay_key_mode() == 'test':
        return True
    return localhost_checkout_allowed()


def should_mock_razorpay(request):
    """
    Mock is never used to complete a paid registration.
    Missing keys in DEBUG still return True so callers can show a gateway error.
    """
    if not getattr(settings, 'DEBUG', False):
        return False
    return razorpay_key_mode() == 'missing'


def sanitize_contact(raw):
    digits = re.sub(r'\D', '', str(raw or ''))
    if digits.startswith('91') and len(digits) == 12:
        digits = digits[2:]
    elif digits.startswith('0') and len(digits) == 11:
        digits = digits[1:]
    if len(digits) == 10:
        return digits
    return ''


def mock_order_id():
    return f'{MOCK_ORDER_PREFIX}{int(time.time())}_{uuid.uuid4().hex[:10]}'


def mock_payment_id():
    return f'{MOCK_PAYMENT_PREFIX}{int(time.time())}_{uuid.uuid4().hex[:8]}'


def create_checkout_order(amount_paise, receipt, request, notes=None):
    """Return (order_id, is_mock). order_id is None if a paid order could not be created."""
    amount_paise = int(amount_paise or 0)
    if amount_paise <= 0:
        return None, False
    if razorpay_key_mode() == 'live' and is_local_request(request) and not request.is_secure():
        logger.error('Refusing live Razorpay checkout on insecure localhost')
        return None, False
    if should_mock_razorpay(request):
        logger.error(
            'Razorpay keys missing; refusing mock auto-complete (host=%s)',
            request.get_host(),
        )
        return None, False
    try:
        client = razorpay_client()
        if client is None:
            logger.error('Razorpay keys are missing; cannot create order')
            return None, False
        order_payload = {
            'amount': amount_paise,
            'currency': 'INR',
            'receipt': str(receipt or '')[:40],
            'payment_capture': 1,
        }
        if notes and isinstance(notes, dict):
            order_payload['notes'] = {str(k)[:40]: str(v)[:256] for k, v in notes.items() if v is not None}
        order = client.order.create(order_payload)
        return order.get('id'), False
    except Exception as err:
        key, _secret = razorpay_credentials()
        key_prefix = f'{key[:12]}...' if key else 'empty'
        logger.error(
            'Razorpay order creation failed: %s (mode=%s, key=%s)',
            err,
            razorpay_key_mode(),
            key_prefix,
        )
        return None, False


def is_mock_payment(order_id=None, signature=None):
    if not getattr(settings, 'DEBUG', False):
        return False
    order_id = str(order_id or '')
    signature = str(signature or '')
    if order_id.startswith(MOCK_ORDER_PREFIX):
        return True
    return signature in (MOCK_SIGNATURE, 'test_signature_skip_verification')


def checkout_key(is_mock=False):
    if is_mock:
        return 'rzp_test_local_mock'
    key, _secret = razorpay_credentials()
    return key


def checkout_payload(order_id, amount_paise, agent, is_mock=False, extra=None, request=None):
    phone = sanitize_contact(getattr(agent, 'mobile', '') if agent else '')
    payload = {
        'success': True,
        'payment_required': bool(amount_paise and amount_paise > 0),
        'razorpay_order_id': order_id,
        'razorpay_key_id': checkout_key(is_mock),
        'amount_paise': amount_paise,
        'order_id': order_id,
        'amount': amount_paise,
        'key': checkout_key(is_mock),
        'agent_id': getattr(agent, 'id', None),
        'customer_name': getattr(agent, 'fullname', '') or '',
        'customer_email': getattr(agent, 'email', '') or '',
        'customer_phone': phone,
        'name': getattr(agent, 'fullname', '') or '',
        'email': getattr(agent, 'email', '') or '',
        'mobile': phone,
        'mock_checkout': bool(is_mock),
    }
    if is_mock:
        payload['mock_signature'] = MOCK_SIGNATURE
        payload['mock_payment_id'] = mock_payment_id()
        if request is not None and is_unsafe_localhost_checkout(request):
            payload['mock_checkout_reason'] = 'localhost_http'
    if request is not None:
        payload['checkout_use_callback'] = checkout_uses_redirect_callback(request)
        payload['unsafe_localhost_checkout'] = (
            not is_mock and is_unsafe_localhost_checkout(request)
        )
    if extra:
        payload.update(extra)
    return payload


def login_agent_user(request, user):
    if not user:
        return
    from django.contrib.auth import login
    from apps.agents.services.account_auth import DJANGO_AUTH_BACKEND
    from apps.distributors.views.dashboard import is_distributor

    if request.user.is_authenticated and is_distributor(request.user):
        return
    login(request, user, backend=DJANGO_AUTH_BACKEND)
