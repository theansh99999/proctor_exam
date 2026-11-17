# ExamProctor — Production Deployment Guide

## 1. System Architecture Overview

ExamProctor is an enterprise-grade, modular monolith assessment and proctoring platform designed for high concurrency, zero-data-loss examination workflows, and robust proctoring integrity.

```
                      ┌─────────────────────────────────────────┐
                      │          Nginx Reverse Proxy            │
                      │    (SSL Termination / HTTP/2 / WSS)     │
                      └────────────────────┬────────────────────┘
                                           │
                    ┌──────────────────────┴──────────────────────┐
                    │                                             │
                    ▼                                             ▼
     ┌─────────────────────────────┐               ┌─────────────────────────────┐
     │   FastAPI Web Cluster       │               │   Background Async Worker   │
     │  (Gunicorn + Uvicorn Workers)│              │  (Scheduled jobs, sync,     │
     │  Non-root `appuser` (10001) │               │   session auto-finalize)    │
     └──────────────┬──────────────┘               └──────────────┬──────────────┘
                    │                                             │
          ┌─────────┴───────────────┐                             │
          ▼                         ▼                             ▼
┌───────────────────┐     ┌───────────────────┐         ┌───────────────────┐
│  PostgreSQL 15+   │     │      Redis 7+     │         │ External Services │
│ (Pool: 20+10,     │     │ (Distributed Lock,│         │ (ServiceNow,      │
│  Pre-ping, SSL)   │     │  Cache, TTL Fallbk│         │  LLM Generators)  │
└───────────────────┘     └───────────────────┘         └───────────────────┘
```

---

## 2. Infrastructure Prerequisites

| Component | Minimum Specification | Recommended Production Spec |
| :--- | :--- | :--- |
| **CPU** | 2 vCPU | 4–8 vCPU |
| **RAM** | 4 GB | 16 GB |
| **Disk** | 40 GB SSD | 200 GB NVMe SSD (with automated snapshots) |
| **OS** | Linux (Ubuntu 22.04 LTS / Debian 12) | Linux (Ubuntu 22.04 LTS) |
| **Container Engine**| Docker Engine 24+ & Docker Compose v2 | Docker Engine 24+ |
| **Database** | PostgreSQL 15+ | AWS RDS PostgreSQL 15 / Managed Cloud PostgreSQL |
| **In-Memory Store** | Redis 7+ | AWS ElastiCache / Redis Cluster |

---

## 3. Containerized Deployment (Recommended)

ExamProctor ships with a hardened, multi-stage, rootless Dockerfile and a multi-container Compose topology.

### 3.1 Step 1: Clone Repository and Enter Directory
```bash
git clone https://github.com/organization/exam-proctor.git
cd "exam-proctor"
```

### 3.2 Step 2: Configure Environment Variables
Copy `.env.production.example` to `.env`:
```bash
cp .env.production.example .env
chmod 600 .env
```
Ensure all required secrets are generated and populated (see `docs/ENVIRONMENT_VARIABLES.md`). Critical variables:
- `ENVIRONMENT=production`
- `SECRET_KEY=<generate with openssl rand -hex 32>`
- `DB_PASSWORD=<secure-strong-password>`
- `REDIS_PASSWORD=<secure-redis-password>`
- `CORS_ORIGINS=https://exams.yourdomain.com`

### 3.3 Step 3: Build and Launch Services
```bash
docker compose -f docker-compose.yml up -d --build
```

### 3.4 Step 4: Verify Container Health
```bash
docker compose ps
docker compose logs -f web
```
Both `web` and `worker` should show `healthy` status via built-in curl health probes.

---

## 4. Database Setup & Migration Execution

### 4.1 Automated Schema Migration
ExamProctor maintains a dedicated migration runner (`migrations/run_migrations.py`) tracking applied migrations in `schema_migrations`.

To apply all migrations (Phases 1 through 11):
```bash
# In Container:
docker compose exec web python migrations/run_migrations.py upgrade --confirm

# On Bare-Metal / Virtual Environment:
python migrations/run_migrations.py upgrade --confirm
```

> [!CAUTION]
> The `--confirm` flag is required when running in production (`ENVIRONMENT=production`). This safety barrier prevents accidental schema alterations.

### 4.2 Verify Migration Status
```bash
python migrations/run_migrations.py status
```
All migrations should display `[APPLIED]`.

---

## 5. Reverse Proxy & SSL Configuration (Nginx)

Place Nginx in front of ExamProctor for TLS termination, HTTP/2 multiplexing, static asset caching, and WebSocket connection upgrade.

### Sample `/etc/nginx/sites-available/examproctor.conf`:
```nginx
upstream examproctor_backend {
    server 127.0.0.1:8000;
    keepalive 32;
}

server {
    listen 80;
    server_name exams.yourdomain.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name exams.yourdomain.com;

    ssl_certificate /etc/letsencrypt/live/exams.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/exams.yourdomain.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    # Security Headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    # WebSocket Proxy for Live Monitoring & Proctoring
    location /ws/ {
        proxy_pass http://examproctor_backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "Upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;
    }

    # REST API & Web Application
    location / {
        proxy_pass http://examproctor_backend;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_connect_timeout 10s;
        proxy_read_timeout 120s;
        client_max_body_size 50M;
    }
}
```

---

## 6. Initial Platform Bootstrapping

On fresh installations, seed the initial Platform Super Administrator account:
```bash
python scripts/seed_super_admin.py --email admin@yourdomain.com --password "ChangeMeOnFirstLogin#2026"
```
Or execute via the Admin API:
```bash
curl -X POST https://exams.yourdomain.com/api/v1/auth/register-initial-admin \
  -H "Content-Type: application/json" \
  -H "X-Bootstrap-Key: <BOOTSTRAP_SECRET_KEY>" \
  -d '{"name": "Master Super Admin", "email": "admin@yourdomain.com", "password": "SecurePassword123!"}'
```

---

## 7. Health Check & Observability Monitoring

ExamProctor exposes dedicated, non-blocking health check endpoints:

1. **Liveness Probe**:
   `GET /health`
   - Returns: `{"status": "ok", "environment": "production"}`
   - Use for: Kubernetes liveness / container restart decisions.

2. **Readiness Probe**:
   `GET /health/ready`
   - Returns: `{"status": "ready", "database": "healthy", "redis": "healthy", "circuit_breakers": "closed"}`
   - Use for: Load balancer traffic routing.

3. **Metrics & Access Logs**:
   Every response includes:
   - `X-Request-ID`: Distributed tracing identifier (UUID4)
   - `X-Process-Time`: Server processing time (e.g., `0.024s`)

---

## 8. Troubleshooting Guide

| Issue | Root Cause | Resolution |
| :--- | :--- | :--- |
| Container fails to start with `ValueError: SECRET_KEY must be overridden` | `ENVIRONMENT=production` set with default dev secret | Set a random 64-character secret in `.env` |
| `/health/ready` reports database `unhealthy` | Connection refused or invalid pool credentials | Verify `DATABASE_URL` host, port, credentials, and network connectivity |
| WebSockets disconnect after 60 seconds | Reverse proxy read timeout elapsed | Ensure `proxy_read_timeout 86400s;` is set in Nginx WebSocket block |
| Redis unavailable log warning | Redis offline or network blocked | The system automatically fails over to in-memory TTL caching. Restore Redis for cross-node caching. |
