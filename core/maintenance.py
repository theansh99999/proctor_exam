"""
core/maintenance.py
-------------------
Platform Maintenance Mode enforcement and management:
- Database-backed persistence (survives application restarts)
- High-performance in-memory TTL caching (5 seconds)
- Role-based bypass for Super Administrators
- Graceful 503 Service Unavailable page for candidates and examiners
- Seamless restoration when maintenance mode is disabled
"""
import time
import json
import logging
from typing import Optional
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse, HTMLResponse
from sqlalchemy.orm import Session
from jose import jwt, JWTError

import database
import models
from core.rbac import PlatformRole, normalize_role
from core.config import SECRET_KEY, ALGORITHM

logger = logging.getLogger("examproctor.maintenance")

_maintenance_cache = {
    "value": None,
    "expires_at": 0.0
}
CACHE_TTL_SECONDS = 5.0


def invalidate_maintenance_cache():
    """Immediately invalidate the maintenance mode memory cache."""
    global _maintenance_cache
    _maintenance_cache["value"] = None
    _maintenance_cache["expires_at"] = 0.0


def is_maintenance_mode(db: Optional[Session] = None) -> bool:
    """
    Check if maintenance mode is enabled in the database platform_configs table.
    Uses a 5-second in-memory cache to prevent database load spikes.
    """
    global _maintenance_cache
    now = time.time()
    if _maintenance_cache["value"] is not None and now < _maintenance_cache["expires_at"]:
        return _maintenance_cache["value"]

    should_close_db = False
    if db is None:
        try:
            db = database.SessionLocal()
            should_close_db = True
        except Exception as e:
            logger.warning("[MAINTENANCE] Could not open DB session: %s", e)
            return False

    is_active = False
    try:
        row = db.query(models.PlatformConfig).filter(models.PlatformConfig.key == "maintenance_mode").first()
        if row and row.value:
            v_str = str(row.value).strip().lower()
            is_active = v_str in ("true", "1", "yes", "on")
    except Exception as e:
        logger.warning("[MAINTENANCE] Error checking maintenance mode config: %s", e)
        is_active = False
    finally:
        if should_close_db:
            db.close()

    _maintenance_cache["value"] = is_active
    _maintenance_cache["expires_at"] = now + CACHE_TTL_SECONDS
    return is_active


EXEMPT_PATH_PREFIXES = (
    "/static",
    "/health",
    "/favicon.ico",
    "/login",
    "/logout",
    "/admin",
    "/api/v1/admin",
    "/run-tests",
)


def _is_request_exempt(path: str) -> bool:
    """Check if the request URL is exempt from maintenance mode."""
    if path == "/" or path == "/login" or path == "/logout":
        return True
    for prefix in EXEMPT_PATH_PREFIXES:
        if path == prefix or path.startswith(prefix + "/") or path.startswith(prefix + "?"):
            return True
    return False


def _is_super_admin_session(request: Request) -> bool:
    """Inspect request cookies or Authorization header for valid Super Admin credentials."""
    token = request.cookies.get("access_token")
    if not token:
        auth_hdr = request.headers.get("Authorization", "")
        if auth_hdr.startswith("Bearer "):
            token = auth_hdr.split(" ")[1]

    if not token:
        return False

    if token.startswith("Bearer "):
        token = token[7:]

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        role = payload.get("role")
        return normalize_role(role) == PlatformRole.SUPER_ADMIN
    except (JWTError, Exception):
        return False


class MaintenanceMiddleware(BaseHTTPMiddleware):
    """
    Middleware that enforces platform maintenance mode.
    When enabled:
    - Non-exempt requests by candidates or examiners receive HTTP 503.
    - Super Administrators maintain complete bypass and control.
    - Static assets and health checks remain accessible.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path

        # 1. Fast path for exempt routes
        if _is_request_exempt(path):
            return await call_next(request)

        # 2. Check maintenance mode status
        if not is_maintenance_mode():
            return await call_next(request)

        # 3. Super Admin bypass check
        if _is_super_admin_session(request):
            return await call_next(request)

        # 4. Render JSON response for API routes, HTML maintenance page for web UI
        if path.startswith("/api/"):
            return JSONResponse(
                status_code=503,
                content={
                    "error": "Service Unavailable",
                    "detail": "ExamProctor is currently undergoing scheduled platform maintenance. Assessment services will resume shortly."
                },
                headers={"Retry-After": "300"}
            )

        try:
            from core.templates import templates
            content = templates.get_template("maintenance.html").render({"request": request})
            return HTMLResponse(
                content=content,
                status_code=503,
                headers={"Retry-After": "300"}
            )
        except Exception as e:
            logger.error("[MAINTENANCE] Error rendering maintenance template: %s", e)
            return HTMLResponse(
                content="<h1>503 Service Unavailable</h1><p>Scheduled maintenance in progress. Please check back shortly.</p>",
                status_code=503,
                headers={"Retry-After": "300"}
            )
