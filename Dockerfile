# =============================================================================
# ExamProctor Production Dockerfile
# Python 3.10-slim Multi-Stage Minimal Production Image
# =============================================================================

FROM python:3.10-slim AS builder

WORKDIR /app

# Install build tools for C extensions (e.g. greenlet, bcrypt, psycopg2)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt


# ── Production Runtime Image ──────────────────────────────────────────────────
FROM python:3.10-slim AS runner

WORKDIR /app

# Install runtime dependencies only (curl for healthcheck, libpq5 for PostgreSQL)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create dedicated non-root user and group
RUN groupadd -g 10001 appgroup && \
    useradd -u 10001 -g appgroup -s /bin/bash -m appuser

# Copy installed Python packages from builder stage
COPY --from=builder /root/.local /home/appuser/.local
ENV PATH=/home/appuser/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV ENVIRONMENT=production

# Copy application code with non-root ownership
COPY --chown=appuser:appgroup . /app

# Switch to non-root user
USER appuser

# Container Healthcheck (Liveness probe)
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:10000/health || exit 1

EXPOSE 10000

# Production ASGI server execution with graceful shutdown
CMD ["gunicorn", "main:app", \
     "-w", "4", \
     "-k", "uvicorn.workers.UvicornWorker", \
     "-b", "0.0.0.0:10000", \
     "--timeout", "120", \
     "--graceful-timeout", "30", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
