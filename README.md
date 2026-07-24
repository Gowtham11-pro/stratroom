# StratRoom

AI-powered enterprise governance dashboard — full-stack SaaS application with role-based access control.

## Stack

- **Frontend:** HTML/CSS/JS monolith (`31may_index.html`, ~23K lines) — 20+ dashboard modules
- **Backend:** FastAPI + async SQLAlchemy + PostgreSQL (asyncpg)
- **ML:** XGBoost risk-scoring pipeline
- **Auth:** JWT (HS256, bcrypt-hashed passwords)
- **RBAC:** 3-tier role hierarchy — admin → manager → member
- **Infra:** Docker Compose

## Quick Start

```bash
docker compose up -d --build
```

API: `http://localhost:8001` | Swagger docs: `http://localhost:8001/docs`

## Default Users (org_id=1)

| Email | Password | Role |
|-------|----------|------|
| admin@stratroom.com | Admin@123 | admin |
| admin@test.com | Admin@123 | member |
| manager@stratroom.com | Admin@123 | manager |
| member@stratroom.com | Admin@123 | member |

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
- `POST /auth/login` — Login, returns JWT
- `POST /auth/register` — Create user + org
- `GET /auth/me` — Current user profile

### Dashboard
- `GET /dashboard/stats` — Org-scoped dashboard stats

### Application Modules (CRUD)
- `GET/POST /tasks` — Task management
- `GET/POST /scorecards` — Strategy scorecards
- `GET/POST /initiatives` — Strategic initiatives
- `GET/POST/PUT/DELETE /risks` — Risk register
- `GET/POST/PUT/DELETE /audit-findings` — Audit findings
- `GET/POST/PUT/DELETE /complaints` — Complaints

### Read-Only Modules (Enterprise Data)
- `GET /incidents` — Incident reports
- `GET /budget` — Budget lines
- `GET /meetings` — Meetings
- `GET /compliance` — Compliance obligations
- `GET /swot` — SWOT analysis
- `GET /pestel` — PESTEL analysis
- `GET /documents` — Document registry

### AI & ML
- `POST /agents/chat` — AI agent chat
- `POST /predict/risk-score` — XGBoost risk prediction
- `POST /ml/forecast` — Time-series forecasting

### System
- `GET /health` — Liveness probe
- `GET /ready` — Readiness probe
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
├── 31may_index.html          # Frontend monolith
├── backend/
│   ├── app/
│   │   ├── core/             # Security, deps, RBAC, utils
│   │   ├── routers/          # 20 API routers
│   │   ├── ai/               # AI agent modules
│   │   └── agents/           # Task tools, agent runner
│   └── requirements.txt
├── db/                       # SQL migrations (01-09)
├── docker-compose.yml
├── Dockerfile
├── docs/                     # Phase reports, architecture docs
├── README.md
├── DEPLOYMENT_GUIDE.md
├── ARCHITECTURE_AUDIT.md
└── SECURITY_REPORT.md
```

## Notes

- `db/01_init.sql` auto-runs on first Postgres start. Migrations `02-09` run in order.
- `JWT_SECRET` is ephemeral — regenerated on each container start.
- All queries are org_id-scoped. No cross-tenant data leaks.
- Container name: `stratroom_api`. Rebuild required after code changes.
