from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse
import logging

logger = logging.getLogger(__name__)


def is_django_staff_session(session_key: str) -> bool:
    """Check if standard Django session corresponds to an authenticated staff/superuser."""
    if not session_key:
        return False
    try:
        from django.contrib.sessions.models import Session
        from django.contrib.auth import get_user_model
        session = Session.objects.filter(session_key=session_key).first()
        if session:
            data = session.get_decoded()
            user_id = data.get("_auth_user_id")
            if user_id:
                User = get_user_model()
                user = User.objects.filter(id=user_id, is_staff=True).first()
                return user is not None
    except Exception:
        pass
    return False


def is_valid_admin_session(token: str, session_key: str = None) -> bool:
    """Validate admin authentication from custom session_token or Django sessionid."""
    # 1. First check Django staff/superuser session if session_key provided
    if session_key and is_django_staff_session(session_key):
        return True

    if not token:
        return False

    # 2. Check cached admin info from Django admin context_processors
    try:
        from django.core.cache import cache
        cached_info = cache.get(f"admin_session_{token}")
        if cached_info and isinstance(cached_info, dict) and cached_info.get("admin_obj"):
            return True
    except Exception:
        pass

    # 3. Check database via django.db.connection (shares connection pool with Django)
    try:
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT s.id
                FROM user_sessions s
                LEFT JOIN user_session_data d ON s.id = d.session_id AND d.data_key = 'admin_id'
                WHERE s.session_token = %s
                  AND (s.expires_at > NOW() OR s.expires_at IS NULL)
                  AND (s.admin_id IS NOT NULL OR d.id IS NOT NULL)
                LIMIT 1
                """,
                [token],
            )
            if cursor.fetchone() is not None:
                return True
    except Exception as django_err:
        logger.debug("Django db check for admin session failed: %s; falling back to SQLAlchemy", django_err)

    # 4. Fallback check via SQLAlchemy engine
    try:
        from fastapi_app.database import engine
        from sqlalchemy import text
        with engine.connect() as conn:
            result = conn.execute(
                text("""
                SELECT s.id 
                FROM user_sessions s
                LEFT JOIN user_session_data d ON s.id = d.session_id AND d.data_key = 'admin_id'
                WHERE s.session_token = :token 
                  AND (s.expires_at > UTC_TIMESTAMP() OR s.expires_at IS NULL)
                  AND (s.admin_id IS NOT NULL OR d.id IS NOT NULL)
                LIMIT 1
                """),
                {"token": token}
            ).fetchone()
            return result is not None
    except Exception as e:
        logger.error(f"Error checking admin session in FastAPI middleware: {e}")
        return False


class AdminAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        
        # Completely ignore non-API / Django / Admin routes
        protected_paths = [
            "/docs", "/redoc", "/openapi.json", 
            "/docs/", "/redoc/", "/openapi.json/",
            "/api/docs", "/api/redoc", "/api/openapi.json",
            "/api/docs/", "/api/redoc/", "/api/openapi.json/"
        ]
        
        if not path.startswith("/api") and path not in protected_paths:
            return await call_next(request)
        
        # Only check admin session for docs / openapi
        if path in protected_paths:
            session_token = request.cookies.get("session_token")
            session_id = request.cookies.get("sessionid")
            if not await run_in_threadpool(is_valid_admin_session, session_token, session_id):
                return RedirectResponse(url="/admin/login/", status_code=303)

        response = await call_next(request)
        return response
