import importlib.util
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

# Python 3.11 virtualenvs used by cPanel Passenger. Keep both app-name spellings:
# production tracebacks load packages from virtualenv/padosiagentdjango (no underscore).
_VENVS = [
    "/home/m69qf6gyhm3n/virtualenv/padosiagent_django/src/3.11/lib/python3.11/site-packages",
    "/home/m69qf6gyhm3n/virtualenv/padosiagent_django/src/3.11/lib64/python3.11/site-packages",
    "/home/m69qf6gyhm3n/virtualenv/padosiagentdjango/src/3.11/lib/python3.11/site-packages",
    "/home/m69qf6gyhm3n/virtualenv/padosiagentdjango/src/3.11/lib64/python3.11/site-packages",
]

for venv_dir in _VENVS:
    if os.path.exists(venv_dir) and venv_dir not in sys.path:
        sys.path.insert(0, venv_dir)

_razorpay_snapshot = None
_resync_razorpay = None
try:
    _rzp_spec = importlib.util.spec_from_file_location(
        "_padosi_razorpay_env_boot",
        PROJECT_ROOT / "padosi_agent" / "razorpay_env.py",
    )
    _rzp_mod = importlib.util.module_from_spec(_rzp_spec)
    _rzp_spec.loader.exec_module(_rzp_mod)
    _razorpay_snapshot = _rzp_mod.capture_razorpay_environ()
    _resync_razorpay = _rzp_mod.resync_razorpay_environ_after_dotenv
except Exception:
    pass

try:
    from dotenv import load_dotenv
    for env_path in (PROJECT_ROOT.parent / ".env", PROJECT_ROOT / ".env"):
        if env_path.exists():
            load_dotenv(env_path, override=True)
except ImportError:
    pass

if _resync_razorpay is not None and _razorpay_snapshot is not None:
    _resync_razorpay(PROJECT_ROOT, _razorpay_snapshot)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "padosi_agent.settings")

from django.core.wsgi import get_wsgi_application
django_wsgi_application = get_wsgi_application()

FASTAPI_ENABLED = False
_last_pid = None
_asgi_wsgi_app = None

try:
    import a2wsgi
    from padosi_agent.asgi import application as asgi_app
    FASTAPI_ENABLED = True
except Exception:
    import logging
    logging.getLogger(__name__).exception("ASGI/FastAPI could not be initialized")
    FASTAPI_ENABLED = False

def get_asgi_wsgi_application():
    """Lazily instantiate ASGIMiddleware per worker process to ensure event loop thread survives fork."""
    global _last_pid, _asgi_wsgi_app
    current_pid = os.getpid()
    if _asgi_wsgi_app is None or _last_pid != current_pid:
        from a2wsgi import ASGIMiddleware
        from padosi_agent.asgi import application as asgi_app
        _asgi_wsgi_app = ASGIMiddleware(asgi_app)
        _last_pid = current_pid
    return _asgi_wsgi_app

def application(environ, start_response):
    path = environ.get("PATH_INFO", "")
    if FASTAPI_ENABLED and (path.startswith("/api/") or path == "/api"):
        if path == "/api":
            start_response("307 Temporary Redirect", [("Location", "/api/docs"), ("Content-Length", "0")])
            return [b""]
        try:
            return get_asgi_wsgi_application()(environ, start_response)
        except Exception:
            import logging
            logging.getLogger(__name__).exception("FastAPI ASGI execution error; falling back to Django")
            return django_wsgi_application(environ, start_response)
    return django_wsgi_application(environ, start_response)
