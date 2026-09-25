"""Load Razorpay key/secret as a matching pair from a single source.

Incomplete dotenv files must not overwrite only the key (or only the secret)
and mix test/live credentials from cPanel + .env.
"""
import os
from pathlib import Path

RAZORPAY_ENV_KEYS = (
    'RAZORPAY_KEY',
    'RAZORPAY_SECRET',
    'RAZORPAY_KEY_ID',
    'RAZORPAY_KEY_SECRET',
)

USER_PAYMENT_UNAVAILABLE = (
    "We're unable to process your payment right now. Please try again in a few minutes."
)


def clean_razorpay_credential(value):
    text = str(value or '').replace('\ufeff', '').strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ('"', "'"):
        text = text[1:-1].strip()
    return text


def credential_pair_from_mapping(mapping):
    """Return a key/secret pair only when both values exist in the same mapping."""
    if not mapping:
        return '', ''
    key = clean_razorpay_credential(
        mapping.get('RAZORPAY_KEY') or mapping.get('RAZORPAY_KEY_ID')
    )
    secret = clean_razorpay_credential(
        mapping.get('RAZORPAY_SECRET') or mapping.get('RAZORPAY_KEY_SECRET')
    )
    if key and secret:
        return key, secret
    return '', ''


def capture_razorpay_environ(environ=None):
    env = environ if environ is not None else os.environ
    return {key: env.get(key) for key in RAZORPAY_ENV_KEYS}


def restore_razorpay_environ(snapshot, environ=None):
    env = environ if environ is not None else os.environ
    for key, value in (snapshot or {}).items():
        if value is None or value == '':
            env.pop(key, None)
        else:
            env[key] = value


def complete_pair_from_env_files(base_dir):
    try:
        from dotenv import dotenv_values
    except ImportError:
        return '', ''
    base = Path(base_dir)
    pair = ('', '')
    for path in (base.parent / '.env', base / '.env'):
        try:
            if path.is_file():
                key, secret = credential_pair_from_mapping(dotenv_values(path) or {})
                if key and secret:
                    pair = (key, secret)
        except Exception:
            continue
    return pair


def webhook_secret_from_env_files(base_dir):
    try:
        from dotenv import dotenv_values
    except ImportError:
        return ''
    base = Path(base_dir)
    for path in (base.parent / '.env', base / '.env'):
        try:
            if path.is_file():
                val = (dotenv_values(path) or {}).get('RAZORPAY_WEBHOOK_SECRET')
                if val:
                    cleaned = clean_razorpay_credential(val)
                    if cleaned:
                        return cleaned
        except Exception:
            continue
    return ''


def apply_complete_razorpay_pair(pair, environ=None):
    env = environ if environ is not None else os.environ
    key, secret = pair
    if not key or not secret:
        return
    env['RAZORPAY_KEY'] = key
    env['RAZORPAY_SECRET'] = secret
    env['RAZORPAY_KEY_ID'] = key
    env['RAZORPAY_KEY_SECRET'] = secret


def resync_razorpay_environ_after_dotenv(base_dir, snapshot, environ=None):
    """
    After load_dotenv(override=True), restore process env then apply the
    first complete file pair (src/.env wins over parent .env).
    """
    restore_razorpay_environ(snapshot, environ)
    pair = complete_pair_from_env_files(base_dir)
    if pair[0] and pair[1]:
        apply_complete_razorpay_pair(pair, environ)
    return pair
