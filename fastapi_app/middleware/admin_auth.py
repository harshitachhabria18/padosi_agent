from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi_app.database import engine
from sqlalchemy import text
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

def is_valid_admin_session(token: str) -> bool:
    if not token:
        return False
    now_utc = datetime.utcnow()
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text("""
                SELECT s.id 
                FROM user_sessions s
                JOIN user_session_data d ON s.id = d.session_id
                WHERE s.session_token = :token 
                  AND s.expires_at > :now_utc
                  AND d.data_key = 'admin_id'
                LIMIT 1
                """),
                {"token": token, "now_utc": now_utc}
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
            if not await run_in_threadpool(is_valid_admin_session, session_token):
                return RedirectResponse(url="/admin/login/", status_code=303)

        response = await call_next(request)
        return response
