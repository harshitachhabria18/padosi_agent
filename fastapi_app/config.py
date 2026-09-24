import os
import re
import hashlib
import logging
from pathlib import Path
from typing import Optional, Any
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Load .env files matching Django settings and passenger_wsgi (parent directory first, then project directory)
_CONFIG_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _CONFIG_DIR.parent
for _env_path in (_PROJECT_ROOT.parent / ".env", _PROJECT_ROOT / ".env"):
    if _env_path.exists():
        load_dotenv(_env_path, override=False)

# Clean up any trailing newlines or spaces from database environment variables (very common in Docker/Railway)
for key in ["DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD", "MYSQLHOST", "MYSQLPORT", "MYSQLDATABASE", "MYSQLUSER", "MYSQLPASSWORD"]:
    if key in os.environ and os.environ[key]:
        os.environ[key] = os.environ[key].strip()

# Auto-detect Railway MySQL variables and map them
if "MYSQLHOST" in os.environ:
    os.environ["DB_HOST"] = os.getenv("MYSQLHOST", "").strip()
if "MYSQLPORT" in os.environ:
    os.environ["DB_PORT"] = os.getenv("MYSQLPORT", "").strip()
if "MYSQLDATABASE" in os.environ:
    os.environ["DB_NAME"] = os.getenv("MYSQLDATABASE", "").strip()
if "MYSQLUSER" in os.environ:
    os.environ["DB_USER"] = os.getenv("MYSQLUSER", "").strip()
if "MYSQLPASSWORD" in os.environ:
    os.environ["DB_PASSWORD"] = os.getenv("MYSQLPASSWORD", "").strip()

class Settings(BaseSettings):
    APP_KEY: Optional[str] = None
    DB_HOST: str = "localhost"
    DB_PORT: int = 3306
    DB_NAME: str = "padosiagent"
    DB_USER: str = "root"
    DB_PASSWORD: str = ""

    @model_validator(mode="before")
    @classmethod
    def strip_string_fields(cls, values):
        if isinstance(values, dict):
            for k, v in values.items():
                if isinstance(v, str):
                    values[k] = v.strip()
            for field in ["ALLOWED_CORS_ORIGINS", "ADMIN_WHITELIST_IPS"]:
                val = values.get(field)
                if isinstance(val, str) and val:
                    values[field] = [x.strip() for x in val.split(",") if x.strip()]
        return values

    # Auth & Security
    SECRET_KEY: str = "v2f6yt8&oq&%^=mh^1=w5y8v0-q3ks^s__$!2+&@5kcyn)wsd5"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 120
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Profile JWT Auth
    JWT_SECRET_KEY: str = "v2f6yt8&oq&%^=mh^1=w5y8v0-q3ks^s__$!2+&@5kcyn)wsd5"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 120
    APP_URL: str = "http://localhost:8000"
    DEBUG: bool = False

    @model_validator(mode="after")
    def validate_production_app_url(self):
        is_debug = bool(self.DEBUG) or os.environ.get("DEBUG", "False").lower() in ("true", "1", "yes")
        is_localhost = any(h in (self.APP_URL or "").lower() for h in ("localhost", "127.0.0.1", "0.0.0.0"))
        if not is_debug and is_localhost:
            self.APP_URL = "https://padosiagent.com"
        return self

    # Razorpay Payments
    RAZORPAY_KEY: str = ""
    RAZORPAY_SECRET: str = ""
    RAZORPAY_WEBHOOK_SECRET: str = ""

    # Firebase FCM
    FCM_PROJECT_ID: Optional[str] = "padosiagent-e74c8"
    FCM_SERVICE_ACCOUNT_JSON: Optional[str] = "storage/app/firebase-service-account.json"

    # Brevo Mail & SMTP configuration
    BREVO_API_KEY: str = ""
    BREVO_FROM_EMAIL: str = "noreply@padosiagent.com"
    BREVO_FROM_NAME: str = "PadosiAgent"
    BREVO_OTP_FALLBACK: bool = True

    MAIL_HOST: str = "smtp-relay.brevo.com"
    MAIL_PORT: int = 587
    MAIL_USERNAME: str = ""
    MAIL_PASSWORD: str = ""
    MAIL_ENCRYPTION: str = "tls"
    MAIL_FROM_ADDRESS: str = "noreply@padosiagent.com"
    MAIL_FROM_NAME: str = "PadosiAgent"

    # Cloudinary
    CLOUDINARY_CLOUD_NAME: str = ""
    CLOUDINARY_API_KEY: str = ""
    CLOUDINARY_API_SECRET: str = ""

    # Local Storage Fallback Path
    LOCAL_STORAGE_PATH: str = "media"

    # Security Config
    SECURITY_ALERT_EMAIL: str = "ashisprajapati2131@gmail.com"
    WAF_AUTO_BAN_ENABLED: bool = False  # Temporarily disabled for testing (do not lock agent after 3 attempts)
    ALLOWED_CORS_ORIGINS: list[str] = ["http://localhost:3000"]
    ADMIN_WHITELIST_IPS: list[str] = []

    model_config = SettingsConfigDict(
        env_file=[
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"),
            os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env"),
        ],
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()

# Default committed key from legacy configuration
_COMMITTED_DEFAULT_SECRET = "v2f6yt8&oq&%^=mh^1=w5y8v0-q3ks^s__$!2+&@5kcyn)wsd5"


def _ensure_valid_secret(cfg: Settings) -> None:
    """Ensure SECRET_KEY and JWT_SECRET_KEY are set safely without crashing the app in production."""
    key = (cfg.SECRET_KEY or "").strip()
    
    # 1. If key is already non-default and non-empty, keep it
    if key and key != _COMMITTED_DEFAULT_SECRET:
        return

    # 2. Check environment or Django settings for an explicit SECRET_KEY or DJANGO_SECRET_KEY
    env_django_secret = (os.environ.get("DJANGO_SECRET_KEY") or os.environ.get("SECRET_KEY") or "").strip()
    if env_django_secret and env_django_secret != _COMMITTED_DEFAULT_SECRET:
        cfg.SECRET_KEY = env_django_secret
        if cfg.JWT_SECRET_KEY == _COMMITTED_DEFAULT_SECRET:
            cfg.JWT_SECRET_KEY = env_django_secret
        return

    # 3. Check if JWT_SECRET_KEY is explicitly set to a custom value
    env_jwt_secret = (getattr(cfg, "JWT_SECRET_KEY", None) or os.environ.get("JWT_SECRET_KEY") or "").strip()
    if env_jwt_secret and env_jwt_secret != _COMMITTED_DEFAULT_SECRET:
        cfg.SECRET_KEY = env_jwt_secret
        return

    # 4. In debug mode, committed default is acceptable for local testing
    debug = bool(cfg.DEBUG) or os.environ.get("DEBUG", "False").strip().lower() in ("true", "1", "yes")
    if debug:
        return

    # 5. Production fallback: generate deterministic deployment secret instead of crashing
    fallback_seed = f"padosi-fallback-{cfg.DB_NAME}-{cfg.DB_USER}-{cfg.DB_HOST}"
    derived_secret = hashlib.sha256(fallback_seed.encode("utf-8")).hexdigest()
    cfg.SECRET_KEY = derived_secret
    if cfg.JWT_SECRET_KEY == _COMMITTED_DEFAULT_SECRET:
        cfg.JWT_SECRET_KEY = derived_secret
    logger.warning(
        "FastAPI SECRET_KEY was missing or committed default; generated deterministic fallback key. "
        "Set a strong SECRET_KEY in your .env file."
    )
    os.environ.setdefault("SECRET_KEY", derived_secret)


_ensure_valid_secret(settings)
if settings.SECRET_KEY:
    os.environ.setdefault("SECRET_KEY", settings.SECRET_KEY)


def is_debug_mode() -> bool:
    """Detect whether running in debug/development mode across FastAPI and Django."""
    env_debug = os.environ.get("DEBUG", "").strip().lower()
    if env_debug in ("true", "1", "yes"):
        return True
    if env_debug in ("false", "0", "no"):
        return False
    if bool(getattr(settings, "DEBUG", False)):
        return True
    try:
        from django.conf import settings as django_settings
        return bool(getattr(django_settings, "DEBUG", False))
    except Exception:
        pass
    return False


def get_base_url(request: Optional[Any] = None, path: Optional[str] = None) -> str:
    """
    Get the absolute base URL for building links and asset paths.
    Prioritizes incoming request headers (x-forwarded-proto, host) so that
    production reverse proxies (Passenger WSGI, Nginx, ALB) correctly reflect the public domain.
    In production (DEBUG=False), ensures URLs never leak localhost/127.0.0.1 or insecure http.
    Falls back to settings.APP_URL or https://padosiagent.com.

    If 'path' is provided, cleanly joins it to the base URL without double slashes.
    """
    if isinstance(request, str) and path is None:
        path = request
        request = None

    is_debug = is_debug_mode()
    base = ""

    if request is not None:
        headers = getattr(request, "headers", None)
        proto = None
        host = None

        if headers and hasattr(headers, "get"):
            proto = headers.get("x-forwarded-proto")
            if not proto:
                if headers.get("x-forwarded-ssl") == "on" or headers.get("front-end-https") == "on":
                    proto = "https"
            host = headers.get("x-forwarded-host") or headers.get("host")

        if not proto:
            if hasattr(request, "is_secure") and callable(request.is_secure):
                proto = "https" if request.is_secure() else "http"
            else:
                proto = getattr(getattr(request, "url", None), "scheme", "") or "https"

        if not host:
            if hasattr(request, "get_host") and callable(request.get_host):
                try:
                    host = request.get_host()
                except Exception:
                    pass
            if not host and hasattr(request, "url"):
                host = getattr(request.url, "netloc", "")

        if proto and "," in proto:
            proto = proto.split(",")[0].strip()
        if host and "," in host:
            host = host.split(",")[0].strip()

        if host:
            is_localhost = any(lh in host.lower() for lh in ("localhost", "127.0.0.1", "0.0.0.0", "testserver", "::1"))
            if not is_localhost:
                final_proto = "https" if not is_debug else (proto or "http")
                base = f"{final_proto}://{host}".rstrip('/')
            else:
                if is_debug:
                    chosen_proto = proto or "http"
                    base = f"{chosen_proto}://{host}".rstrip('/')
                else:
                    app_url = (settings.APP_URL or "").rstrip('/')
                    is_app_localhost = any(lh in app_url.lower() for lh in ("localhost", "127.0.0.1", "0.0.0.0"))
                    if app_url and not is_app_localhost:
                        base = app_url
                    else:
                        base = "https://padosiagent.com"

    if not base:
        if is_debug:
            base = (settings.APP_URL or "").rstrip('/') or "http://localhost:8000"
        else:
            app_url = (settings.APP_URL or "").rstrip('/')
            is_localhost = any(lh in app_url.lower() for lh in ("localhost", "127.0.0.1", "0.0.0.0"))
            if is_localhost:
                base = "https://padosiagent.com"
            else:
                base = app_url or "https://padosiagent.com"

    if not is_debug and any(lh in base.lower() for lh in ("localhost", "127.0.0.1", "0.0.0.0")):
        base = "https://padosiagent.com"

    base = base.rstrip('/')

    if path:
        if path.startswith("http://") or path.startswith("https://"):
            if not is_debug and any(h in path.lower() for h in ("localhost", "127.0.0.1", "0.0.0.0")):
                return re.sub(r"^https?://(localhost|127\.0\.0\.1|0\.0\.0\.0)(:\d+)?", "https://padosiagent.com", path)
            return path
        clean_path = path if path.startswith("/") else f"/{path}"
        return f"{base}{clean_path}"

    return base


def build_safe_url(path_or_url: str, request: Optional[Any] = None) -> str:
    """
    Build an absolute safe URL from a path or existing URL, ensuring that
    in production no localhost/127.0.0.1 origins leak to clients.
    """
    return get_base_url(request=request, path=path_or_url)



