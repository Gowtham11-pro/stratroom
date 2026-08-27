# System Architecture Blueprint & Multi-Agent Execution Strategy

**Role**: Principal System Architect, AI Engineering Lead, & Technical Product Manager  
**Project**: **StratRoom** (Enterprise Strategy, Risk Management & Balanced Scorecard Platform)  
**Target Environment**: Strict Local Development (`d:\project001\stratroom`) & Local Ports  

---

## 1. PROJECT DETAILS & TECH STACK OVERVIEW

| Layer | Technology / Framework | Port / Resource | Responsibility |
| :--- | :--- | :--- | :--- |
| **Frontend UI** | Single-File SPA (`31may_index.html`), Vanilla JS / CSS | Local Port `8088` (Apache / Container) | Executive Dashboard, Scorecard Matrix, Drill-Downs, AI Assistant Chat |
| **API Gateway / Core Backend** | Python 3.11, FastAPI, Uvicorn, PyMySQL | Local Port `8001` | REST Routing, JWT Security, RBAC Scoping, MySQL Compatibility Bridge |
| **AI Agent Processing Layer** | Strategy Agent Engine (`llm_providers.py`, `agents.py`, `tools.py`) | Integrated with FastAPI (`:8001`) | Context-aware LLM orchestration, MySQL metric retrieval, multi-provider fallbacks |
| **Database Layer** | MySQL 8.0 (`orgstructure` schema) | Local Port `3306` (or Tunnel `3307`) | Snapshot tables (`kpi_snapshot`), `scorecard_kpis`, `agent_conversations`, `ai_agent_runs` |

---

## 2. ARCHITECTURE VALIDATION & RISK AUDIT

### Identified Bottlenecks & Cross-Module Risk Points

1. **Single-File Frontend Concurrency Conflict**:
   - *Risk*: `frontend/31may_index.html` is a monolithic 1.5MB file containing all HTML, CSS, JavaScript state, and module interceptors.
   - *Mitigation*: **OpenCode** will have exclusive ownership of `31may_index.html`. AntiGravity and FreeBuffer must **never edit** `31may_index.html` directly during parallel sprints.

2. **In-Memory Rate Limiter Concurrency**:
   - *Risk*: The rate limiter in `backend/app/core/rate_limiter.py` uses per-process in-memory counters (`--workers 1` required). Spawning multiple API worker processes during local development will cause state fragmentation.
   - *Mitigation*: Keep local API running strictly on a single worker instance (`uvicorn app.main:app --port 8001 --workers 1`).

3. **Database Lock Contention & Token Validation**:
   - *Risk*: Concurrent queries to legacy tables (`score_card`) vs newer MySQL tables (`scorecard_kpis`, `agent_messages`) can trigger deadlocks if transactions are uncommitted.
   - *Mitigation*: Ensure explicit connection closing (`db.close()`) and parameter substitution (`%s` placeholders for MySQL).

---

## 3. DECOUPLED MODULE BREAKDOWN STRATEGY

To achieve **zero intersection and zero file locks** across terminal instances, we divide execution into 3 self-contained, isolated agent domains:

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                 STRATROOM WORKSPACE                                     │
├───────────────────────────────┬───────────────────────────────┬─────────────────────────┤
│    AGENCY 1: ANTIGRAVITY      │     AGENCY 2: FREEBUFFER      │   AGENCY 3: OPENCODE    │
│  (AI Agent Engine & Tools)    │   (FastAPI Backend & SQL)     │   (Frontend SPA UI)     │
├───────────────────────────────┼───────────────────────────────┼─────────────────────────┤
│ • backend/app/ai/             │ • backend/app/routers/        │ • frontend/31may_index  │
│ • backend/app/agents/         │ • backend/app/services/       │ • DOM State Management  │
│ • LLM Providers & Prompts     │ • backend/app/core/           │ • Event Listeners & UI  │
│ • Tool Registries             │ • MySQL DB Queries & Schema   │ • Chart.js Integrations │
└───────────────────────────────┴───────────────────────────────┴─────────────────────────┤
```

### Domain 1: AntiGravity (AI Agent Engine & Tooling Specialist)
- **Exclusive Directory Boundaries**: `backend/app/ai/`, `backend/app/agents/`
- **Core Tasks**:
  1. Enhance context-aware prompts in `llm_providers.py` to ingest real-time MySQL scorecard metrics.
  2. Implement tools in `scorecard_tools.py` and `risk_tools.py` for automated strategic recommendations.
  3. Manage AI conversation history in `agent_conversations` and `agent_messages`.

### Domain 2: FreeBuffer (FastAPI Router & Data Pipeline Specialist)
- **Exclusive Directory Boundaries**: `backend/app/routers/`, `backend/app/services/`, `backend/app/core/`
- **Core Tasks**:
  1. Maintain and optimize REST routers (`scorecards.py`, `dashboard.py`, `risks.py`, `tasks.py`).
  2. Ensure strict date parsing (`extract_date_bounds`, `parse_date_range_to_months`) across all snapshot queries.
  3. Enforce RBAC security in `security.py` and `deps.py` without modifying frontend templates.

### Domain 3: OpenCode (Frontend SPA & User Experience Specialist)
- **Exclusive Directory Boundaries**: `frontend/31may_index.html`
- **Core Tasks**:
  1. Manage client-side global state (`window.gperiodState`, `window.CurrentUser`).
  2. Maintain UI event listeners for global period pickers (`applyGlobalPeriodFilter`, `loadScorecards`).
  3. Optimize Chart.js time-series data rendering and drill-down views.

---

## 4. 2-HOUR EXECUTION BLUEPRINT & ENVIRONMENT CONFIGURATION

### Local Environment Setup & Port Allocations
- **API Dev Server**: `http://localhost:8001` (`uvicorn app.main:app --reload --port 8001`)
- **Apache Web Server Container**: `http://localhost:8088` (Proxies `/api` -> `:8001`)
- **MySQL Database Tunnel**: `localhost:3307` (Tunneled to `localhost:3306`)

---

### Step-by-Step 2-Hour Action Plan

#### Hour 1: Isolation & Domain Implementation
- **AntiGravity**: Refine LLM prompt builder to extract live snapshot metrics from system prompts (`llm_providers.py`).
- **FreeBuffer**: Ensure all router endpoints accept optional `date_range` query parameters and execute parameterized MySQL queries (`scorecards.py`).
- **OpenCode**: Optimize `openKPIDetailView()` to pass URL-encoded `date_range` query strings and re-render canvas charts (`31may_index.html`).

#### Hour 2: Integration, Automated Testing, & Deployment
- Run local unit tests: `python backend/tests/test_suite.py` (Must achieve 125/125 passed).
- Execute local container build and staging validation.

---

## 5. AGENT HANDOFF PROMPT TEMPLATES

Use the exact prompts below in separate terminal sessions to launch each agent:

### Prompt for Agent 1: AntiGravity (AI Agent Engine)
```markdown
ROLE: Senior AI Systems Engineer.
DOMAIN: AI Processing Layer & Agent Tooling (`backend/app/ai/`, `backend/app/agents/`).
TASK: Refine the AI Strategy Engine in `backend/app/ai/llm_providers.py` and `backend/app/agents/scorecard_tools.py`.
RULES:
1. Do NOT touch files outside `backend/app/ai/` or `backend/app/agents/`.
2. Do NOT modify `frontend/31may_index.html` or backend router files in `routers/`.
3. Parse the `--- CURRENT ORGANIZATION DATA ---` context string to extract live off-track KPIs, risk counts, and budget variances for context-aware responses.
```

### Prompt for Agent 2: FreeBuffer (FastAPI & Database Layer)
```markdown
ROLE: Backend Systems Architect & Database Specialist.
DOMAIN: FastAPI Backend (`backend/app/routers/`, `backend/app/services/`, `backend/app/core/`).
TASK: Verify date range filtering across all scorecard endpoints in `backend/app/routers/scorecards.py`.
RULES:
1. Do NOT modify files in `frontend/31may_index.html` or `backend/app/ai/`.
2. Ensure `extract_date_bounds(date_range)` parses both `MM/DD/YYYY` and `YYYY-MM-DD` string formats cleanly.
3. Use `%s` parameterized inputs for all `bridge._mysql()` queries to prevent SQL injection and lock contention.
```

### Prompt for Agent 3: OpenCode (Frontend SPA UI)
```markdown
ROLE: Principal Frontend Engineer & UX Architect.
DOMAIN: Single-File SPA (`frontend/31may_index.html`).
TASK: Optimize global date filtering and KPI detail modal state binding.
RULES:
1. Do NOT modify any Python code under `backend/`.
2. Expose global state cleanly on `window` (`window.gperiodState`, `window.CurrentUser`).
3. Ensure `applyGlobalPeriodFilter(evt)` invokes `loadScorecards()` and updates active Chart.js canvas elements cleanly without throwing console errors.
```
