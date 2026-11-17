"""
core/security_headers.py
------------------------
Security Headers Middleware for production hardening:
- Strict-Transport-Security (HSTS)
- X-Content-Type-Options (nosniff)
- X-Frame-Options (SAMEORIGIN)
- Referrer-Policy
- Permissions-Policy
- Content-Security-Policy (CSP)
"""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
from fastapi import Request, Response
from core.config import IS_PRODUCTION


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)

        # 1. Prevent MIME-sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # 2. Clickjacking protection (permit framing only by same origin for examiner/camera feeds if needed)
        response.headers["X-Frame-Options"] = "SAMEORIGIN"

        # 3. Referrer Policy
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # 4. Permissions Policy: Restrict features to self (camera & microphone needed for proctoring)
        response.headers["Permissions-Policy"] = (
            "camera=(self), microphone=(self), geolocation=(), payment=()"
        )

        # 5. HSTS (HTTP Strict Transport Security) - enabled in production
        if IS_PRODUCTION:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"

        # 6. Content Security Policy (allow local assets, CDNs, Chart.js, Bootstrap, WebSockets)
        csp_directives = [
            "default-src 'self'",
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com",
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://fonts.googleapis.com",
            "font-src 'self' https://fonts.gstatic.com https://cdn.jsdelivr.net https://cdnjs.cloudflare.com data:",
            "img-src 'self' data: blob: https:",
            "connect-src 'self' ws: wss: https:",
            "media-src 'self' blob: mediastream: data:",
            "frame-ancestors 'self'"
        ]
        response.headers["Content-Security-Policy"] = "; ".join(csp_directives)

        return response
