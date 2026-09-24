from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request, Response
from fastapi_app.config import settings

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        
        # Remove fingerprinting headers
        if "x-powered-by" in response.headers:
            del response.headers["x-powered-by"]
        if "server" in response.headers:
            del response.headers["server"]
        if "Server" in response.headers:
            del response.headers["Server"]
        if "X-Powered-By" in response.headers:
            del response.headers["X-Powered-By"]
            
        # Security headers matching Laravel
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(self), payment=(self)"
        response.headers["X-Permitted-Cross-Domain-Policies"] = "none"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin-allow-popups"
        response.headers["Cross-Origin-Resource-Policy"] = "same-site"
        
        # HSTS (Force HTTPS)
        if settings.APP_URL.startswith("https://"):
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
            
        # Content-Security-Policy (CSP) matching PHP Laravel exact policies
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' "
            "https://cdn.jsdelivr.net https://cdnjs.cloudflare.com "
            "https://checkout.razorpay.com https://api.razorpay.com "
            "https://connect.facebook.net https://www.googletagmanager.com "
            "https://www.google-analytics.com https://www.gstatic.com "
            "https://unpkg.com https://assets.calendly.com "
            "https://www.clarity.ms https://*.clarity.ms; "
            "style-src 'self' 'unsafe-inline' "
            "https://fonts.googleapis.com https://cdn.jsdelivr.net "
            "https://cdnjs.cloudflare.com https://unpkg.com "
            "https://assets.calendly.com; "
            "font-src 'self' data: "
            "https://fonts.gstatic.com https://cdnjs.cloudflare.com; "
            "img-src 'self' data: blob: https://fastapi.tiangolo.com "
            "https://www.facebook.com https://www.google-analytics.com "
            "https://*.clarity.ms https://c.clarity.ms; "
            "frame-src 'self' "
            "https://checkout.razorpay.com https://api.razorpay.com "
            "https://calendly.com; "
            "connect-src 'self' "
            "https://api.razorpay.com wss: ws: "
            "https://fcm.googleapis.com https://firebaseinstallations.googleapis.com "
            "https://www.google-analytics.com "
            "https://*.clarity.ms https://www.clarity.ms "
            "https://*.on.aws "
            "https://*.run.app; "
            "worker-src 'self' blob:; "
            "manifest-src 'self';"
        )
        
        return response
