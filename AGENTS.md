# StratRoom — AGENTS.md

## Quick Start
```powershell
# Tunnels to production (bind 0.0.0.0, required for Docker Desktop host.docker.internal)
plink -ssh -P 55004 -l root -pw "%SSH_PASS%" -L 0.0.0.0:3307:localhost:3306 -N 103.191.132.36

docker compose up -d --build           # Full stack (no PostgreSQL needed)
python backend/tests/test_suite.py     # Offline tests (no DB)
$env:SSH_PASS='password'; python deploy.py   # Deploy to production
```

## Production
- **URL**: http://103.191.132.36:8088 (also http://demo.stratroom.io:8088)
- **Auth**: Passwordless — `POST /api/v1/auth/login {"email":"admin@stratroom.com"}` → JWT
- **Login test users**: `admin@stratroom.com`, `admin@test.com` (passwordless)
- **JWT_SECRET**: Must be 64-char hex; auto-generated if unset → tokens die on restart
- **Rate limiter**: In-memory per-process (`--workers 1` required, breaks with >1 worker)
- **Database**: MySQL only (PostgreSQL removed July 2026)

## Architecture
```
[Apache :8088] serves 31may_index.html
       │ ProxyPass / → localhost:8001
       ▼
[FastAPI :8001] — two route layers:
   │
   ├── /stratroom/* (compat) → JavaBridge → MySQL (legacy routes)
   │
   └── Bare routes like /risks, /tasks, /scorecards → JavaBridge → MySQL
       (or direct pymysql queries via bridge._mysql())
```

**All data reads and writes go through MySQL.** PostgreSQL was fully removed in July 2026. The `scorecard_kpis` table replaced the PG `scorecards` table. The `ai_agent_runs`, `ai_memory`, `agent_conversations`, and `agent_messages` tables also run on MySQL.

## Deploy
- Only `deploy.py` is used — copies 41 files, restarts container, exits on error.
- **Frontend-only change** (31may_index.html): no backend rebuild needed, but the Apache doc root (`/var/www/stratroom-ai/index.html`) is **NOT what's served** — the vhost has `ProxyPass / http://localhost:8001/`, so FastAPI's `serve_frontend()` (`/app/backend/app/main.py:212`) serves the **container's** `/app/frontend/31may_index.html`. Correct deploy: `cp index.html /opt/stratroom-new/frontend/31may_index.html` (build source) then `docker cp` it into `stratroom_api:/app/frontend/31may_index.html` + chown appuser.
- All 15 SSH scripts read password from `os.environ["SSH_PASS"]` — never hardcode.

## Key Files
| File | What |
|------|------|
| `frontend/31may_index.html` | 1.5MB single-file SPA (served by Apache, NOT the React bundle) |
| `backend/app/main.py` | FastAPI entrypoint + route registration |
| `backend/app/routers/compat.py` | 19 `/stratroom/*` MySQL compat routes |
| `backend/app/services/java_bridge.py` | MySQL bridge (direct pymysql + HTTP proxy to Java) |
| `backend/app/core/security.py` | JWT + password hashing |
| `backend/app/core/deps.py` | `require_role("member")`, `get_current_user` |
| `backend/app/core/config.py` | All settings (MySQL, Java service URLs) |
| `backend/app/core/db.py` | PostgreSQL session (gracefully degraded — yields None when PG is down) |
| `backend/app/core/rate_limiter.py` | In-memory, per-process, `--workers 1` required |
| `deploy.py` | SSH + paramiko deployment script |

## Frontend Data Flow (critical nuance)
The SPA has **two population mechanisms** for each module:
1. **`load*Data()`** → `apiGet('/stratroom/xxx')` → MySQL compat (legacy)
2. **`hydrate*Page()`** → `load*FromBackend()` → `authFetch('/xxx')` → bare route (MySQL)

An **interceptor** (line ~20794-20799) blocks mechanism #1 when authenticated for these modules: risk, incidents, scorecard, budget, tasks, meetings, audit, complaints, compliance, swot, pestel, projects, org. So the hydrate functions always win for logged-in users.
**Two legacy paths BYPASS the interceptor** (they call `apiGet`/`apiRequest` directly, not `loadModuleData`): `budgetAPI.init()` (line ~13129, fires at script parse) and `refreshDashboardKPIs()` (line ~16825, fires 300ms after login). Both are gated with `window.isTokenValid()` + `!API_TOKEN` checks — do not remove those gates or expired-token 401/403 walls return.

## Security (preserve everywhere)
- `text("...AND org_id = :oid...")` — never f-strings for SQL (PG routes only; MySQL uses `%s` placeholders).
- Single-query ownership: `UPDATE ... WHERE id=:id AND org_id=:oid AND user_id=:uid`.
- Path traversal guard: `_validate_storage_path()` with `os.path.realpath()`.
- AI provider URLs hardcoded (no SSRF).
- Rate limiting: 120 req/min global, 30 req/min AI.

## Gotchas
- **Frontend is a single 1.5MB file** (`31may_index.html`). No build step. Edit directly.
- `tasks` and `initiatives` use `created_at` not `updated_at`.
- `org_members` table is empty — use `employee_details.parent_emp_id` for tree.
- Dashboard summary returns 0 for any bridge data that fails (no crash).
- MySQL `score_card` has 108 scorecard-definition rows (names/weights/dates). MySQL `scorecard_kpis` has 408 KPI-value rows (target/actual/status per KPI). **Different data**, not duplicates.
- Navigate hook chain has ~14 wrappers. Adding a new wrapper: save `_prevNav = window.navigate`, set `window.navigate = function(id) { _prevNav(id); /* your code */ }`.
- Compat routes (`/stratroom/*`) require JWT auth via `require_role("member")` — unauthenticated requests get 401, not fallback data.
- Container PYTHONPATH = `/app/backend` — imports use `from app.main import app`.
- PostgreSQL container was removed in July 2026. The `db.py` module still has a PG session factory for backward compatibility but gracefully yields `None` if PG is unavailable.
- `scorecards/{id}` (with ID) goes to MySQL `score_card`; `/scorecards` (bare) goes to MySQL `scorecard_kpis`.
- SWOT/PESTEL: GET reads MySQL, POST/DELETE writes MySQL. Projects: GET reads MySQL, CRUD writes MySQL.

## Verification
```powershell
# Login
$token = (curl.exe -s -m 10 -X POST http://103.191.132.36:8088/api/v1/auth/login
  -H "Content-Type: application/json"
  -d '{\"email\":\"admin@stratroom.com\"}' | ConvertFrom-Json).access_token

# Check scorecard data (MySQL scorecard_kpis)
curl.exe -s -m 10 http://103.191.132.36:8088/scorecards
  -H "Authorization: Bearer $token" | python -c "import sys,json; d=json.load(sys.stdin); print(len(d['scorecards']))"

# Check compat data (MySQL)
curl.exe -s -m 10 http://103.191.132.36:8088/stratroom/riskList?pageId=3196
  -H "Authorization: Bearer $token" | python -c "import sys,json; d=json.load(sys.stdin); print(len(d['risks']))"
```
