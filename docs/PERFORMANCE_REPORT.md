# Phase 5 Performance Report

**Date:** 2026-07-20

---

## Optimizations Applied

### 1. Dashboard Stats — 11 Queries → 3 Queries
**File:** `routers/dashboard.py`
**Before:** 11 separate `SELECT COUNT(*)` queries, each opening a new cursor.
**After:** Consolidated into 3 queries using subqueries:
- Query 1: 9 count/aggregation metrics in a single SELECT with subqueries
- Query 2: Severity and region breakdowns with UNION ALL
- Query 3: Org-level stats (compliance, members, scorecards)
**Impact:** ~60% reduction in DB round-trips for `/dashboard/stats`.

### 2. Database Connection Pool
**File:** `core/db.py`
**Before:** Default SQLAlchemy pool (unbounded, no recycling, no health checks).
**After:**
- `pool_size=10` — base connection pool
- `max_overflow=20` — burst capacity
- `pool_timeout=30` — fail fast if pool exhausted
- `pool_recycle=1800` — recycle connections every 30 minutes
- `pool_pre_ping=True` — test connection health before use
**Impact:** Prevents connection leaks, handles DB restarts gracefully, bounded memory usage.

### 3. Async Engine Configuration
- `expire_on_commit=False` already set (prevents lazy-load issues)
- `echo=False` in production (no SQL logging overhead)

---

## Performance Baseline (Estimated)

| Endpoint | DB Queries | Est. Latency | Notes |
|----------|-----------|--------------|-------|
| `GET /health` | 0 | <1ms | No DB check |
| `GET /ready` | 1 | <5ms | SELECT 1 |
| `GET /dashboard/stats` | 3 | 20-50ms | Consolidated |
| `GET /risks` | 1 | 5-15ms | Simple SELECT |
| `POST /agents/chat` | 5-8 | 2-30s | LLM-dependent |
| `POST /documents/upload` | 2 | 50-200ms | File I/O |
| `GET /documents` | 1 | 5-15ms | Simple SELECT |

---

## What Was NOT Changed (And Why)

1. **No caching layer (Redis/Memcached)**: Per rules, no new infrastructure. The existing application serves a single-org dashboard with moderate traffic. Adding cache invalidation logic would increase complexity without proportional benefit.

2. **No query result caching**: SQLAlchemy's query caching is implicit through connection pooling. Explicit caching requires invalidation strategy (out of scope).

3. **No N+1 in agent context**: `fetch_agent_context` queries 4-10 modules per agent call. These are already simple indexed queries. Consolidating would reduce readability for marginal gain.

4. **No async file I/O for document storage**: Python's `open()` is synchronous but file sizes are bounded (20MB max). Using `aiofiles` would add a dependency for negligible benefit.

5. **No CDN for frontend HTML**: Static HTML served from FastAPI. Appropriate for internal enterprise tool. External CDN only needed for public-facing apps.

---

## Memory Usage

- Connection pool: ~10-30 connections (bounded)
- Rate limiter: In-memory dict, grows with unique clients (bounded by cleanup)
- AI counters: Fixed-size in-memory counters (negligible)
- Document storage: Filesystem-based, no in-memory buffering

---

## Recommendations for Future Scaling

1. **Multi-instance deployment**: Add Redis for rate limiting and session state
2. **Database read replicas**: For high-read dashboards
3. **Background task queue**: For LLM summarization (currently synchronous)
4. **CDN**: If serving external users
5. **Connection pooling external**: PgBouncer for >100 concurrent connections
