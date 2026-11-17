"""
core/observability.py
---------------------
Observability, structured logging, and health monitoring:
- Request ID correlation (X-Request-ID)
- Request latency timing (X-Process-Time)
- Structured access logging
- /health and /health/ready endpoints for liveness & readiness probes
"""
import time
import uuid
import logging
from typing import Callable
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
from fastapi import Request, Response, APIRouter, status
from fastapi.responses import JSONResponse

from database import check_database_health
from core.cache import check_redis_health
from time_utils import utc_now, to_utc_iso

logger = logging.getLogger("examproctor.access")


class ObservabilityMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # 1. Request ID correlation
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id

        # 2. Timing
        start_time = time.perf_counter()
        response: Response = await call_next(request)
        process_time_ms = round((time.perf_counter() - start_time) * 1000, 2)

        # 3. Add headers
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time"] = f"{process_time_ms}ms"

        # 4. Filter static file noise from main access log
        if not request.url.path.startswith("/static/"):
            client_ip = request.client.host if request.client else "unknown"
            logger.info(
                "[%s] %s %s - %d (%s ms) client=%s",
                request_id[:8],
                request.method,
                request.url.path,
                response.status_code,
                process_time_ms,
                client_ip
            )

        return response


# ── Health Check Router ───────────────────────────────────────────────────────
health_router = APIRouter(tags=["System Health & Observability"])


@health_router.get("/health", status_code=status.HTTP_200_OK)
def liveness_probe():
    """
    Liveness probe: verifies that the FastAPI application process is alive and responsive.
    Kubernetes / Docker Compose health checks use this endpoint.
    """
    return {
        "status": "ok",
        "service": "ExamProctor",
        "timestamp": to_utc_iso(utc_now())
    }


@health_router.get("/health/ready")
def readiness_probe():
    """
    Readiness probe: validates critical dependencies (database and cache connectivity).
    Returns HTTP 200 if dependencies are operational; HTTP 503 if database is disconnected.
    Never exposes internal credentials, connection strings or IP addresses.
    """
    db_health = check_database_health()
    redis_health = check_redis_health()

    is_ready = (db_health.get("status") == "healthy")
    http_status = status.HTTP_200_OK if is_ready else status.HTTP_503_SERVICE_UNAVAILABLE

    return JSONResponse(
        content={
            "status": "ready" if is_ready else "not_ready",
            "timestamp": to_utc_iso(utc_now()),
            "checks": {
                "database": db_health.get("status"),
                "cache": redis_health.get("status"),
                "cache_mode": redis_health.get("mode")
            }
        },
        status_code=http_status
    )
