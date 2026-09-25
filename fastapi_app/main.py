from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi_app.middleware.security_headers import SecurityHeadersMiddleware
from fastapi_app.middleware.threat_monitor import ThreatMonitorMiddleware
from fastapi_app.middleware.rate_limiter import RateLimitMiddleware
from fastapi_app.middleware.admin_auth import AdminAuthMiddleware
from fastapi_app.middleware.api_logger import APILoggingMiddleware
import os
import logging

from fastapi_app.config import settings
from fastapi_app.routers import (
    auth, dashboard, profile, public_profile,
    pincode, leads, notifications, analytics,
    qr, referral, find_agents, championship,
    plans
)
import fastapi_app.models

templates = Jinja2Templates(directory=os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates"))

logger = logging.getLogger(__name__)

# NOTE: Removed blocking startup DB connection and migration logic here
# to prevent "Resource temporarily unavailable" / timeout errors in Passenger WSGI.
# Database tables should be created externally or via a script, not automatically on every worker boot.

app = FastAPI(
    title="PadosiAgent FastAPI Service",
    description="Backend API for PadosiAgent Mobile App",
    version="1.0.0"
)

# Register Security & Request Processing Middlewares (LIFO Order)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RateLimitMiddleware, requests_limit=100, window_seconds=60)
app.add_middleware(APILoggingMiddleware)
app.add_middleware(ThreatMonitorMiddleware)
app.add_middleware(AdminAuthMiddleware)


# Include all consolidated routers
app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(profile.router)
app.include_router(public_profile.router)
app.include_router(pincode.router)
app.include_router(leads.router)
app.include_router(notifications.router)
app.include_router(analytics.router)
app.include_router(qr.router)
app.include_router(referral.router)
app.include_router(find_agents.router)
app.include_router(championship.router)
app.include_router(plans.router)

class RestrictedStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        # Disallow direct unauthenticated access to private documents / invoices
        normalized = path.replace("\\", "/").strip("/")
        if normalized.startswith("app/private") or "/app/private/" in f"/{normalized}/":
            return Response("Access Denied: Private media files must be accessed through authenticated Django routes.", status_code=403)
        return await super().get_response(path, scope)

# Mount local storage directory with private directory protection
os.makedirs(settings.LOCAL_STORAGE_PATH, exist_ok=True)
app.mount("/media", RestrictedStaticFiles(directory=settings.LOCAL_STORAGE_PATH), name="media")

@app.get("/v1/csrf-refresh/", response_class=JSONResponse)
@app.get("/v1/csrf-refresh", response_class=JSONResponse)
def csrf_refresh_api(request: Request):
    """
    Lightweight API endpoint for client-side JS to fetch a fresh CSRF token on-demand
    when mounted under ASGI (/api/v1/csrf-refresh/).
    """
    try:
        from django.middleware.csrf import _get_new_csrf_string
        fresh_token = _get_new_csrf_string()
    except Exception:
        import secrets
        fresh_token = secrets.token_hex(32)

    is_secure = request.url.scheme == "https"
    response = JSONResponse(
        content={
            "success": True,
            "csrf_token": fresh_token
        }
    )
    response.set_cookie("padosi_csrf_token", fresh_token, path="/", samesite="lax", secure=is_secure)
    return response

@app.get("/reset-password/{token}", response_class=HTMLResponse)
def get_reset_password_page(request: Request, token: str, email: str, type: str = "agent"):
    return templates.TemplateResponse(
        request=request,
        name="reset_password.html",
        context={
            "token": token,
            "email": email,
            "login_type": type,
            "app_url": settings.APP_URL,
            # Empty when served standalone, "/api" when mounted in the Django
            # ASGI app. The page posts back to itself, so it must match.
            "api_prefix": request.scope.get("root_path", "") or ""
        }
    )


def clean_error(err):
    if isinstance(err, dict):
        cleaned = {}
        for k, v in err.items():
            if k == 'ctx' and isinstance(v, dict):
                cleaned_ctx = {}
                for ctx_k, ctx_v in v.items():
                    if ctx_k == 'error' and isinstance(ctx_v, Exception):
                        cleaned_ctx[ctx_k] = str(ctx_v)
                    else:
                        cleaned_ctx[ctx_k] = clean_error(ctx_v)
                cleaned[k] = cleaned_ctx
            else:
                cleaned[k] = clean_error(v)
        return cleaned
    elif isinstance(err, list):
        return [clean_error(item) for item in err]
    elif isinstance(err, Exception):
        return str(err)
    else:
        return err

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.error(f"422 Validation Error on {request.method} {request.url}")
    logger.error(f"Validation details: {exc.errors()}")
    
    errors_dict = {}
    for error in exc.errors():
        loc = error.get("loc", [])
        field = str(loc[-1]) if loc else "non_field_errors"
        msg = error.get("msg", "Validation error")
        
        # Clean up Pydantic V2 prefixes
        if msg.startswith("Value error, "):
            msg = msg[len("Value error, "):]
        elif msg.startswith("Assertion failed, "):
            msg = msg[len("Assertion failed, "):]
            
        if field not in errors_dict:
            errors_dict[field] = []
        errors_dict[field].append(msg)
        
    return JSONResponse(
        status_code=422,
        content={
            "success": False,
            "message": "Validation failed",
            "errors": errors_dict
        },
    )

@app.get("/")
def health_check():
    return {"status": "ok", "service": "PadosiAgent FastAPI"}

@app.get("/get-ip")
def get_ip(request: Request):
    return {"ip": request.client.host}