# ExamProctor — Environment Variables Reference

This document provides a comprehensive specification of all environment variables supported by the ExamProctor platform (`core/config.py`).

## 1. Core Application Configuration

| Variable | Type | Default | Required in Prod | Description |
| :--- | :--- | :--- | :--- | :--- |
| `ENVIRONMENT` | string | `development` | **YES** | Target environment: `development`, `staging`, `production`, or `testing`. Controls validation strictness. |
| `APP_NAME` | string | `ExamProctor API` | No | Platform display name in OpenAPI schema and notification headers. |
| `DEBUG` | boolean | `False` | No | Enables debug stack traces in errors. Must be `False` in production. |
| `API_V1_PREFIX` | string | `/api/v1` | No | Global URL route prefix for version 1 REST APIs. |

---

## 2. Security & Authentication

| Variable | Type | Default | Required in Prod | Description |
| :--- | :--- | :--- | :--- | :--- |
| `SECRET_KEY` | string | *(dev key)* | **YES** | 256-bit cryptographic signing key for JWT tokens. In production, default raises fatal error. |
| `ALGORITHM` | string | `HS256` | No | JWT signing algorithm. Standard: `HS256`. |
| `ACCESS_TOKEN_EXPIRE_MINUTES`| integer | `60` | No | Access token validity duration in minutes. |
| `REFRESH_TOKEN_EXPIRE_DAYS` | integer | `7` | No | Refresh token validity period in days. |
| `CORS_ORIGINS` | string / list | `*` | **YES** | Comma-separated list of allowed frontend origins. Wildcard `*` rejected in production. |

---

## 3. Database & Connection Pooling

| Variable | Type | Default | Required in Prod | Description |
| :--- | :--- | :--- | :--- | :--- |
| `DATABASE_URL` | string | *(sqlite)* | **YES** | Full PostgreSQL connection URI: `postgresql://user:pass@host:5432/dbname`. |
| `DB_POOL_SIZE` | integer | `20` | No | Maximum persistent connections maintained in the SQLAlchemy pool. |
| `DB_MAX_OVERFLOW` | integer | `10` | No | Additional transient connections allowed beyond `DB_POOL_SIZE` during traffic bursts. |
| `DB_POOL_TIMEOUT` | integer | `30` | No | Seconds to wait for an available connection from the pool before raising an error. |
| `DB_POOL_RECYCLE` | integer | `1800` | No | Seconds after which a connection is closed and re-established (prevents stale TCP sockets). |
| `DB_POOL_PRE_PING`| boolean | `True` | No | Tests connections with a ping query before checkout to handle remote disconnects. |

---

## 4. Redis & Caching

| Variable | Type | Default | Required in Prod | Description |
| :--- | :--- | :--- | :--- | :--- |
| `REDIS_URL` | string | `redis://localhost:6379/0` | Recommended | Redis connection URI. If unavailable, falls back to in-memory TTL caching. |
| `REDIS_PASSWORD` | string | `None` | If Auth req | Authentication password for Redis server / cluster. |
| `REDIS_TIMEOUT` | integer | `2` | No | Redis connection and command timeout in seconds. |
| `CACHE_TTL_DEFAULT`| integer | `300` | No | Default expiration time in seconds for cached queries and sessions (5 minutes). |

---

## 5. Background Worker & Scheduled Tasks

| Variable | Type | Default | Required in Prod | Description |
| :--- | :--- | :--- | :--- | :--- |
| `WORKER_POLL_INTERVAL` | integer | `30` | No | Sleep interval in seconds between background worker job execution loops. |
| `AUTO_FINALIZE_GRACE_MINUTES` | integer | `5` | No | Grace period in minutes after exam end time before worker automatically finalizes unsubmitted sessions. |

---

## 6. Email & Notifications (SMTP)

| Variable | Type | Default | Required in Prod | Description |
| :--- | :--- | :--- | :--- | :--- |
| `SMTP_HOST` | string | `smtp.example.com` | If Email req | Outgoing SMTP mail server hostname. |
| `SMTP_PORT` | integer | `587` | If Email req | SMTP port (typically `587` for TLS / STARTTLS, `465` for SSL). |
| `SMTP_USER` | string | `None` | If Email req | Username for SMTP authentication. |
| `SMTP_PASSWORD` | string | `None` | If Email req | Password for SMTP authentication (sensitive). |
| `SMTP_FROM_EMAIL`| string | `noreply@examproctor.com` | If Email req | Sender address appearing on automated notification emails. |

---

## 7. External Integrations

| Variable | Type | Default | Required in Prod | Description |
| :--- | :--- | :--- | :--- | :--- |
| `SERVICENOW_INSTANCE_URL` | string | `None` | Optional | Base URL for ServiceNow grade export sync. |
| `SERVICENOW_CLIENT_ID` | string | `None` | Optional | OAuth Client ID for ServiceNow integration. |
| `SERVICENOW_CLIENT_SECRET` | string | `None` | Optional | OAuth Client Secret for ServiceNow integration (sensitive). |
| `AI_QUESTION_GEN_API_KEY` | string | `None` | Optional | API key for external LLM-driven question bank authoring (sensitive). |

---

## 8. Safe Configuration Inspection

To inspect the runtime configuration without leaking sensitive credentials, use `get_sanitized_config()`:
```python
from core.config import get_sanitized_config
import pprint
pprint.pprint(get_sanitized_config())
```
All passwords, secrets, and auth tokens are automatically masked (e.g. `******`).
