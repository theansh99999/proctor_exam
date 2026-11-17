# 🎓 ExamProctor — Enterprise Assessment & Proctoring Monolith

<p align="center">
  <strong>A high-concurrency, modular monolith examination platform with configurable AI-assisted proctoring, multi-tenant organization isolation, adaptive testing, and comprehensive analytics.</strong>
</p>

<p align="center">
  <a href="https://exam-proctor-cl7j.onrender.com"><img src="https://img.shields.io/badge/Live%20Demo-exam--proctor--cl7j.onrender.com-46E3B7?logo=render&logoColor=white" alt="Live Demo"></a>
  <img src="https://img.shields.io/badge/FastAPI-0.135-009688?logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/Python-3.10-3776AB?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/PostgreSQL-15+-336791?logo=postgresql&logoColor=white" alt="PostgreSQL">
  <img src="https://img.shields.io/badge/Redis-7+-DC382D?logo=redis&logoColor=white" alt="Redis">
  <img src="https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker&logoColor=white" alt="Docker">
  <img src="https://img.shields.io/badge/CI%2FCD-GitHub%20Actions-2088FF?logo=githubactions&logoColor=white" alt="GitHub Actions">
</p>

<p align="center">
  🌐 <strong>Live Website:</strong> <a href="https://exam-proctor-cl7j.onrender.com" target="_blank">https://exam-proctor-cl7j.onrender.com</a>
</p>

---

## 🌐 Live Deployment

The complete ExamProctor platform is deployed live on Render:
- **Production URL**: [https://exam-proctor-cl7j.onrender.com](https://exam-proctor-cl7j.onrender.com)
- **Liveness Probe**: [https://exam-proctor-cl7j.onrender.com/health](https://exam-proctor-cl7j.onrender.com/health)
- **Readiness Probe**: [https://exam-proctor-cl7j.onrender.com/health/ready](https://exam-proctor-cl7j.onrender.com/health/ready)

---

## 🏛️ System Architecture

ExamProctor is architected as a modular monolith adhering to Domain-Driven Design (DDD) principles. It combines high-throughput asynchronous request routing with robust data persistence, connection pooling, and multi-tenant isolation.

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

## 🚀 Key Platform Capabilities

1. **Role-Based Access Control & Multi-Tenancy**:
   - Strict organization-level data isolation across 4 roles: `Super Admin`, `Organization Admin`, `Examiner`, and `Candidate`.
   - Immutable audit logging for security governance and traceability.

2. **Unified Assessment Engine**:
   - Six supported question types: Single-choice MCQ, Multi-select MCQ, True/False, Short Answer, Descriptive (with examiner manual grading), and Code Stubs.
   - Blueprint-driven automatic question assembly and reusable assessment templates.
   - Item Response Theory (IRT) adaptive testing engine with dynamic difficulty adjustment.
   - Deterministic option and question shuffling with sequential section-locking navigation.

3. **Configurable Proctoring & Integrity Monitoring**:
   - Configurable proctoring policies per assessment (webcam, microphone, face tracking, tab-switch detection).
   - Air-gapped integrity scoring: Proctoring violation flags **never alter academic marks directly**; suspicious attempts are routed to an examiner review queue with timestamped evidence.
   - Real-time examiner live-monitoring dashboard powered by WebSockets.

4. **Production Hardening & Operational Resilience**:
   - Connection pooling (`QueuePool` with `pool_pre_ping=True` and connection recycling).
   - Redis distributed caching with transparent in-memory TTL dictionary fallback.
   - Comprehensive security headers (HSTS, CSP, X-Frame-Options: SAMEORIGIN) and SlowAPI rate limiting.
   - Distributed request tracing (`X-Request-ID`, `X-Process-Time`) and health probes (`/health`, `/health/ready`).
   - Automated cryptographic database backup and restoration pipeline (`SHA-256` verification).

---

## 📂 Repository Structure

```
.
├── core/                   # Centralized configuration, RBAC, cache, security headers, observability
├── modules/                # Domain-Driven Modules
│   ├── admin/              # Super admin governance, audit logging, system settings
│   ├── analytics/          # Cohort statistics, examiner dashboards, candidate performance
│   ├── assessments/        # Blueprints, templates, sections, adaptive engine, attempt policies
│   ├── background/         # Standalone background worker & scheduled jobs
│   ├── evaluation/         # Grading engine, manual scoring queue, result release gating
│   ├── integrations/       # Outbound sync framework (ServiceNow, LLM question generator)
│   ├── notifications/      # Multi-channel notification center (in-app, SMTP)
│   ├── organizations/      # Multi-tenant isolation & organization administration
│   ├── proctoring/          # Configurable proctoring policies, violation ingestion, live WS
│   ├── questions/          # Central question bank & 6 question types
│   └── users/              # User administration & role management
├── migrations/             # Sequential migration runner & Phase 1–11 schema migrations
├── routers/                # Web application routes (admin, auth, student, teacher, websocket)
├── templates/              # Jinja2 frontend views (admin, auth, student, teacher, notifications)
├── scripts/                # Database backup, restore, and load testing scripts
├── docs/                   # Complete operational, deployment, and security documentation
├── testing/                # Automated regression, integration, and E2E acceptance test suite
├── .github/workflows/      # 5-stage GitHub Actions CI/CD automation pipeline
├── docker-compose.yml      # Multi-container orchestration stack (db, redis, web, worker)
├── Dockerfile              # Hardened rootless multi-stage production container
├── .env.example            # Development configuration template
├── .env.production.example # Production configuration template
└── requirements.txt        # Pinned Python package dependencies
```

---

## 🛠️ Quick Start & Installation

### Prerequisites
- Python 3.10+
- PostgreSQL 15+
- Redis 7+ (Optional; in-memory fallback included)

### 1. Clone & Setup Environment
```bash
git clone https://github.com/theansh99999/proctor_exam.git
cd proctor_exam

# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: .\venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Environment Variables
```bash
cp .env.example .env
```
Update `.env` with your PostgreSQL database URL, secret key, and optional SMTP credentials. Refer to [`docs/ENVIRONMENT_VARIABLES.md`](docs/ENVIRONMENT_VARIABLES.md) for full configuration specifications.

### 3. Run Database Migrations
ExamProctor includes an ordered migration runner with status inspection:
```bash
# Check current migration status
python migrations/run_migrations.py status

# Apply all migrations
python migrations/run_migrations.py upgrade
```

### 4. Start the Application
```bash
# Start Web Server
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# In a separate terminal, start the Background Worker (optional for background tasks)
python worker.py
```
Visit `http://localhost:8000` to access the platform.

---

## 🐳 Docker Deployment

To launch the full production-like stack including PostgreSQL, Redis, FastAPI, and Background Worker:
```bash
# Configure production variables
cp .env.production.example .env

# Build and start services
docker compose up -d --build

# Run migrations inside the container
docker compose exec web python migrations/run_migrations.py upgrade --confirm
```

---

## 🧪 Running the Test Suite

The repository includes a comprehensive 192-test test harness covering all domain modules, RBAC boundaries, staging migrations, and full lifecycle end-to-end acceptance:

```bash
# Run the complete test suite
python -m unittest discover -s testing -p "test_*.py"

# Run the Phase 12 End-to-End Acceptance Scenario
python -m unittest testing/test_phase12_e2e_acceptance.py
```

---

## 📖 Operational Documentation

Comprehensive guides are provided in the [`docs/`](docs/) directory:
- [`docs/PRODUCTION_DEPLOYMENT.md`](docs/PRODUCTION_DEPLOYMENT.md): Deployment architectures, Nginx reverse proxy, and bootstrapping.
- [`docs/SECURITY_CHECKLIST.md`](docs/SECURITY_CHECKLIST.md): Defense-in-depth security checklist, CORS, CSP, and RBAC matrix.
- [`docs/DISASTER_RECOVERY.md`](docs/DISASTER_RECOVERY.md): RPO/RTO metrics, automated backups, and recovery drills.
- [`docs/ENVIRONMENT_VARIABLES.md`](docs/ENVIRONMENT_VARIABLES.md): Complete variable dictionary with descriptions and defaults.
- [`docs/OPERATIONS_RUNBOOK.md`](docs/OPERATIONS_RUNBOOK.md): SRE incident response playbooks, metrics, and log tracing.

---

## 🛡️ License

This project is licensed under the MIT License.
