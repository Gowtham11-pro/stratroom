# StratRoom Production Deployment Guide

## Prerequisites

- Docker & Docker Compose v2+
- PostgreSQL 16+ (if running DB externally)
- Python 3.11+ (for local dev)

---

## Quick Start (Docker)

```bash
# 1. Build and start
docker compose up -d --build

# 2. Verify
curl http://localhost:8001/health    # Liveness
curl http://localhost:8001/ready     # Readiness
curl http://localhost:8001/metrics   # Metrics

# 3. Access
# API docs: http://localhost:8001/docs
# Frontend: http://localhost:8001
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `JWT_SECRET` | YES | (auto-gen) | 64-char hex secret for JWT signing |
| `POSTGRES_PASSWORD` | YES | stratroom_pw | PostgreSQL password |
| `DATABASE_URL` | No | auto from POSTGRES_* | Full connection string |
| `CORS_ORIGINS` | No | localhost | Comma-separated allowed origins |
| `ENVIRONMENT` | No | production | `development` or `production` |
| `LOG_JSON_MODE` | No | true | JSON structured logs |
| `ENABLE_DOCS` | No | false | Enable Swagger/ReDoc at /docs |
| `RATE_LIMIT_PER_MINUTE` | No | 120 | Global rate limit per IP |
| `DB_POOL_SIZE` | No | 10 | AsyncPG connection pool size |
| `DB_MAX_OVERFLOW` | No | 20 | Max extra connections beyond pool |

---

## Database

SQL files in `db/` auto-execute via Docker init:

```
db/01_init.sql          # Core schema
db/02_migrate_org.py    # Organization support
db/03_migrate_tasks.sql # Task ownership
db/04_rbac.sql          # RBAC columns
db/05_seed_data.sql     # Demo data
db/06_init_enterprise.sql # Enterprise schema
db/07_seed_enterprise.sql # Enterprise seed data
db/08_phase_4.sql       # Phase 4 tables
db/09_phase_4.sql       # Phase 4 indexes
```

---

## Default Users

| Email | Password | Role | Org |
|-------|----------|------|-----|
| admin@stratroom.com | Admin@123 | admin | StratRoom (1) |
| admin@test.com | Admin@123 | member | StratRoom (1) |
| manager@stratroom.com | Admin@123 | manager | StratRoom (1) |
| member@stratroom.com | Admin@123 | member | StratRoom (1) |

---

## RBAC Hierarchy

| Role | Level | Permissions |
|------|-------|-------------|
| admin | 100 | Full CRUD on all org data, manage users |
| manager | 50 | View all org data, create + update own, no delete |
| member | 10 | View assigned data only, update own only |

---

## Health Endpoints

| Endpoint | Purpose | Expected Response |
|----------|---------|-------------------|
| `GET /health` | Liveness probe | `{"status": "ok"}` |
| `GET /ready` | Readiness probe | `{"status": "ready", "database": "ok"}` |
| `GET /metrics` | Basic metrics | AI counters, uptime, version |

---

## Container Operations

```bash
# Rebuild after code changes (no volume mounts)
docker compose up -d --build api

# View logs
docker logs stratroom_api --tail 50 -f

# Enter container
docker exec -it stratroom_api bash

# Check database
docker exec -it stratroom_db psql -U stratroom -d stratroom -c "\dt"
```

---

## Backup & Restore

```bash
# Database backup
docker compose exec db pg_dump -U stratroom stratroom > backup_$(date +%Y%m%d).sql

# Restore from backup
docker compose exec -T db psql -U stratroom -d stratroom < backup_20260720.sql
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

- [ ] `JWT_SECRET` set to strong 64-char hex
- [ ] `POSTGRES_PASSWORD` changed from default
- [ ] `CORS_ORIGINS` set to actual frontend domain(s)
- [ ] `ENVIRONMENT=production`
- [ ] `ENABLE_DOCS=false`
- [ ] Database migrations applied (01 through 09)
- [ ] Docker health checks passing
- [ ] SSL/TLS termination configured (via reverse proxy)
- [ ] Log aggregation configured
- [ ] `curl /health` returns 200
- [ ] `curl /ready` returns ready status
