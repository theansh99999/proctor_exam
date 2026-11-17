"""
main.py
-------
FastAPI Application Entrypoint for ExamProctor:
- Modular monolith router aggregation
- Production security headers & CORS middleware
- Observability and request correlation middleware
- Rate limiting middleware (SlowAPI)
- Health check endpoints (/health and /health/ready)
- Static asset serving
"""
import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from limiter import limiter
import models
from database import engine
from core.config import (
    ENVIRONMENT,
    IS_PRODUCTION,
    ALLOWED_ORIGINS,
    get_sanitized_config
)
from core.security_headers import SecurityHeadersMiddleware
from core.observability import ObservabilityMiddleware, health_router

logger = logging.getLogger("examproctor.app")

# In non-production and non-test environments, ensure schema tables exist
if not IS_PRODUCTION and not os.getenv("TESTING", ""):
    try:
        models.Base.metadata.create_all(bind=engine)
    except Exception as e:
        logger.warning("[STARTUP_WARN] Could not auto-create tables: %s", e)
    # Apply pending additive schema migrations (idempotent; tracks applied
    # versions in schema_migrations). Required on hosts without shell access
    # so existing databases gain new columns/tables after each deploy.
    try:
        from migrations import run_migrations
        run_migrations.run_upgrade(engine, confirm=True)
    except Exception as e:
        logger.warning("[STARTUP_WARN] Could not apply schema migrations: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup diagnostics
    cfg = get_sanitized_config()
    logger.info("[STARTUP] ExamProctor starting in '%s' environment.", cfg["environment"])
    logger.info("[STARTUP] Active DB: %s, Redis: %s", cfg["database_url"], cfg["redis_url"])
    yield
    # Graceful shutdown
    logger.info("[SHUTDOWN] ExamProctor shutting down gracefully.")


app = FastAPI(
    title="ExamProctor Platform",
    description="Enterprise Multi-Purpose Assessment, Proctoring and Examination Monolith",
    version="1.0.0",
    lifespan=lifespan
)

# ── Middlewares (Order of execution: LIFO for responses) ──────────────────────
# 1. Rate Limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# 2. Security Headers (HSTS, CSP, X-Frame-Options, Nosniff)
app.add_middleware(SecurityHeadersMiddleware)

# 3. Observability & Timing (X-Request-ID, X-Process-Time, Access logging)
app.add_middleware(ObservabilityMiddleware)

# 4. CORS Whitelisting
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "X-Process-Time"]
)

# ── Health & Observability Router ─────────────────────────────────────────────
app.include_router(health_router)

# ── Static Files & Templates ──────────────────────────────────────────────────
app.mount("/static", StaticFiles(directory="static"), name="static")

# ── Routers ───────────────────────────────────────────────────────────────────
from routers import auth_r, teacher_r, student_r, websocket_r, admin_r
from modules.organizations import organization_router
from modules.users import user_router
from modules.assessments import assessment_router
from modules.integrations import integration_router
from modules.questions import question_bank_router
from modules.proctoring.router import router as proctoring_router
from modules.evaluation import evaluation_router
from modules.analytics import analytics_router
from modules.notifications import notification_router
from modules.admin import admin_router

app.include_router(auth_r.router)
app.include_router(teacher_r.router)
app.include_router(student_r.router)
app.include_router(websocket_r.router)
app.include_router(admin_r.router)

# Mount API v1 Modular Monolith Endpoints
app.include_router(organization_router, prefix="/api/v1/organizations")
app.include_router(user_router, prefix="/api/v1/users")
app.include_router(assessment_router, prefix="/api/v1/assessments")
app.include_router(question_bank_router, prefix="/api/v1/question-bank")
app.include_router(integration_router, prefix="/api/v1/integrations")
app.include_router(notification_router, prefix="/api/v1/notifications")
app.include_router(proctoring_router)
app.include_router(evaluation_router)
app.include_router(analytics_router, prefix="/api/v1/analytics")
app.include_router(admin_router, prefix="/api/v1/admin")


@app.get("/")
def home(request: Request):
    return RedirectResponse(url="/login")


@app.get("/run-tests")
def run_tests_endpoint():
    from fastapi.responses import HTMLResponse
    try:
        from testing.test_runner import run_all_tests_and_get_report
    except ModuleNotFoundError:
        return HTMLResponse(content="<h1>Test suite not available in this deployment</h1>", status_code=503)
    html_content = run_all_tests_and_get_report()
    return HTMLResponse(content=html_content, status_code=200)


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "10000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
