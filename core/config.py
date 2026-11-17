"""
core/config.py
--------------
Centralized, validated configuration for ExamProctor.
Separates environments: development, testing, staging, production.
Enforces strict secret validation, database connection pooling parameters,
Redis caching configuration, CORS rules, and security headers.
"""
import os
import re
from typing import List, Optional
from dotenv import load_dotenv

load_dotenv()

# ── Environment ───────────────────────────────────────────────────────────────
ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()
IS_PRODUCTION = ENVIRONMENT == "production"
IS_STAGING = ENVIRONMENT == "staging"
IS_TESTING = bool(os.getenv("TESTING", "") or ENVIRONMENT == "testing")

# ── Security & Authentication ─────────────────────────────────────────────────
SECRET_KEY = os.getenv("SECRET_KEY", "change-to-generated-secure-random-key-using-python-secrets-module-min-32-chars")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "120"))

# Production Security Gate: Fail fast if default or insecure secrets are used in production
INSECURE_SECRET_DEFAULTS = {
    "default-secret-key-change-in-production-min-32-chars",
    "change-to-generated-secure-random-key-using-python-secrets-module-min-32-chars",
    "secret",
    "changeme",
    "admin"
}

if IS_PRODUCTION:
    if not SECRET_KEY or SECRET_KEY in INSECURE_SECRET_DEFAULTS or len(SECRET_KEY) < 32:
        raise ValueError(
            "FATAL: Insecure or default SECRET_KEY detected in PRODUCTION environment! "
            "Set a cryptographically strong SECRET_KEY (min 32 characters) using python secrets module."
        )

# ── Database Configuration ───────────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/exam_proctor")

# Connection Pooling Settings
DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "20"))
DB_MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "10"))
DB_POOL_TIMEOUT = int(os.getenv("DB_POOL_TIMEOUT", "30"))
DB_POOL_RECYCLE = int(os.getenv("DB_POOL_RECYCLE", "1800"))  # Recycle connections every 30 mins

# ── Redis & Caching Configuration ─────────────────────────────────────────────
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CACHE_ENABLED = os.getenv("CACHE_ENABLED", "true").lower() in ("true", "1", "yes")
CACHE_DEFAULT_TTL = int(os.getenv("CACHE_DEFAULT_TTL", "300"))  # 5 minutes default

# ── CORS & Host Security ──────────────────────────────────────────────────────
ALLOWED_HOSTS_RAW = os.getenv("ALLOWED_HOSTS", "*")
ALLOWED_HOSTS: List[str] = [h.strip() for h in ALLOWED_HOSTS_RAW.split(",") if h.strip()]

ALLOWED_ORIGINS_RAW = os.getenv("ALLOWED_ORIGINS", "http://localhost:10000,http://127.0.0.1:10000")
ALLOWED_ORIGINS: List[str] = [o.strip() for o in ALLOWED_ORIGINS_RAW.split(",") if o.strip()]

# Cookie Security
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "true" if IS_PRODUCTION else "false").lower() in ("true", "1")
COOKIE_SAMESITE = os.getenv("COOKIE_SAMESITE", "lax")

# ── Email / SMTP Configuration ────────────────────────────────────────────────
MAIL_USERNAME = os.getenv("MAIL_USERNAME", "")
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "")
MAIL_FROM = os.getenv("MAIL_FROM", "ExamProctor <noreply@examproctor.com>")
MAIL_PORT = int(os.getenv("MAIL_PORT", "587"))
MAIL_SERVER = os.getenv("MAIL_SERVER", "smtp.gmail.com")
MAIL_TLS = os.getenv("MAIL_TLS", "true").lower() in ("true", "1")
MAIL_SSL = os.getenv("MAIL_SSL", "false").lower() in ("true", "1")
MOCK_EMAIL = os.getenv("MOCK_EMAIL", "false" if IS_PRODUCTION else "true").lower() in ("true", "1")

# ── External Integrations ─────────────────────────────────────────────────────
SERVICENOW_INSTANCE_URL = os.getenv("SERVICENOW_INSTANCE_URL", "")
SERVICENOW_USERNAME = os.getenv("SERVICENOW_USERNAME", "")
SERVICENOW_PASSWORD = os.getenv("SERVICENOW_PASSWORD", "")

QUESTION_GENERATOR_API_URL = os.getenv("QUESTION_GENERATOR_API_URL", "")
QUESTION_GENERATOR_API_KEY = os.getenv("QUESTION_GENERATOR_API_KEY", "")

# ── API Paths ─────────────────────────────────────────────────────────────────
API_V1_PREFIX = "/api/v1"


def get_sanitized_config() -> dict:
    """Return runtime configuration with all secrets and passwords securely masked for debugging/monitoring."""
    def _mask(val: Optional[str]) -> str:
        if not val:
            return "<not set>"
        if len(val) <= 4:
            return "****"
        return val[:2] + "****" + val[-2:]

    def _mask_url(url: str) -> str:
        # Mask password in connection strings like postgresql://user:pass@host:5432/db
        return re.sub(r"://([^:]+):([^@]+)@", r"://\1:****@", url)

    return {
        "environment": ENVIRONMENT,
        "is_production": IS_PRODUCTION,
        "is_staging": IS_STAGING,
        "is_testing": IS_TESTING,
        "database_url": _mask_url(DATABASE_URL),
        "db_pool_size": DB_POOL_SIZE,
        "db_max_overflow": DB_MAX_OVERFLOW,
        "db_pool_recycle": DB_POOL_RECYCLE,
        "redis_url": _mask_url(REDIS_URL),
        "cache_enabled": CACHE_ENABLED,
        "allowed_hosts": ALLOWED_HOSTS,
        "allowed_origins": ALLOWED_ORIGINS,
        "cookie_secure": COOKIE_SECURE,
        "cookie_samesite": COOKIE_SAMESITE,
        "mail_server": MAIL_SERVER,
        "mail_port": MAIL_PORT,
        "mail_username": _mask(MAIL_USERNAME),
        "mail_from": MAIL_FROM,
        "mock_email": MOCK_EMAIL,
        "servicenow_configured": bool(SERVICENOW_INSTANCE_URL and SERVICENOW_USERNAME),
        "question_gen_configured": bool(QUESTION_GENERATOR_API_URL and QUESTION_GENERATOR_API_KEY)
    }
