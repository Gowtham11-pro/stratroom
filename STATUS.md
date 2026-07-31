# StratRoom — Deployment Status

## Quick Links

| Service | URL | Status |
|---------|-----|--------|
| Production | http://103.191.132.36:8088 (also http://demo.stratroom.io:8088) | ✅ |
| FastAPI (direct) | http://localhost:8001/docs | ✅ |
| Health Check | http://localhost:8001/health | ✅ `{"status":"ok"}` |
| Readiness | http://localhost:8001/ready | ✅ `{"database":"ok","mysql":"ok"}` |
| v1 Endpoints | 22 routes in `api_v1.py` | ✅ All 200 OK |
| Total FastAPI routes | 116 | ✅ |
| Container `stratroom_api` | port 8001 | ✅ Up, healthy (`--workers 1`) |

## Working Credentials

| Email | Auth Method | Role | Notes |
|-------|-------------|------|-------|
| `admin@stratroom.com` | Passwordless (`POST /api/v1/auth/login {email}`) or password `changeme` (`POST /auth/login`) | admin | Verified via curl + headless browser |
| `admin@test.com` | Passwordless | member | Works via MySQL `users` |

Auth has **two login paths** (both live):
1. **Passwordless** — `POST /api/v1/auth/login {email}` → checks MySQL `users`, falls back to JavaBridge userList (v1 path, used for API/tooling).
2. **Password-verified** — `POST /auth/login {email,password}` → bcrypt check against MySQL `users.hashed_password` (this is what the SPA's login form calls).

## Database Record Counts (production, MySQL — verified)

PostgreSQL was **removed in July 2026**. All reads/writes go through MySQL (`orgstructure` via JavaBridge on `host.docker.internal:3306`).

| Table | Count | Note |
|-------|-------|------|
| `employee_details` (Active) | 46 | MySQL |
| `employee_details` (Total) | 65 | MySQL |
| `user_role_management` | 65 | MySQL (designation → RBAC mapping) |
| `users` | varies | MySQL (auth + hashed_password) |
| `score_card` | 108 | MySQL — scorecard *definitions* (names/weights/dates) |
| `scorecard_kpis` | 408 | MySQL — KPI *values* (target/actual/status). **Different data** from `score_card` |
| `tasks`, `incidents`, `risks`, `meetings`, `audit_findings`, `initiatives` | seed/user | MySQL |

## Verification Commands

```powershell
# === Health (through Apache proxy) ===
curl.exe http://103.191.132.36:8088/health

# === Login: passwordless v1 ===
$token = (curl.exe -s -m 10 -X POST http://103.191.132.36:8088/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@stratroom.com"}' | ConvertFrom-Json).access_token

# === Bare routes (MySQL via JavaBridge) ===
curl.exe -s -m 10 http://103.191.132.36:8088/scorecards -H "Authorization: Bearer $token"
curl.exe -s -m 10 http://103.191.132.36:8088/risks -H "Authorization: Bearer $token"

# === Compat routes (MySQL) ===
curl.exe -s -m 10 http://103.191.132.36:8088/stratroom/riskList?pageId=3196 -H "Authorization: Bearer $token"
curl.exe -s -m 10 http://103.191.132.36:8088/stratroom/scoreCardList -H "Authorization: Bearer $token"
```

## Current State

### What's Working
- All 22 `/api/v1/` endpoints — login, dashboard (kpis/summary/compliance), org structure, incidents, audit (read+write), meetings, initiatives, risks, sessions, tasks, AI insights
- 7 bare routes (require member): `/risks`, `/tasks`, `/scorecards`, `/budgets`, `/org`, `/meetings`, `/dashboard/stats`
- 19 `/stratroom/*` MySQL compat routes
- MySQL read/write routing — POST/PUT/DELETE via JavaBridge → direct MySQL INSERT/UPDATE/DELETE
- Apache proxy — `:8088` → `:8001` (ProxyPass `/` → localhost:8001, so **all** traffic incl. `/` is served by FastAPI)
- Deploy pipeline — `deploy.py` (41 files, container restart, exit on error); `deploy_frontend.py` (SFTP to doc root only — cosmetic); real frontend deploy = `docker cp` into `stratroom_api:/app/frontend/31may_index.html`
- **Session-expiry / stale-session fix** — deployed & verified (see below)
- Java services — running on host (ports 9010-9060), reachable via `host.docker.internal`

### Session-Expiry Fix (2026-07-31, deployed + verified)
- `isTokenValid()` (reads `sr_backend_token`), `handleSessionExpired()` (purges `sr_backend_token`/`stratroom_token`/`api-token` + user keys, shows `#login-screen`)
- 401 branches wired into `authFetch`/`apiGet`/`apiRequest`; presence-guards added to `initRiskPage`, `loadScorecards`, `fetchChartData`, `initOrg`, compat DCL, and the two interceptor bypasses `budgetAPI.init()` + `refreshDashboardKPIs()`
- Verified: headless-browser tests pass (expired-token load → login screen with **0 data requests**; fresh login → only `/`, `/auth/login`, `/auth/me`, `/dashboard/stats`; mid-session expiry → single 401 → graceful logout)
- `log_tracker.py` confirms pre-fix 401×89/403×18/404×54 bursts are gone (clean baseline, no error wall)

### Frontend Note
The Apache doc root (`/var/www/stratroom-ai/index.html`) is **NOT what's served**. FastAPI's `serve_frontend()` (`backend/app/main.py:212`) serves the **container's** `/app/frontend/31may_index.html` (the 1.5MB single-file SPA). The React SPA bundle (`assets/index-lurHdRTe.js`, 1.35MB) still exists on disk but is not served. Frontend-only changes need `docker cp` into the container (build source `/opt/stratroom-new/frontend/31may_index.html`).

### Key Gotchas
- `audit_findings` (MySQL) is the audit table, not `audit`
- `tasks` and `initiatives` use `created_at`, not `updated_at`
- Org tree uses `employee_details.parent_emp_id` (not `org_members` which is empty)
- Dashboard summary returns `0` for any bridge data that fails (no crash)
- `JWT_SECRET` must be a static 64-char hex in production; if unset it's auto-generated and **tokens die on restart**
- Rate limiter is in-memory per-process — breaks with `--workers > 1` (must run `--workers 1`)
- Compat routes (`/stratroom/*`) require JWT — unauthenticated requests get 401, not fallback data
