# StratRoom — AGENTS.md

## Quick start
```powershell
docker compose up -d --build           # Full stack
python backend/tests/test_suite.py     # Offline tests (no DB)
```

## Key commands
| Command | Notes |
|---------|-------|
| `docker compose up -d --build` | Start everything. DB migrations auto-run on first start. |
| `docker compose up -d --build api` | Rebuild only API after code changes. |
| `python backend/tests/test_suite.py` | Offline mock test suite (128+ tests, no Docker needed). |
| `.\backend\tests\test_all.ps1` | Integration tests (requires running containers). |
| `docker compose exec db pg_dump -U stratroom stratroom > backup.sql` | DB backup. |
| ML train inside container: `cd /ml/scripts && python train_all.py` | Trains 5 models (risk, revenue, attrition, incidents, budget). |

## CI — `.github/workflows/ci.yml`
Runs on push to `main`/`develop`, PR to `main`:
1. `ruff check backend/app/ --select E,F,W --ignore E501,E401,E741,F841,F401`
2. `python backend/tests/test_suite.py`
3. `python -c "from app.main import app; print(f'Routes: {len(app.routes)}')"`
4. `docker build -f backend/Dockerfile .`
5. `pip-audit -r backend/requirements.txt`

## Architecture notes
- **Entrypoint:** `backend/app/main.py` — FastAPI app with middleware (rate limit, security headers, tracing).
- **No ORM models** — all DB queries use raw `text("...")` with bound params.
- **Every query scoped** by `org_id = :oid` and ownership `user_id = :uid`.
- **Compat router** (`routers/compat.py`) maps legacy frontend paths like `/stratroom/riskList/1`, `/stratroom/scoreCardList` to DB logic. Frontend calls these, not the `routers/*.py` endpoints directly.
- **Agent runner** (`agents/base.py`) uses `[TOOL_CALL:tool_name:args]` pattern parsed from LLM output.
- **5 XGBoost models** in `ml/models/`: risk, revenue, attrition, incidents, budget_variance. Train all with `train_all.py`.

## Security patterns (preserve everywhere)
- `text("...AND org_id = :oid...")` — never f-strings for SQL.
- Single-query ownership update: `UPDATE ... WHERE id=:id AND org_id=:oid AND user_id=:uid`.
- Path traversal guard: `_validate_storage_path()` with `os.path.realpath()` canonicalization.
- AI provider URLs hardcoded (no SSRF).
- Rate limiting: 120 req/min global, 30 req/min AI (in-memory, fail-open, not shared across workers).

## Gotchas
- **Password requirements:** ≥8 chars, must contain uppercase, lowercase, and digit (`security.py:21-31`).
- **JWT_SECRET** auto-generated if unset — tokens invalidated on restart. Set persistent 64-char hex for production.
- **Frontend** is a single 23K-line HTML file. Any UI change touches this one file.
- **No git repo** — `git init` before any commit work.
- **Rate limiter** is per-process. Breaks with `--workers > 1` — needs Redis.
- **ML inference** (`routers/ml.py`) adds `ml/scripts` to `sys.path` at module load time — don't move that import.
- **Default users** (org_id=1): `admin@stratroom.com` — password `changeme` (from seed SQL in `01_init.sql:239`). Also `admin@test.com` (member role).
- **Container PYTHONPATH** = `/app/backend`, so imports use `from app.main import app`, not `from backend.app.main`.
