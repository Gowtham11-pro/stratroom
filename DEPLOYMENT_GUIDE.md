# StratRoom Production Deployment Guide

## Prerequisites

- Docker & Docker Compose v2+ (for the `stratroom_api` container)
- Python 3.11+ (for local dev and the deploy scripts)
- SSH access to the production host (port 55004) + `plink`/`ssh` tunnel to MySQL (port 3307 → host 3306)
- Production host: `103.191.132.36` — Apache `:8088` → FastAPI `localhost:8001` (container `stratroom_api`)

> **July 2026:** PostgreSQL was fully removed. The only datastore is **MySQL** (`orgstructure`),
> reached from the container via `host.docker.internal:3306` (tunneled to host 3306). No `stratroom_db`
> container exists anymore.

---

## Quick Start (Docker — local dev)

```bash
# 1. Build and start
docker compose up -d --build

# 2. Verify
curl http://localhost:8001/health    # Liveness
curl http://localhost:8001/ready     # Readiness (database + mysql)
curl http://localhost:8001/metrics   # Metrics

# 3. Access
# API docs: http://localhost:8001/docs
# Frontend: http://localhost:8001
```

**Production:** the app is already deployed. Use the deploy scripts below, not `docker compose`.

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `JWT_SECRET` | YES | (auto-gen) | **Static 64-char hex** — tokens survive restarts. Auto-gen = tokens die on restart |
| `MYSQL_HOST` | YES | host.docker.internal | MySQL host (tunnel to prod 3306) |
| `MYSQL_PORT` | Yes | 3306 | MySQL port (prod tunnel maps 3307→3306) |
| `MYSQL_USER` | Yes | root | MySQL user |
| `MYSQL_PASSWORD` | Yes | Admin#123 | MySQL password (set in prod!) |
| `MYSQL_DATABASE` | Yes | orgstructure | MySQL schema — single data store |
| `JAVA_*_URL` | Yes | host.docker.internal:9010/9040/9050/9060 | Java service bridge endpoints |
| `CORS_ORIGINS` | No | localhost | Comma-separated allowed origins |
| `ENVIRONMENT` | No | production | `development` or `production` |
| `LOG_JSON_MODE` | No | true | JSON structured logs |
| `ENABLE_DOCS` | No | false | Enable Swagger/ReDoc at /docs |
| `RATE_LIMIT_PER_MINUTE` | No | 120 | Global rate limit per IP |
| `RATE_LIMIT_AI_PER_MINUTE` | No | 30 | AI endpoints limit |

> `core/db.py` still has PostgreSQL pool settings (`DATABASE_URL`, `DB_POOL_*`) for backward
> compatibility, but the PG session factory yields `None` when PG is unavailable — all real I/O is MySQL.

---

## Database

**MySQL** (`orgstructure`) is the single data store. Key tables:

- `users`, `employee_details`, `user_role_management` — auth + org/RBAC
- `tasks`, `risks`, `incidents`, `audit_findings`, `meetings`, `initiatives` — application data
- `score_card` (108 definitions) + `scorecard_kpis` (408 KPI values) — scorecards
- `agent_conversations`, `agent_messages`, `ai_agent_runs`, `ai_memory` — AI layer
- JavaBridge legacy tables: `risk_details`, `score_card`, `budget_detail`, `compliance_details`, etc.

The `db/` SQL files (01-09) are **historical PostgreSQL migrations** — superseded by MySQL. Schema is
managed in MySQL directly.

---

## Default Users

| Email | Password | Role | Org |
|-------|----------|------|-----|
| admin@stratroom.com | changeme | admin | StratRoom (1) |
| admin@test.com | changeme | member | StratRoom (1) |

Login is **passwordless** on `/api/v1/auth/login` (email only). The SPA login form calls `/auth/login`
with these email/password pairs (bcrypt-verified against MySQL `users.hashed_password`).

---

## RBAC Hierarchy

| Role | Level | Permissions |
|------|-------|-------------|
| admin | 100 | Full CRUD on all org data, manage users |
| manager | 50 | View all org data, create + update own, no delete |
| member | 10 | View assigned data only, update own only |

Role is resolved by `resolve_rbac_role()` in priority order: app_role → designation → enterprise_role.

---

## Health Endpoints

| Endpoint | Purpose | Expected Response |
|----------|---------|-------------------|
| `GET /health` | Liveness probe | `{"status": "ok"}` |
| `GET /ready` | Readiness probe | `{"status": "ready", "database": "ok", "mysql": "ok"}` |
| `GET /metrics` | Basic metrics | AI counters, uptime, version |

---

## Production Deployment

### SSH setup
```powershell
$env:SSH_PASS = "..."   # all 15 SSH scripts read this env var — never hardcode
```

### 1. Backend deploy (`deploy.py`)
Copies 41 files to the container, restarts it, exits on error:
```powershell
python deploy.py
```

### 2. Frontend deploy (docker cp — the doc root is NOT served)
The Apache vhost does `ProxyPass / http://localhost:8001/`, so FastAPI's `serve_frontend()`
(`/app/backend/app/main.py:212`) serves the **container's** `/app/frontend/31may_index.html`:
```powershell
# a) SFTP/copy local frontend/31may_index.html → host /opt/stratroom-new/frontend/31may_index.html
# b) Copy into the running container
docker cp /opt/stratroom-new/frontend/31may_index.html stratroom_api:/app/frontend/31may_index.html
```
No container restart needed — the live page updates immediately. (`deploy_frontend.py` only SFTPs to the
Apache doc root — cosmetic, not served.)

### 3. Verify
```powershell
$token = (curl.exe -s -m 10 -X POST http://103.191.132.36:8088/api/v1/auth/login `
  -H "Content-Type: application/json" -d '{"email":"admin@stratroom.com"}' | ConvertFrom-Json).access_token
curl.exe -s -m 10 http://103.191.132.36:8088/scorecards -H "Authorization: Bearer $token"
curl.exe -s -m 10 "http://103.191.132.36:8088/stratroom/riskList?pageId=3196" -H "Authorization: Bearer $token"
```

---

## Container Operations

```bash
# Rebuild after backend code changes (no volume mounts)
docker compose up -d --build api

# View logs (JSON access logs — grep for 4xx/5xx)
docker logs stratroom_api --tail 50 -f

# Enter container
docker exec -it stratroom_api bash

# Container must run with --workers 1 (in-memory rate limiter)
```

---

## Backup & Restore

The datastore is MySQL on the host (reached via tunnel `plink -L 0.0.0.0:3307:localhost:3306`):

```bash
# MySQL backup (from host, via tunnel)
mysqldump -h 127.0.0.1 -P 3307 -u root -p orgstructure > backup_$(date +%Y%m%d).sql

# Restore from backup
mysql -h 127.0.0.1 -P 3307 -u root -p orgstructure < backup_20260720.sql
```

---

## Rollback Guide

```bash
# 1. Stop current version
docker compose down

# 2. Revert to previous commit
git checkout <previous-commit-hash>

# 3. Rebuild and restart
docker compose up -d --build
```

---

## Production Checklist

- [ ] `JWT_SECRET` set to a strong **static** 64-char hex (else tokens die on restart)
- [ ] `MYSQL_PASSWORD` is not the default
- [ ] `CORS_ORIGINS` set to actual frontend domain(s)
- [ ] `ENVIRONMENT=production`
- [ ] `ENABLE_DOCS=false`
- [ ] Container runs `--workers 1` (in-memory rate limiter)
- [ ] MySQL reachable from container via `host.docker.internal:3306` (tunnel up)
- [ ] Docker health checks passing
- [ ] Frontend updated via `docker cp` into `stratroom_api:/app/frontend/31may_index.html`
- [ ] SSL/TLS termination configured (via reverse proxy)
- [ ] Log aggregation configured
- [ ] `curl /health` returns 200
- [ ] `curl /ready` returns ready status
