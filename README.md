# StratRoom

AI-powered enterprise governance dashboard — full-stack SaaS application with role-based access control.

## Stack

- **Frontend:** Single-file HTML/CSS/JS SPA (`31may_index.html`, ~1.5MB, 23K+ lines) — 20 dashboard modules
- **Backend:** FastAPI (Python 3.11) + MySQL (via JavaBridge + pymysql)
- **Database:** MySQL only — PostgreSQL **removed July 2026**. All reads/writes go through `java_bridge._mysql()` (direct pymysql) or the Java service HTTP proxies
- **ML:** XGBoost risk/forecast pipeline (6 endpoints in `ml.py`)
- **Auth:** JWT (HS256). Passwordless `POST /api/v1/auth/login {email}` + password-verified `POST /auth/login` (bcrypt)
- **RBAC:** `require_role()` dependency; role resolved from app_role → designation → enterprise_role (`rbac.py`)
- **Infra:** Docker Compose (single `stratroom_api` container) + Apache reverse proxy `:8088` on the production host

## Quick Start

```bash
docker compose up -d --build
```

API: `http://localhost:8001` | Swagger docs: `http://localhost:8001/docs`

## Default Users (org_id=1)

| Email | Password | Role |
|-------|----------|------|
| admin@stratroom.com | changeme | admin |
| admin@test.com | changeme | member |

Login is **passwordless** on `/api/v1/auth/login` (email only). The SPA's `/auth/login` form also accepts these credentials with password `changeme` (verified in production).

## RBAC Permissions

| Action | Admin | Manager | Member |
|--------|-------|---------|--------|
| View all org data | ✅ | ✅ | ❌ (assigned only) |
| Create records | ✅ | ✅ | ❌ |
| Update own records | ✅ | ✅ | ✅ |
| Update any record | ✅ | ❌ | ❌ |
| Delete records | ✅ | ❌ | ❌ |

## API Endpoints

### Authentication
- `POST /api/v1/auth/login` — Passwordless login (email only), returns JWT
- `POST /auth/login` — Password-verified login (bcrypt against MySQL `users.hashed_password`)
- `POST /auth/register` — Create user + org
- `GET /auth/me` — Current user profile (resolves RBAC role + employee info)

### v1 Endpoints (22, `/api/v1/`)
- `POST /api/v1/chat/` — AI chat proxy
- `/api/v1/sessions/*` — Suggested tasks, session list
- `POST /api/v1/tasks/approve`, `approve-all`, `reject/{id}`, `GET modules` — Task workflow
- `GET /api/v1/dashboard/kpis`, `summary`, `compliance` — Dashboard
- `GET /api/v1/organization/structure` — Org tree + users + summary
- `POST /api/v1/ai-insights/signals`, `recommendations`, `analysis`, `tasks` — AI insights
- `GET /api/v1/incidents/`, `audit/`, `meetings/`, `initiatives/`, `risk/register` — Module reads
- `PUT /api/v1/audit/{id}` — Audit write

### Bare Routes (7, require member — MySQL)
- `GET /risks`, `GET /tasks`, `GET /scorecards` (→ `scorecard_kpis`), `GET /budgets`, `GET /org`, `GET /meetings`, `GET /dashboard/stats`

### Compat Routes (19, `/stratroom/*` — MySQL via JavaBridge)
- `riskList`, `scoreCardList`, `initiativesList`, `budgetsList`, `masterValue`, etc.

### Application Modules (CRUD via MySQL bridge)
- `GET/POST /tasks`, `GET/POST /scorecards`, `GET/POST /initiatives`, `GET/POST/PUT/DELETE /risks`, `GET/POST/PUT/DELETE /audit-findings`, `GET/POST/PUT/DELETE /complaints`

### AI & ML
- `POST /agents/chat` — AI agent chat (10 agents, tool calling)
- `POST /predict/risk-score` — XGBoost risk prediction
- `POST /ml/risk|revenue|attrition|incidents|budget|forecast` — ML endpoints
- `POST /ai/chat` — Direct LLM (openai/anthropic/google/deepseek/moonshot/together/mistral/xai/ollama)

### System
- `GET /health` — Liveness probe
- `GET /ready` — Readiness probe (DB + MySQL)
- `GET /metrics` — System metrics

## Train the ML Model

```bash
docker exec -it stratroom_api bash
cd /ml/scripts
python train.py
exit
```

## Project Structure

```
stratroom/
├── frontend/31may_index.html # Frontend monolith — deployed source of truth for the SPA
├── backend/
│   ├── app/
│   │   ├── core/             # Security, deps, RBAC, utils, config, db
│   │   ├── routers/          # 26 API routers (incl. compat.py + api_v1.py)
│   │   ├── services/java_bridge.py  # MySQL bridge (pymysql + HTTP proxies)
│   │   ├── ai/               # llm_providers, tool_registry, memory, guardrails, metrics
│   │   └── agents/           # AgentRunner, prompts, tools
│   └── requirements.txt
├── db/                       # Historical PostgreSQL migrations (01-09) — superseded by MySQL
├── docker-compose.yml
├── Dockerfile
├── deploy.py                 # Full deploy (41 files, container restart)
├── deploy_frontend.py        # SFTP to Apache doc root ONLY (cosmetic — not served)
├── log_tracker.py            # Snapshot/report tool for access-log 4xx/5xx tracking
├── docs/                     # Phase reports, architecture docs
├── README.md
├── STATUS.md
├── DEPLOYMENT_GUIDE.md
├── ARCHITECTURE_AUDIT.md
├── SECURITY_REPORT.md
└── AGENTS_CHANGELOG.md
```

## Notes

- **Frontend serving:** FastAPI `serve_frontend()` serves the container's `/app/frontend/31may_index.html`. The Apache doc root `/var/www/stratroom-ai/index.html` is **not** what's served (vhost does `ProxyPass / http://localhost:8001/`).
- **Frontend-only deploy:** copy `frontend/31may_index.html` → `/opt/stratroom-new/frontend/31may_index.html` on the host, then `docker cp` it into `stratroom_api:/app/frontend/31may_index.html`. No container restart needed.
- **Database:** MySQL (`orgstructure`, `host.docker.internal:3306`). PostgreSQL container was removed July 2026; `db.py` PG session factory remains but yields `None` gracefully.
- `JWT_SECRET` should be a static 64-char hex in production — auto-generation makes tokens die on restart.
- Rate limiter is in-memory per-process — must run with `--workers 1`.
- All queries are org_id-scoped. No cross-tenant data leaks.
- Container name: `stratroom_api`. Rebuild required after backend code changes.

## Verification

```bash
# Login (passwordless)
TOKEN=$(curl -s -X POST http://localhost:8001/api/v1/auth/login \
  -H "Content-Type: application/json" -d '{"email":"admin@stratroom.com"}' \
  | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Check scorecard KPI data (MySQL scorecard_kpis)
curl -s http://localhost:8001/scorecards -H "Authorization: Bearer $TOKEN"

# Check compat data (MySQL)
curl -s "http://localhost:8001/stratroom/riskList?pageId=3196" -H "Authorization: Bearer $TOKEN"
```
