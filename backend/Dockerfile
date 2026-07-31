# ── Stage 1: Build dependencies ──
FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends gcc && \
    rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Stage 2: Production image ──
FROM python:3.11-slim AS production

LABEL maintainer="StratRoom Team"
LABEL description="StratRoom Enterprise AI Governance Platform"

RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

RUN useradd --create-home --shell /bin/bash --uid 1000 appuser

WORKDIR /app

COPY backend/ ./backend/
COPY backend/ml/ ./backend/ml/
COPY backend/db/ ./backend/db/
COPY frontend/31may_index.html ./frontend/31may_index.html

RUN mkdir -p /app/backend/storage/documents && \
    chown -R appuser:appuser /app

USER appuser

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/backend \
    ENVIRONMENT=production \
    LOG_JSON_MODE=true \
    ENABLE_DOCS=false

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--limit-concurrency", "200", "--timeout-keep-alive", "30"]
