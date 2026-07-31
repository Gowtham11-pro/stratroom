# StratRoom — System Stabilization (July 2026)

> **Update (2026-07-31):** This changelog is historical. Since it was written, **PostgreSQL was fully
> removed** — every table below now lives in MySQL (`orgstructure`), and the AI tables
> (`ai_agent_runs`, `ai_memory`, `agent_conversations`, `agent_messages`) run on MySQL too. The Apache
> doc-root frontend copy described in §1 is **not what's served** — FastAPI's `serve_frontend()`
> serves the container's `/app/frontend/31may_index.html`. Deploy count is now **41 files** via
> `deploy.py`. A stale-session/401 fix (with headless-browser verification) was also shipped (see §7).

## What Changed

### 1. Frontend (served by FastAPI, not the doc root)
- `/var/www/stratroom-ai/index.html` was replaced with `31may_index.html` (1.5MB single-file app) — **cosmetic only**, the Apache doc root is NOT what's served
- FastAPI `serve_frontend()` (`backend/app/main.py:212`) serves the **container's** `/app/frontend/31may_index.html` (vhost has `ProxyPass / http://localhost:8001/`)
- React SPA bundle (`assets/index-lurHdRTe.js`) still exists on disk but is no longer served
- Frontend-only deploy: copy `frontend/31may_index.html` → host `/opt/stratroom-new/frontend/31may_index.html`, then `docker cp` into `stratroom_api:/app/frontend/31may_index.html`

### 2. API v1 Endpoints (22 total)
File: `backend/app/routers/api_v1.py`

| Method | Path | Type |
|--------|------|------|
| POST | `/api/v1/auth/login` | Passwordless JWT — accepts `{email}`, checks MySQL `users` then JavaBridge userList fallback |
| POST | `/api/v1/chat/` | Proxies to JavaBridge chat endpoint |
| GET | `/api/v1/sessions/suggested-tasks` | MySQL `tasks` table |
| GET | `/api/v1/sessions/` | MySQL `tasks` table filtered by emp_id |
| POST | `/api/v1/tasks/approve` | Updates task status → approved |
| POST | `/api/v1/tasks/approve-all` | Batch task approval |
| POST | `/api/v1/tasks/reject/{id}` | Updates task status → rejected |
| GET | `/api/v1/tasks/modules` | Distinct `agent` values from tasks |
| GET | `/api/v1/dashboard/kpis` | Scorecard counts (on_track, critical, at_risk) |
| GET | `/api/v1/dashboard/summary` | Aggregated data via JavaBridge (risks, incidents, scorecards, etc.) |
| GET | `/api/v1/dashboard/compliance` | Proxied to JavaBridge `/compliance` |
| GET | `/api/v1/organization/structure` | **Full response** — tree + 65 users + summary (via `get_org_full()`) |
| POST | `/api/v1/ai-insights/signals` | Proxied to JavaBridge AI endpoint |
| POST | `/api/v1/ai-insights/recommendations` | Proxied to JavaBridge AI endpoint |
| POST | `/api/v1/ai-insights/analysis` | Proxied to JavaBridge AI endpoint |
| POST | `/api/v1/ai-insights/tasks` | Proxied to JavaBridge AI endpoint |
| GET | `/api/v1/incidents/` | MySQL `incidents` table |
| GET | `/api/v1/audit/` | MySQL `audit_findings` table |
| PUT | `/api/v1/audit/{id}` | Updates `audit_findings` (allowed: title, severity, owner, due_date, status) |
| GET | `/api/v1/meetings/` | MySQL `meetings` table |
| GET | `/api/v1/initiatives/` | MySQL `initiatives` table |
| GET | `/api/v1/risk/register` | MySQL `risks` table |

### 3. Auth Flow
- `/api/v1/auth/login` accepts `{email}` only (no password)
- Looks up email in: (1) MySQL `users` table, (2) JavaBridge userList fallback
- Returns `{"access_token": "<jwt>", "token_type": "bearer"}`
- Frontend stores token as `sr_backend_token` (and legacy `stratroom_token`/`api-token`)
- The SPA login form calls `/auth/login` (email + password, bcrypt against MySQL `users.hashed_password`)
- All other endpoints use `Authorization: Bearer <token>`

### 4. JavaBridge Write Routing
File: `backend/app/services/java_bridge.py`
- Added `_route_db_post(path, data)` — INSERT routing for score_card, risk_details, task_details, initiatives_details, audit_management, meeting_management, universal_incident
- Added `_route_db_put(path, data)` — UPDATE routing for same tables
- Added `_route_db_delete(path)` — DELETE routing for same tables
- Added `_mysql_write(sql, params)` — sync MySQL write executor with auto-commit
- `post()`, `put()`, `delete()` methods now try MySQL routing first, then fall through to HTTP Java service

### 5. Database Unification (PostgreSQL removed)
- July 2026: PostgreSQL container removed; all application + enterprise data now on MySQL (`orgstructure`)
- `scorecards` (PG) → `score_card` (108 definitions) + `scorecard_kpis` (408 KPI values) on MySQL
- AI tables (`ai_agent_runs`, `ai_memory`, `agent_conversations`, `agent_messages`) moved to MySQL
- `core/db.py` keeps a PG session factory for backward compatibility but yields `None` when PG is unavailable
- `core/config.py` (JAVA_* env vars), `core/deps.py`, `core/security.py`, all router files updated accordingly

### 6. Deployment Pipeline
File: `deploy.py`
- 41 files synced instead of 3
- Frontend copied to build source `/opt/stratroom-new/frontend/31may_index.html` and `docker cp`'d into `stratroom_api:/app/frontend/31may_index.html` (the Apache doc-root copy is cosmetic — FastAPI serves the container file)
- Container restart enforced after deploy
- Exit on non-zero exit code (no silent failures)

### 7. Session-Expiry / Stale-Session Fix (2026-07-31)
File: `frontend/31may_index.html`
- `isTokenValid()` (×12) — validates `sr_backend_token` before firing data loads
- `handleSessionExpired()` (×5) — purges `sr_backend_token`/`stratroom_token`/`api-token` + user keys, shows `#login-screen`
- 401 branches (×12) wired into `authFetch`/`apiGet`/`apiRequest`
- `window.authFetch || fetch` fallback (×3)
- Presence-guards (×11) on `initRiskPage`, `loadScorecards`, `fetchChartData`, `initOrg`, compat DCL, etc.
- "no token = demo mode" ×1
- Interceptor-bypass gates: `budgetAPI.init()` + `refreshDashboardKPIs()` (both call `apiGet`/`apiRequest` directly)
- Verified: headless Chrome tests (expired-token load → 0 data requests → login screen; fresh login → 4 requests only; mid-session expiry → single 401 → graceful logout)

## Key Tables

**MySQL (single data store — PostgreSQL removed July 2026):**
`users`, `employee_details`, `user_role_management`, `organizations`, `tasks`, `incidents`, `audit_findings`, `meetings`, `initiatives`, `risks`, `score_card`, `scorecard_kpis`, `agent_conversations`, `agent_messages`, `ai_agent_runs`, `ai_memory`

**MySQL (JavaBridge legacy data, via `host.docker.internal:3306`):**
`employee_credentials`, `risk_details`, `task_details`, `initiatives_details`, `audit_management`, `meeting_management`, `universal_incident`, `budget_detail`, `compliance_details`, `swot_analysis`, `pestel_analysis`, `processenabler`, `project_planning`, `org_structure_details`

## Verification Commands

```bash
# Login
curl -s -X POST http://localhost:8001/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@stratroom.com"}'

# Authenticated read (any v1 endpoint)
TOKEN=$(curl -s ...)
curl -s http://localhost:8001/api/v1/dashboard/kpis \
  -H "Authorization: Bearer $TOKEN"

# Write
curl -s -X PUT http://localhost:8001/api/v1/audit/1 \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"status":"reviewed"}'

# Apache proxy
curl -s http://localhost:8088/api/v1/dashboard/kpis \
  -H "Authorization: Bearer $TOKEN"
```

## Gotchas
- `audit` table is `audit_findings` (MySQL), not `audit`
- `scorecards` (bare route) reads `scorecard_kpis`; `score_card` holds scorecard definitions — different data
- `tasks` uses `created_at` not `updated_at`
- `initiatives` uses `created_at` not `updated_at`
- Org queries use `employee_details` with `parent_emp_id` for tree (not `org_members` which is empty)
- Dashboard summary returns `0` for any bridge data that fails (no crash)
- Compat routes (`/stratroom/*`) require JWT — unauthenticated requests get 401, not fallback data
