import re
import json
import time
import logging
import threading
import urllib.request
import urllib.error
import html
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request
from fastapi.responses import JSONResponse
from datetime import datetime, timedelta

from fastapi_app.config import settings
from fastapi_app.database import SessionLocal
from fastapi_app.models.blocked_ip import BlockedIp
from fastapi_app.models.security_threat_log import SecurityThreatLog
from fastapi_app.models.user import User
from fastapi_app.models.agent import Agent

logger = logging.getLogger(__name__)

# WAF Regex Patterns
PATTERNS = {
    "SQL Injection": r"(union select\s|select\s+\*\s+from|insert\s+into|update\s+\w+\s+set|'\s*or\s*'1'\s*=\s*'1|sleep\(\d+\)|benchmark\s*\(|group_concat|information_schema)",
    "Cross Site Scripting (XSS)": r"(<script\b[^>]*>|javascript:|onerror=|onload=|eval\(|setTimeout\(|setInterval\(|alert\(|document\.cookie|document\.domain|window\.location)",
    "Path Traversal / LFI": r"(\.\.\/|\.\.\\\\|\/etc\/passwd|\/etc\/shadow|\/etc\/group|\/etc\/hosts|\/proc\/self|php:\/\/filter|php:\/\/input|expect:\/\/)",
    "RCE / Shell Injection": r"(system\(|exec\(|passthru\(|shell_exec\(|proc_open\(|pcntl_exec\(|python\s+-c|perl\s+-e|ruby\s+-e|bash\s+-i|nc\s+-e)",
    "SSRF / Metadata API": r"(169\.254\.169\.254|metadata\.google\.internal|\/latest\/meta-data\/)",
    "XML External Entity (XXE)": r"(<!ENTITY\s+|SYSTEM\s+[\"']|PUBLIC\s+[\"'])",
    "Server-Side Template Injection": r"({{\s*[\s\S]*\s*}}|{%\s*[\s\S]*\s*%}|\[\[\s*[\s\S]*\s*\]\])",
    "CRLF / Header Injection": r"(\%0d\%0a|Set-Cookie:|Content-Type:)",
}

LOCAL_HOSTS = ["127.0.0.1", "::1", "testclient", "localhost", "testserver"]

# One alert email per IP per window (the Django WAF uses the same 10 minutes).
# Previously every detection sent a synchronous email with no timeout, so a
# stream of payloads was both email-bombing and an event-loop stall.
ALERT_EMAIL_WINDOW_SECONDS = 600
_alert_sent_at = {}
_alert_lock = threading.Lock()


def _should_send_alert(ip: str) -> bool:
    now = time.time()
    with _alert_lock:
        last = _alert_sent_at.get(ip)
        if last and now - last < ALERT_EMAIL_WINDOW_SECONDS:
            return False
        if len(_alert_sent_at) > 5000:
            _alert_sent_at.clear()
        _alert_sent_at[ip] = now
        return True


AUTO_BLOCK_TTL = timedelta(hours=24)


def _auto_block_expired(block) -> bool:
    reason = getattr(block, "reason", "") or ""
    created = getattr(block, "created_at", None)
    if not reason.startswith("Auto-blocked") or not created:
        return False
    try:
        # Rows may be written by Django (local time) or FastAPI (UTC); measure
        # from the earlier clock so a block never expires early.
        return created < min(datetime.utcnow(), datetime.now()) - AUTO_BLOCK_TTL
    except TypeError:
        return False


def _match_threat(input_str: str, url_str: str, is_admin_route: bool):
    input_str_for_crlf = input_str.replace('\\r\\n', ' ').replace('\r\n', ' ')
    for type_name, pattern in PATTERNS.items():
        if type_name == "Server-Side Template Injection" and is_admin_route:
            continue
        str_to_check = input_str_for_crlf if type_name == "CRLF / Header Injection" else input_str
        if re.search(pattern, str_to_check, re.IGNORECASE) or re.search(pattern, url_str, re.IGNORECASE):
            return type_name
    return None


def _send_alert_email(ip, type_matched, url_str, location, isp, hacker_name, hacker_email,
                      is_auto_blocked, ban_reason, user_agent, input_str):
    if not settings.BREVO_API_KEY or not settings.SECURITY_ALERT_EMAIL:
        return
    e = html.escape
    threat_html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6;">
        <h2 style="color: #c0392b;">⚠️ SECURITY ALERT: Malicious Activity Detected on PadosiAgent</h2>
        <p>A security threat event was detected and blocked by the FastAPI Threat Monitor WAF.</p>
        <table border="1" cellpadding="8" style="border-collapse: collapse; width: 100%; max-width: 600px; border-color: #ddd;">
            <tr bgcolor="#f2f2f2"><th align="left">Field</th><th align="left">Details</th></tr>
            <tr><td><strong>IP Address</strong></td><td>{e(ip)}</td></tr>
            <tr><td><strong>Event Type</strong></td><td>{e(type_matched)}</td></tr>
            <tr><td><strong>Request URL</strong></td><td>{e(url_str)}</td></tr>
            <tr><td><strong>Location</strong></td><td>{e(location)}</td></tr>
            <tr><td><strong>ISP</strong></td><td>{e(isp)}</td></tr>
            <tr><td><strong>Hacker Account</strong></td><td>{e(str(hacker_name))} ({e(str(hacker_email or 'Guest'))})</td></tr>
            <tr><td><strong>Auto-Banned?</strong></td><td>{'YES' if is_auto_blocked else 'NO'} {e(f'({ban_reason})') if is_auto_blocked else ''}</td></tr>
            <tr><td><strong>User Agent</strong></td><td>{e(user_agent)}</td></tr>
        </table>
        <p><strong>Payload preview (first 500 chars):</strong></p>
        <pre style="background: #f8f9fa; padding: 10px; border: 1px solid #ddd; max-width: 600px; overflow-x: auto;">{e(input_str[:500])}</pre>
    </body>
    </html>
    """

    brevo_payload = {
        "sender": {"name": "Security Grid", "email": settings.BREVO_FROM_EMAIL or "noreply@padosiagent.com"},
        "to": [{"email": settings.SECURITY_ALERT_EMAIL, "name": "Security Admin"}],
        "subject": "⚠️ SECURITY ALERT: Malicious Activity Detected on PadosiAgent",
        "htmlContent": threat_html
    }

    req_email = urllib.request.Request(
        "https://api.brevo.com/v3/smtp/email",
        data=json.dumps(brevo_payload).encode("utf-8"),
        headers={
            "api-key": settings.BREVO_API_KEY,
            "Content-Type": "application/json",
            "Accept": "application/json"
        },
        method="POST"
    )
    with urllib.request.urlopen(req_email, timeout=10) as resp_email:
        resp_email.read()


def _inspect_request(ip, input_str, url_str, auth_header, user_agent):
    """Blocking DB/email work — runs in a worker thread, never on the event loop.

    Returns None to allow the request, or a (status, body) tuple to reject it.
    """
    try:
        db = SessionLocal()
    except Exception:
        return None

    try:
        # Check if IP is blocked in database
        try:
            is_blocked = db.query(BlockedIp).filter(BlockedIp.ip_address == ip).first()
            if is_blocked and _auto_block_expired(is_blocked):
                # Automatic blocks expire after 24h (shared mobile IPs); manual
                # admin blocks stay. Mirrors apps.admin_panel.middleware.is_ip_blocked.
                db.delete(is_blocked)
                db.commit()
                is_blocked = None
            if is_blocked:
                return 403, {"error": "Forbidden", "message": "Your IP address has been blocked due to suspicious activity."}
        except Exception:
            pass

        is_admin_route = "/admin/" in url_str or "/api/v1/championship/admin" in url_str
        type_matched = _match_threat(input_str, url_str, is_admin_route)
        if not type_matched:
            return None

        # Malicious Activity Detected - Gather Hacker details
        hacker_name = "GUEST / ANONYMOUS"
        hacker_email = None
        hacker_mobile = None

        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
            try:
                from fastapi_app.utils.auth import decode_token
                payload = decode_token(token)
                if payload and payload.get("sub"):
                    email = payload.get("sub")
                    user = db.query(User).filter(User.email == email).first()
                    if user:
                        hacker_name = user.fullname
                        hacker_email = user.email
                        agent = db.query(Agent).filter(Agent.email == email).first()
                        if agent:
                            hacker_mobile = agent.mobile
            except Exception:
                pass

        # Location & ISP (non-blocking, avoids external HTTP DoS vulnerability)
        location = "Unknown"
        isp = "Unknown"

        # Check auto-ban threshold (3 threats within 1 hour)
        is_auto_blocked = False
        ban_reason = ""
        if settings.WAF_AUTO_BAN_ENABLED:
            one_hour_ago = datetime.utcnow() - timedelta(hours=1)
            recent_threats_count = db.query(SecurityThreatLog).filter(
                SecurityThreatLog.ip_address == ip,
                SecurityThreatLog.created_at >= one_hour_ago
            ).count()

            if recent_threats_count >= 2:  # this would be the 3rd offense
                already_blocked = db.query(BlockedIp).filter(BlockedIp.ip_address == ip).first()
                if not already_blocked:
                    db.add(BlockedIp(
                        ip_address=ip,
                        reason=f"Auto-blocked by Threat Monitor due to recurring malicious payloads ({type_matched})."
                    ))
                is_auto_blocked = True
                ban_reason = "Auto-blocked due to 3+ malicious payload detections in 1 hour."

        # Record Threat Log in database
        db.add(SecurityThreatLog(
            ip_address=ip,
            event_type=type_matched,
            hacker_name=hacker_name,
            hacker_email=hacker_email,
            hacker_mobile=hacker_mobile,
            location=location,
            isp=isp,
            url=url_str,
            payload=input_str[:1000],
            user_agent=user_agent
        ))
        db.commit()

        if _should_send_alert(ip):
            try:
                _send_alert_email(ip, type_matched, url_str, location, isp, hacker_name, hacker_email,
                                  is_auto_blocked, ban_reason, user_agent, input_str)
            except Exception as email_err:
                # Non-blocking, keep middleware robust
                logger.warning("Failed to send security alert email: %s", email_err)

        return 403, {"error": "Forbidden", "message": "Malicious activity detected."}
    finally:
        db.close()


class ThreatMonitorMiddleware(BaseHTTPMiddleware):
    @staticmethod
    def get_client_ip(request: Request) -> str:
        from fastapi_app.utils.client_ip import get_client_ip
        return get_client_ip(request)

    async def dispatch(self, request: Request, call_next):
        # 1. Resolve client IP safely
        client_host = request.client.host if request.client else "127.0.0.1"
        ip = self.get_client_ip(request)

        # 2. Whitelist local/trusted IPs only if direct connection is genuinely local
        if client_host in LOCAL_HOSTS and ip in LOCAL_HOSTS:
            return await call_next(request)

        # 3. Extract input payload (avoid reading multipart/form-data request bodies)
        content_type = request.headers.get("content-type", "")
        if "multipart/form-data" in content_type:
            input_str = ""
        else:
            # BaseHTTPMiddleware caches body() and replays it downstream. Do not
            # replace request._receive: Starlette reads it again to wait for
            # http.disconnect and raises RuntimeError on a repeated http.request.
            body_bytes = await request.body()
            input_str = body_bytes.decode("utf-8", errors="ignore")

        verdict = await run_in_threadpool(
            _inspect_request,
            ip,
            input_str,
            str(request.url),
            request.headers.get("authorization"),
            request.headers.get("user-agent", "N/A"),
        )
        if verdict is not None:
            status_code, body = verdict
            return JSONResponse(status_code=status_code, content=body)

        return await call_next(request)
