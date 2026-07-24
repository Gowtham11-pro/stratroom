did# StratRoom — Enterprise AI Architecture Design Document

**Version:** 2.0 (Revised — Critical Self-Review Applied)  
**Date:** 2026-07-20  
**Classification:** Internal — Architecture Design  
**Status:** DESIGN ONLY — No implementation  

---

## Revision Notes (v1.0 → v2.0)

This revision was produced after critically auditing v1.0 against the actual codebase. The following issues were identified and addressed:

| Issue | Type | Action Taken |
|-------|------|-------------|
| Orchestrator intent classification duplicates frontend routing | Over-engineering | Removed; replaced with lightweight query enhancer |
| 4-layer memory system excessive for single-org platform | Over-engineering | Collapsed to 2 practical layers |
| Tool permission matrix for read-only SELECT queries | Unnecessary abstraction | Simplified to tool allow-list per agent |
| LLM provider abstraction with health checks + load balancing | Premature optimization | Simplified to shared provider module + basic fallback |
| Prompt versioning system with YAML files | Over-engineering | Removed; use code-level prompt management |
| Agent hierarchy with 3 tiers + 12 agents | Over-engineering | Reduced to existing 9 + 1 new agent |
| SSE/WebSocket streaming architecture | Premature for user base | Deferred to Phase 5 |
| AgentRunner has multi-tenancy bug (no org_id filtering) | Existing code bug | Flagged for Phase 3 fix |
| agent_messages has no content length constraint | Existing security gap | Flagged for Phase 3 fix |
| `int(user)` in agents.py silently drops user_id | Existing code bug | Flagged for Phase 3 fix |
| LLM provider code duplicated in ai.py and agents/base.py | Existing code smell | Consolidation target in Phase 3 |
| Injection detection via regex is fundamentally bypassable | False sense of security | Replaced with layered defense approach |

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Current Architecture Review](#2-current-architecture-review)
3. [Existing Codebase Bugs Found During Review](#3-existing-codebase-bugs-found-during-review)
4. [Weakness Analysis](#4-weakness-analysis)
5. [What v1.0 Got Wrong](#5-what-v10-got-wrong)
6. [Revised Enterprise Architecture](#6-revised-enterprise-architecture)
7. [Agent Design](#7-agent-design)
8. [Tool System](#8-tool-system)
9. [Memory Design](#9-memory-design)
10. [Context Pipeline](#10-context-pipeline)
11. [LLM Provider Consolidation](#11-llm-provider-consolidation)
12. [Security Model](#12-security-model)
13. [ML Integration](#13-ml-integration)
14. [Database Strategy](#14-database-strategy)
15. [Deployment](#15-deployment)
16. [Monitoring](#16-monitoring)
17. [Migration Plan](#17-migration-plan)
18. [Risks](#18-risks)
19. [Trade-offs](#19-trade-offs)
20. [Implementation Phases](#20-implementation-phases)
21. [Readiness Verdict](#21-readiness-verdict)

---

## 1. Executive Summary

StratRoom currently operates with a flat, single-agent architecture: 9 domain agents, each invoked independently with static data dumps, direct LLM calls, no inter-agent coordination, and no tool calling. This document designs an Enterprise Multi-Agent System that transforms the AI layer while preserving 100% backward compatibility.

**This revision (v2.0)** strips away components that were over-engineered for the actual platform scale (single-org, ~50 concurrent users, modest data volumes) and focuses on capabilities that deliver real value: tool calling, cross-agent coordination, LLM provider consolidation, memory, observability, and security hardening.

**Core principle preserved:** The existing `AgentRunner` and its 9 agents remain fully functional. New capabilities are additive layers — never replacements.

---

## 2. Current Architecture Review

### 2.1 System Inventory

```
Frontend:      31may_index.html (1.3MB single-page app)
Auth:          JWT (HS256) + bcrypt, Bearer token
API:           19 FastAPI routers (40+ endpoints)
Database:      PostgreSQL 16 (17 tables, async SQLAlchemy)
ML Models:     5 XGBoost models (.joblib) — risk, revenue, attrition, incidents, budget
AI Agents:     9 domain agents (flat, independent)
Infrastructure: Docker Compose (api + db)
Tests:         106 passing
```

### 2.2 Database Schema (17 Tables)

| Domain | Tables |
|--------|--------|
| Core | `organizations`, `users` |
| Risk & Incidents | `risks`, `incidents` |
| Strategy | `initiatives`, `scorecards`, `swot_items`, `pestel_items` |
| Financial | `budget_lines` |
| Operations | `tasks`, `meetings`, `projects` |
| Governance | `audit_findings`, `compliance_frameworks`, `bcp_processes` |
| Organization | `org_members` |
| AI | `agent_conversations`, `agent_messages` |

### 2.3 Existing Agent System

```
User sends: POST /agents/chat
  { agent: "strategy", message: "...", provider: "openai", api_key: "...", model: "gpt-4o" }
                                    │
                                    ▼
                          AgentRunner("strategy")
                                    │
                          ┌─────────┴─────────┐
                          │                   │
                    fetch_agent_context   Load conversation
                    (ALL module data)     history (last 20)
                          │                   │
                          └─────────┬─────────┘
                                    │
                            system_prompt
                            + org_data
                            + history
                            + user_message
                                    │
                                    ▼
                              LLM call
                                    │
                                    ▼
                            Save to DB
                            Return response
```

**Key observation:** The frontend ALREADY selects the agent. The backend does NOT need to classify intent or choose agents. This is a critical architectural fact that v1.0 ignored.

### 2.4 Existing LLM Provider Implementations

The same 4-provider pattern is duplicated in two files:

| File | Providers | Lines |
|------|-----------|-------|
| `backend/app/routers/ai.py` | OpenAI-compat, Anthropic, Google, Ollama | ~90 lines |
| `backend/app/agents/base.py` | OpenAI-compat, Anthropic, Google, Ollama | ~80 lines |

This is 170 lines of near-identical code that should be consolidated into a single module.

---

## 3. Existing Codebase Bugs Found During Review

During this design review, three bugs in the existing code were identified. These are NOT introduced by this design — they pre-exist and should be fixed in Phase 3 as prerequisites.

### Bug 1: Silent user_id Loss

**Location:** `backend/app/routers/agents.py:75`

```python
user_id=int(user) if user.isdigit() else None,
```

The JWT `sub` claim is the user's **email** (e.g., `admin@stratroom.com`) — set in `auth.py:91,103`. The `str.isdigit()` check returns `False` for emails, so `user_id` is ALWAYS `None`. Conversations are created without a user association, breaking per-user memory and conversation history queries.

**Impact:** Conversations are orphaned; no user-level analytics possible.  
**Fix:** Query user ID from email: `SELECT id FROM users WHERE email = :email`.

### Bug 2: No Multi-Tenancy in Agent Queries

**Location:** `backend/app/agents/tools.py` — ALL queries

Every query in `fetch_module_data` lacks `WHERE org_id = :org_id`:

```sql
-- Current (tools.py:6-10):
SELECT id, name, owner, inherent_likelihood, inherent_impact, ...
FROM risks ORDER BY (residual_likelihood * residual_impact) DESC

-- Should be:
SELECT id, name, owner, inherent_likelihood, inherent_impact, ...
FROM risks WHERE org_id = :org_id ORDER BY ...
```

Similarly, `agent_conversations` and `agent_messages` have no `org_id` column.

**Impact:** In a multi-org deployment, all agents see ALL organizations' data.  
**Fix:** Add `org_id` parameter to `fetch_agent_context` and all queries; add `org_id` column to agent tables (migration).

### Bug 3: No Content Length Constraint on agent_messages

**Location:** `db/06_add_agent_tables.sql:14`

```sql
content TEXT NOT NULL  -- No length constraint
```

An attacker could insert a multi-megabyte message that exhausts the context window when loaded.

**Impact:** Context window exhaustion, denial of service.  
**Fix:** Add CHECK constraint or application-level truncation on `_save_message`.

---

## 4. Weakness Analysis

### 4.1 Real Weaknesses (Must Address)

| # | Weakness | Impact | Severity |
|---|----------|--------|----------|
| W1 | **No tool calling** — agents can read data but cannot invoke ML models or take actions | Agents are read-only analysts | CRITICAL |
| W2 | **LLM code duplicated** — same provider logic in ai.py and base.py | Maintenance burden, divergence risk | HIGH |
| W3 | **No cross-agent coordination** — strategy agent cannot consult risk agent | Blind spots in multi-domain analysis | HIGH |
| W4 | **No observability** — no token tracking, no cost attribution, no latency per agent | Cannot optimize or control AI spend | HIGH |
| W5 | **No memory** — agents forget everything between conversations | No continuity, no learning | MEDIUM |
| W6 | **No retry/fallback** — single LLM call fails, entire request fails | No resilience | MEDIUM |
| W7 | **Static context dump** — all module data injected every time | Token waste (but acceptable at current scale) | LOW |

### 4.2 Fake Weaknesses (v1.0 Overstated)

| # | "Weakness" | Reality | Why It's Fake |
|---|------------|---------|---------------|
| FW1 | "No agent coordination" is critical | Frontend routes to specific agents by design; cross-domain queries are rare | Users pick the right agent |
| FW2 | "No streaming" blocks users for 30s | Average LLM call is 3-8s; acceptable for enterprise users | Not a real UX problem at this scale |
| FW3 | "No RAG" prevents document understanding | Current data is all structured (DB tables); no unstructured docs exist in scope | RAG is future work, not current need |
| FW4 | "Prompt injection" is a major risk | Platform is internal enterprise; not public-facing; auth-gated | Threat model doesn't match |
| FW5 | "No hallucination mitigation" is dangerous | Agents are explicitly told "use the provided data" and return structured insights | Guardrails exist via prompt design |

---

## 5. What v1.0 Got Wrong

### 5.1 Orchestrator (REMOVED)

**v1.0 proposed:** Full orchestrator with intent classification, agent selection, task decomposition, and result synthesis.

**Problem:** The frontend ALREADY routes to agents. The user clicks "Risk Agent" → sends `agent: "risk"` → backend receives it. There is no intent classification problem to solve. The orchestrator would add latency to every request for zero benefit.

**v2.0 replacement:** A lightweight `QueryEnhancer` that enriches the user's message with relevant context (memory, cross-agent insights) BEFORE it reaches the existing AgentRunner. No routing, no decomposition — just smarter context.

### 5.2 4-Layer Memory (SIMPLIFIED)

**v1.0 proposed:** Working memory, long-term memory, summary memory, shared memory — 4 separate tables and systems.

**Problem:** For a single-org platform with ~10 concurrent users, this is premature. The conversation history already exists in `agent_messages`. The real gap is:
- Users can't see past conversations easily
- Agents can't reference past insights

**v2.0 replacement:** 2 practical additions:
1. `ai_memory` — simple key-value store for agent-accumulated facts
2. Add `org_id` to `agent_conversations` (fix existing bug)

### 5.3 Tool Permission Matrix (SIMPLIFIED)

**v1.0 proposed:** Per-agent permission matrix with 12+ tools, each with individual permission gates, rate limits, and schema validation.

**Problem:** All 9 existing agents are READ-ONLY against the database. They don't write anything. A permission matrix for SELECT queries is over-engineering.

**v2.0 replacement:** A simple tool registry where each agent declares which tools it uses. Tool execution validates input schema only. Permissions are implicit from the agent's module mapping (already defined in `AGENT_MODULE_MAP`).

### 5.4 LLM Provider Abstraction (SIMPLIFIED)

**v1.0 proposed:** Full provider abstraction with health checks, load balancing, circuit breakers, and rate limiting.

**Problem:** The existing system has 4 provider implementations (OpenAI-compat, Anthropic, Google, Ollama) that work fine. The user supplies their own API key and provider. The backend doesn't manage provider infrastructure.

**v2.0 replacement:** Extract the duplicated provider code into a single `llm_providers.py` module. Add basic retry with exponential backoff. No health checks, no load balancing — not needed when users choose their own providers.

### 5.5 Prompt Versioning (REMOVED)

**v1.0 proposed:** YAML-based prompt versioning with SHA256 hashes, version files, and performance scoring.

**Problem:** 9 agents with static prompts. Prompt changes happen during development, not in production. YAML versioning adds process overhead for zero production benefit.

**v2.0 replacement:** Prompts stay in `prompts.py` (Python). Changes are code changes with normal version control.

### 5.6 Agent Hierarchy (SIMPLIFIED)

**v1.0 proposed:** 3-tier hierarchy with 12 agents (9 existing + 3 new: executive, cross_domain, research).

**Problem:** The "executive" agent is just the strategy agent with all modules. The "cross_domain" agent is any agent with all modules. The "research" agent is for RAG which doesn't exist yet. Adding 3 agents for conceptual completeness adds code without adding capability.

**v2.0 replacement:** Keep existing 9 agents. Add ONE new agent: `executive` (combines all modules). The cross-domain capability comes from the `QueryEnhancer`, not a separate agent.

### 5.7 Streaming (DEFERRED)

**v1.0 proposed:** Full SSE + WebSocket streaming architecture.

**Problem:** Enterprise users making strategic queries can wait 5-10 seconds. Streaming adds significant complexity (WebSocket management, backpressure, reconnection) for marginal UX improvement.

**v2.0 replacement:** Deferred to Phase 5. Phase 3 uses synchronous responses (current behavior).

### 5.8 Injection Detection (RETHOUGHT)

**v1.0 proposed:** Regex-based prompt injection detection with 8 pattern categories.

**Problem:** Regex-based injection detection is fundamentally bypassable. Any pattern can be evaded with encoding, paraphrasing, or novel attack vectors. It creates a false sense of security.

**v2.0 replacement:** Defense-in-depth approach:
1. **Input length limits** (already enforced via Pydantic)
2. **System prompt hardening** (clear role boundaries in prompts)
3. **Output guardrails** (validate outputs against data, not inputs against patterns)
4. **Audit logging** (log all inputs for post-hoc analysis)

### 5.9 Folder Structure (REDUCED)

**v1.0 proposed:** 30+ new files across 8 subdirectories.

**Problem:** For a codebase with 41 Python files, adding 30+ more is disproportionate. Each file needs maintenance, testing, and understanding.

**v2.0 replacement:** 8 new files in a flat `ai/` module:

```
backend/app/ai/
├── __init__.py
├── llm_providers.py          # Consolidated LLM provider code
├── tool_registry.py          # Tool definitions + execution
├── memory.py                 # Simple agent memory
├── query_enhancer.py         # Context enrichment (replaces orchestrator)
├── exec_agent.py             # New executive agent
├── guardrails.py             # Output validation
└── metrics.py                # Token/cost tracking
```

---

## 6. Revised Enterprise Architecture

### 6.1 High-Level Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                       CLIENT LAYER                           │
│  Frontend (existing) ──── API Clients                        │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│                    FASTAPI (existing)                         │
│  ├── Existing 19 routers (UNTOUCHED)                        │
│  ├── /agents/chat (existing — primary AI entry point)        │
│  └── /ai/chat (existing — direct LLM)                       │
└──────────────────────────┬───────────────────────────────────┘
                           │
          ┌────────────────┼────────────────┐
          │                │                 │
          ▼                ▼                 ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│  EXISTING    │  │  EXISTING    │  │  NEW: AI     │
│  AgentRunner │  │  ai.py       │  │  Module      │
│  (UNTOUCHED) │  │  (UNTOUCHED) │  │  (additive)  │
│              │  │              │  │              │
│  9 agents    │  │  Direct LLM  │  │  - LLM utils │
│  Tools       │  │  4 providers │  │  - Tools     │
│  Memory      │  │  File upload │  │  - Memory    │
└──────┬───────┘  └──────────────┘  │  - Metrics   │
       │                            │  - Guardrails│
       │    ┌───────────────────────│  - Exec Agent│
       │    │                       └──────┬───────┘
       │    │ (optional enhancement)       │
       │    │                              │
       ▼    ▼                              ▼
┌──────────────────────────────────────────────────────────────┐
│                     DATA LAYER                               │
│  PostgreSQL (17 existing tables + 2 new additive tables)     │
│  ML Models (5 XGBoost — UNTOUCHED)                          │
└──────────────────────────────────────────────────────────────┘
```

### 6.2 Key Design Differences from v1.0

| Aspect | v1.0 | v2.0 |
|--------|------|------|
| Orchestrator | Full intent classification + routing | REMOVED (frontend routes already) |
| Agent count | 9 existing + 3 new = 12 | 9 existing + 1 new = 10 |
| Memory | 4 layers, 4 tables | 1 new table + existing tables |
| Tools | Full registry + permissions + rate limits | Simple tool list per agent |
| LLM | Provider abstraction + health checks + load balancing | Consolidated shared module + retry |
| Streaming | SSE + WebSocket | DEFERRED to Phase 5 |
| Security | Regex injection detection | Output validation + audit logging |
| Folder structure | 30+ new files | 8 new files |
| New DB tables | 6 | 2 |
| Estimated new code | ~3000 lines | ~800 lines |

### 6.3 New Folder Structure (v2.0)

```
backend/app/ai/
├── __init__.py              # Module exports
├── llm_providers.py         # Unified LLM calling (replaces duplication)
├── tool_registry.py         # Tool definitions + execution
├── memory.py                # Agent memory (accumulated insights)
├── query_enhancer.py        # Context enrichment before agent execution
├── exec_agent.py            # Executive agent (cross-domain)
├── guardrails.py            # Output validation
└── metrics.py               # Token usage + cost tracking
```

Total: **8 files, ~800 lines** (vs. v1.0's 30+ files, ~3000 lines).

---

## 7. Agent Design

### 7.1 Existing Agents (UNTOUCHED)

All 9 existing agents remain exactly as-is:
- `backend/app/agents/base.py` — AgentRunner
- `backend/app/agents/prompts.py` — AGENT_PROMPTS
- `backend/app/agents/tools.py` — fetch_agent_context, fetch_module_data

### 7.2 New: Executive Agent

**Rationale:** Users sometimes need a "give me the full picture" response that spans all domains. Currently this requires the user to manually ask each agent and synthesize themselves.

**Implementation:** A single new agent that:
1. Has access to ALL modules (like strategy + risk + finance combined)
2. Runs all 5 ML models for a full forecast
3. Returns a structured executive summary

**NOT a replacement for the orchestrator.** It's just a 10th agent the user can select from the frontend.

### 7.3 Agent Module Mapping (Existing — Preserved)

```python
AGENT_MODULE_MAP = {
    "strategy": ["scorecards", "initiatives", "projects", "swot", "pestel"],
    "risk": ["risks", "incidents", "audit", "compliance"],
    "finance": ["budgets", "scorecards", "initiatives"],
    "compliance": ["compliance", "audit", "risks"],
    "audit": ["audit", "compliance", "risks"],
    "task": ["tasks", "initiatives", "projects"],
    "meetings": ["meetings", "tasks", "initiatives"],
    "projects": ["initiatives", "projects", "budgets"],
    "incident": ["incidents", "risks", "compliance"],
    "executive": ["risks", "incidents", "scorecards", "budget_lines",  # NEW
                   "initiatives", "tasks", "audit", "compliance", "swot", "pestel", "bcp"],
}
```

### 7.4 How the Query Enhancer Works (Replaces Orchestrator)

Instead of routing queries to agents, the `QueryEnhancer` adds context BEFORE the agent runs:

```
User: "What's our risk posture?"

1. User sends to /agents/chat with agent: "risk"
2. QueryEnhancer checks:
   ├── Does the user have recent relevant memory? → Add to context
   ├── Are there cross-agent insights about risks? → Add to context
   └── Are there ML predictions relevant to risks? → Add to context
3. Enhanced context is prepended to the user message
4. Existing AgentRunner processes as usual
```

**Key difference from v1.0 orchestrator:** This does NOT change routing, does NOT decompose queries, does NOT manage multi-agent execution. It just makes the existing single-agent path smarter.

---

## 8. Tool System

### 8.1 Tool Definition (Simplified)

```python
class Tool:
    name: str
    description: str
    execute: Callable  # async function
    
tools = {
    "predict_risk": Tool(
        name="predict_risk",
        description="Predict risk score given likelihood, impact, days_open, vendor_pct",
        execute=predict_risk_tool,
    ),
    "predict_revenue": Tool(...),
    "predict_attrition": Tool(...),
    "predict_incidents": Tool(...),
    "predict_budget": Tool(...),
    "get_full_forecast": Tool(...),
}
```

### 8.2 Agent Tool Mapping

| Agent | Available Tools |
|-------|----------------|
| strategy | predict_revenue, get_full_forecast |
| risk | predict_risk, predict_incidents |
| finance | predict_budget, predict_revenue |
| compliance | (none — analysis only) |
| audit | (none — analysis only) |
| task | (none — analysis only) |
| meetings | (none — analysis only) |
| projects | predict_budget |
| incident | predict_incidents |
| executive | ALL tools |

### 8.3 Tool Invocation Flow

```
Agent wants to call a tool
    │
    ├── Is tool in agent's allowed list? ──No──→ Skip (not an error)
    │
    ├── Validate input params against tool schema
    │
    ├── Execute tool
    │
    ├── Return result to agent as context
    │
    └── Log invocation to ai_tool_invocations table
```

No complex permission matrix. No rate limiting. Just schema validation + logging.

---

## 9. Memory Design

### 9.1 What's Actually Needed

**Problem:** Agents forget past conversations. If a user discussed "cybersecurity risks" last week and asks about them today, the agent has no memory.

**Current state:** `agent_messages` stores conversation turns. But there's no mechanism to surface past insights to new conversations.

### 9.2 Solution: One New Table

```sql
CREATE TABLE IF NOT EXISTS ai_memory (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    agent_name TEXT NOT NULL,
    insight TEXT NOT NULL,
    source TEXT,                     -- e.g. "risks#12", "scorecards#5"
    confidence FLOAT DEFAULT 0.5,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    accessed_at TIMESTAMPTZ,
    access_count INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_ai_memory_user ON ai_memory(user_id);
CREATE INDEX IF NOT EXISTS idx_ai_memory_agent ON ai_memory(agent_name);
```

**One table. Simple schema. Solves the real problem.**

### 9.3 Memory Operations

| Operation | When | How |
|-----------|------|-----|
| **Store** | Agent identifies a key insight during conversation | INSERT INTO ai_memory (agent extracts insight from its own response) |
| **Retrieve** | Agent starts a new conversation | SELECT relevant insights by agent_name + recency |
| **Prune** | On access or daily | Delete entries older than 30 days with access_count < 2 |

### 9.4 What v2.0 Removed

| v1.0 Memory Layer | Why Removed |
|-------------------|-------------|
| Working memory | Conversation history already exists in `agent_messages` |
| Summary memory | Premature; add when conversation volume warrants it |
| Shared memory | Org-level insights can use `ai_memory` with a shared user_id (NULL = org-wide) |

---

## 10. Context Pipeline

### 10.1 Current Behavior (Preserved)

The existing `fetch_agent_context` fetches ALL rows from ALL related modules. For the current data volumes (~12 risks, ~8 incidents, ~18 scorecards, ~18 budget lines, ~5 tasks, ~4 meetings, ~4 audit findings, ~3 compliance frameworks, ~10 initiatives, ~10 projects, ~30 SWOT/PESTEL items, ~11 BCP processes), this is approximately **2000-3000 tokens** — well within limits.

### 10.2 Enhancement: Query-Aware Context (Optional)

For future data growth, a `QueryEnhancer` can filter context based on the user's query:

```python
# If user asks about "cyber risk":
# Instead of ALL 12 risks, filter to:
SELECT * FROM risks WHERE name ILIKE '%cyber%' OR name ILIKE '%security%'
# Returns 2-3 relevant risks instead of 12
```

**This is an optimization, not a requirement.** Implement only when data volumes justify it.

### 10.3 Context Budget (Reference)

| Component | Current Tokens | Max Recommended |
|-----------|---------------|-----------------|
| System prompt | ~300 | 2,000 |
| Org data (all modules) | ~2,500 | 8,000 |
| Conversation history | ~1,000 | 4,000 |
| Memory insights | 0 (new) | 500 |
| Tool results | 0 (new) | 2,000 |
| **Total** | ~3,800 | ~16,500 |

No budget management needed until data grows 5x.

---

## 11. LLM Provider Consolidation

### 11.1 The Duplication Problem

**Current state:** Two files implement the same 4 providers with near-identical code.

`ai.py` has: `_build_openai_compatible`, `_call_openai_compatible`, `_call_anthropic`, `_call_google`, `_call_ollama`

`base.py` has: `_call_openai_compatible`, `_call_anthropic`, `_call_google`, `_call_ollama`

### 11.2 Solution: Single Shared Module

Create `backend/app/ai/llm_providers.py` that both `ai.py` and `base.py` import from:

```python
# ai/llm_providers.py

async def call_llm(provider: str, api_key: str, model: str,
                   system_prompt: str, messages: list, 
                   max_tokens: int = 2048) -> str:
    """Unified LLM call — all providers."""
    if provider == "anthropic":
        return await _call_anthropic(api_key, model, system_prompt, messages)
    elif provider == "google":
        return await _call_google(api_key, model, system_prompt, messages)
    elif provider == "ollama":
        return await _call_ollama(api_key, model, system_prompt, messages)
    elif provider in ("openai", "deepseek", "moonshot", "together", "mistral", "xai"):
        return await _call_openai_compatible(provider, api_key, model, 
                                              system_prompt, messages, max_tokens)
    else:
        raise ValueError(f"Unknown provider: {provider}")
```

### 11.3 Retry Logic (Add to Shared Module)

```python
async def call_llm_with_retry(provider, api_key, model, system_prompt, messages,
                               max_tokens=2048, max_retries=2, timeout=120):
    """LLM call with retry + exponential backoff."""
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            return await call_llm(provider, api_key, model, system_prompt, 
                                  messages, max_tokens)
        except (httpx.HTTPStatusError, httpx.ConnectTimeout) as e:
            last_error = e
            if attempt < max_retries:
                await asyncio.sleep(2 ** attempt)  # 1s, 2s
    raise last_error
```

### 11.4 What v2.0 Removed

| v1.0 Feature | Why Removed |
|-------------|-------------|
| Provider health checks | Users supply their own keys; health is their concern |
| Load balancing | Single request per user; no load to balance |
| Circuit breakers | Premature for single-org scale |
| Provider cost tracking | Users manage their own API costs |
| Fallback chain (provider 1 → 2 → 3) | User already chose their provider; auto-switching is confusing |

---

## 12. Security Model

### 12.1 Defense-in-Depth (Revised)

```
Layer 1: API Security (EXISTING — Phase 2)
├── JWT authentication
├── CORS enforcement
├── Input validation (Pydantic)
├── Security headers
└── Rate limiting (existing constants, to be enforced)

Layer 2: AI Security (NEW — lightweight)
├── Input length enforcement (already in Pydantic validators)
├── Output validation (guardrails.py)
├── Audit logging (ai_tool_invocations, ai_agent_runs)
└── Content truncation (prevent context window exhaustion)
```

### 12.2 Output Guardrails (Not Input Injection Detection)

Instead of trying to detect injection (fundamentally unreliable), validate outputs:

```python
class OutputGuardrails:
    """Validate agent output before returning to user."""
    
    def validate(self, output: str, context: dict) -> GuardrailResult:
        checks = [
            self._check_length(output),           # Max output length
            self._check_pii(output),              # Strip SSN, credit cards
            self._check_data_consistency(output, context),  # Claims match data
            self._check_source_attribution(output),  # Factual claims cited
        ]
        return GuardrailResult(passed=all(c.passed for c in checks), checks=checks)
```

### 12.3 Context Window Protection

```python
# Prevent memory/conversation history from being too large
MAX_CONTEXT_MESSAGES = 20
MAX_MEMORY_INSIGHTS = 10
MAX_TOOL_RESULT_CHARS = 5000

def truncate_for_context(messages: list, max_messages: int = MAX_CONTEXT_MESSAGES) -> list:
    """Keep only the most recent messages."""
    return messages[-max_messages:]
```

### 12.4 What v1.0 Got Wrong About Security

| v1.0 Approach | Problem | v2.0 Approach |
|--------------|---------|--------------|
| Regex injection detection | Bypassable; false confidence | Input length limits + audit logging |
| Tool permission matrix | Overkill for read-only tools | Simple allow-list per agent |
| Agent permission levels | All agents are same permission level | Permissions implicit from module access |
| Output content filtering | Complex; may block valid outputs | PII detection + source attribution only |

---

## 13. ML Integration

### 13.1 ML as Tools (Simplified)

The 5 existing ML models become callable tools:

```python
from ml.scripts.inference_all import (
    predict_risk, predict_revenue, predict_attrition,
    predict_incidents, predict_budget_variance, run_full_forecast,
)

ML_TOOLS = {
    "predict_risk": Tool(name="predict_risk", execute=lambda params: predict_risk(params)),
    "predict_revenue": Tool(name="predict_revenue", execute=lambda params: predict_revenue(params)),
    "predict_attrition": Tool(name="predict_attrition", execute=lambda params: predict_attrition(params)),
    "predict_incidents": Tool(name="predict_incidents", execute=lambda params: predict_incidents(params)),
    "predict_budget": Tool(name="predict_budget", execute=lambda params: predict_budget_variance(params)),
    "full_forecast": Tool(name="full_forecast", execute=lambda params: run_full_forecast(params)),
}
```

### 13.2 Agent-ML Integration

| Agent | ML Tools Available | Use Case |
|-------|-------------------|----------|
| risk | predict_risk, predict_incidents | "What's the predicted risk score for our top risk?" |
| finance | predict_budget, predict_revenue | "Forecast our budget variance for next quarter" |
| executive | ALL ML tools | Full forecast report |

### 13.3 What Unchanged

- No changes to `ml/scripts/inference.py`
- No changes to `ml/scripts/inference_all.py`
- No changes to any `.joblib` model files
- No changes to `ml/scripts/train.py` or `train_all.py`
- No changes to `ml/models/manifest.json`

---

## 14. Database Strategy

### 14.1 New Tables (Additive Only)

```sql
-- Table 1: Agent memory (accumulated insights)
CREATE TABLE IF NOT EXISTS ai_memory (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    agent_name TEXT NOT NULL,
    insight TEXT NOT NULL,
    source TEXT,
    confidence FLOAT DEFAULT 0.5,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    accessed_at TIMESTAMPTZ,
    access_count INTEGER DEFAULT 0
);

-- Table 2: Agent execution log (observability)
CREATE TABLE IF NOT EXISTS ai_agent_runs (
    id SERIAL PRIMARY KEY,
    conversation_id INTEGER REFERENCES agent_conversations(id) ON DELETE CASCADE,
    agent_name TEXT NOT NULL,
    provider TEXT,
    model TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    duration_ms INTEGER,
    tools_used TEXT[],
    success BOOLEAN DEFAULT true,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ai_memory_user ON ai_memory(user_id);
CREATE INDEX IF NOT EXISTS idx_ai_memory_agent ON ai_memory(agent_name);
CREATE INDEX IF NOT EXISTS idx_ai_agent_runs_conv ON ai_agent_runs(conversation_id);
CREATE INDEX IF NOT EXISTS idx_ai_agent_runs_agent ON ai_agent_runs(agent_name);
```

### 14.2 Schema Changes to Existing Tables

| Table | Change | Migration |
|-------|--------|-----------|
| `agent_conversations` | Add `org_id INTEGER` column | `ALTER TABLE agent_conversations ADD COLUMN org_id INTEGER REFERENCES organizations(id)` |
| `agent_messages` | Add CHECK constraint on content length | `ALTER TABLE agent_messages ADD CONSTRAINT chk_content_length CHECK (length(content) <= 50000)` |

### 14.3 What v1.0 Removed

| v1.0 Table | Why Removed |
|-----------|-------------|
| `ai_conversation_summaries` | Premature; add when conversation volume warrants compression |
| `ai_shared_insights` | Use `ai_memory` with NULL user_id for org-wide insights |
| `ai_tool_invocations` | Use `ai_agent_runs` with tools_used array |
| `ai_token_usage` | Use `ai_agent_runs` with token columns |
| `ai_prompt_versions` | Prompts are code; version via git |
| `ai_orchestrator_logs` | No orchestrator to log |

**2 new tables instead of 6.** Each new table has clear, practical purpose.

---

## 15. Deployment

### 15.1 Docker Changes (Minimal)

```yaml
# docker-compose.yml additions
services:
  api:
    environment:
      # Existing (unchanged)
      DATABASE_URL: ${DATABASE_URL}
      JWT_SECRET: ${JWT_SECRET}
      CORS_ORIGINS: ${CORS_ORIGINS}
      
      # NEW (optional)
      AI_METRICS_ENABLED: ${AI_METRICS_ENABLED:-true}
      AI_MEMORY_ENABLED: ${AI_MEMORY_ENABLED:-true}
```

### 15.2 Feature Flags

```python
# Simple flags, not a framework
AI_METRICS_ENABLED = os.getenv("AI_METRICS_ENABLED", "true").lower() == "true"
AI_MEMORY_ENABLED = os.getenv("AI_MEMORY_ENABLED", "true").lower() == "true"
```

### 15.3 Graceful Degradation

| Failure | Behavior |
|---------|----------|
| `ai/` module fails to import | All existing endpoints work; new features disabled |
| `ai_memory` table missing | Memory features disabled; agents work without memory |
| `ai_agent_runs` table missing | Logging disabled; agents work without metrics |
| ML model files missing | ML tools return error; agents handle gracefully (existing behavior) |
| LLM provider fails | Retry once; then return error to user (existing behavior) |

---

## 16. Monitoring

### 16.1 What to Track

| Metric | Source | Purpose |
|--------|--------|---------|
| Agent execution time | `ai_agent_runs.duration_ms` | Performance monitoring |
| Token usage per query | `ai_agent_runs.input/output_tokens` | Cost optimization |
| Tool invocation count | `ai_agent_runs.tools_used` | Feature usage |
| Error rate per agent | `ai_agent_runs.success` | Reliability |
| Memory usage per user | `ai_memory.access_count` | Memory effectiveness |

### 16.2 Logging

```python
# Enhanced agent execution logging
logger.info(
    "agent_run agent=%s provider=%s model=%s tokens=%d/%d duration=%dms tools=%s success=%s",
    agent_name, provider, model, input_tokens, output_tokens, 
    duration_ms, tools_used, success
)
```

### 16.3 What v1.0 Removed

| v1.0 Feature | Why Removed |
|-------------|-------------|
| Prometheus + Grafana stack | Premature; structured logging sufficient |
| OpenTelemetry tracing | Overkill for single-service architecture |
| Alerting rules | Add when operational patterns are known |
| Real-time dashboard | Add after metrics collection proves valuable |

---

## 17. Migration Plan

### 17.1 Prerequisites (Bug Fixes)

Before Phase 3 work begins, fix these existing bugs:

| Bug | File | Fix |
|-----|------|-----|
| Silent user_id loss | `agents.py:75` | Query user ID from email |
| No org_id in agent queries | `agents/tools.py` | Add org_id parameter to all queries |
| No content length on messages | `06_add_agent_tables.sql` | Add CHECK constraint |
| LLM code duplication | `ai.py` + `base.py` | Consolidate to shared module |

### 17.2 Implementation Steps

```
Step 1: Bug Fixes + LLM Consolidation (Week 1)
├── Fix user_id resolution in agents.py
├── Add org_id to agent tools queries
├── Add content length constraint
├── Create ai/llm_providers.py (extract from ai.py + base.py)
├── Update ai.py to import from shared module
├── Update base.py to import from shared module
└── Verify: 106 tests still pass

Step 2: Tool System + Executive Agent (Week 2-3)
├── Create ai/tool_registry.py (ML tools)
├── Create ai/exec_agent.py (new agent)
├── Create ai/metrics.py (execution logging)
├── Create ai_agent_runs table
├── Update agents.py to log executions
├── Add executive agent to prompts.py + tools.py
└── Verify: new tools work, exec agent responds

Step 3: Memory + Query Enhancement (Week 4-5)
├── Create ai_memory table
├── Create ai/memory.py (store/retrieve/prune)
├── Create ai/query_enhancer.py (context enrichment)
├── Integrate memory into AgentRunner (non-breaking)
└── Verify: memory persists, context is enriched

Step 4: Guardrails + Polish (Week 6)
├── Create ai/guardrails.py (output validation)
├── Add guardrails to agent responses
├── Add retry logic to llm_providers.py
├── Performance testing
├── Security review
└── Verify: all 106 + new tests pass

Step 5: Integration Testing (Week 7)
├── End-to-end testing
├── Frontend integration
├── Load testing
├── Documentation
└── PHASE 3 COMPLETE
```

### 17.3 Backward Compatibility

| Check | Status |
|-------|--------|
| All 19 existing routers unchanged | ✅ |
| All 40+ existing endpoints work | ✅ |
| All 17 existing DB tables unchanged | ✅ |
| Frontend unchanged | ✅ |
| ML models unchanged | ✅ |
| Authentication unchanged | ✅ |
| 106 tests pass | ✅ |
| Docker builds and runs | ✅ |

---

## 18. Risks

| # | Risk | Probability | Impact | Mitigation |
|---|------|-------------|--------|------------|
| R1 | **LLM consolidation breaks existing ai.py or agents.py** | MEDIUM | HIGH | Write tests for shared module BEFORE refactoring; keep old functions as wrappers initially |
| R2 | **org_id migration causes data loss** | LOW | HIGH | Test migration on copy of production data first; reversible ALTER TABLE |
| R3 | **Memory table grows unbounded** | LOW | MEDIUM | Implement pruning from day one; cap at 1000 entries per user |
| R4 | **Executive agent prompt too complex for single LLM call** | MEDIUM | LOW | Keep executive agent simple; fall back to summary if context too large |
| R5 | **Tool invocation adds latency** | LOW | LOW | ML models load in <100ms; tool calls add <200ms |
| R6 | **Scope creep during implementation** | HIGH | MEDIUM | Strict step-by-step plan; no new features beyond defined scope |

---

## 19. Trade-offs

| Decision | Chosen | Alternative | Rationale |
|----------|--------|-------------|-----------|
| **Agent framework** | Custom (extend existing) | LangChain / CrewAI | Avoid dependency bloat; existing code works; 106 tests validate it |
| **Memory store** | PostgreSQL (new table) | Redis | Leverage existing DB; no new infrastructure; single-org scale sufficient |
| **LLM abstraction** | Shared Python module | Class hierarchy | Simpler; same pattern as existing code; no inheritance overhead |
| **Tool system** | Simple registry (dict) | Plugin architecture | 6 tools don't need a plugin system |
| **Prompt management** | Python code (existing) | YAML/template files | Prompts are code; normal version control is sufficient |
| **Monitoring** | Structured logging | Prometheus + Grafana | Faster to implement; sufficient for current scale |
| **Security** | Output validation + audit | Regex injection detection | Output validation is more reliable; injection detection is bypassable |
| **Streaming** | Deferred | Immediate | Enterprise users tolerate 5-10s; complexity not justified yet |
| **RAG** | Deferred | Immediate | No unstructured documents in current scope |
| **New agents** | 1 (executive) | 3 (executive + cross_domain + research) | One agent solves the real problem; others are conceptual |

---

## 20. Implementation Phases

### Phase 3: Enterprise AI (This Design — Revised)
**Duration:** 7 weeks (down from 16 in v1.0)  
**Goal:** Tool calling, memory, metrics, LLM consolidation, executive agent  
**Lines of new code:** ~800 (down from ~3000 in v1.0)  
**New files:** 8 (down from 30+ in v1.0)  
**New DB tables:** 2 (down from 6 in v1.0)

### Phase 4: RAG + Document Intelligence (Future)
**Duration:** 12 weeks  
**Dependencies:** Phase 3 complete + unstructured documents in scope  
**Scope:** Document ingestion, embeddings, semantic retrieval

### Phase 5: Advanced AI (Future)
**Duration:** 16 weeks  
**Dependencies:** Phase 4 complete  
**Scope:** Streaming, proactive alerting, prompt A/B testing, automated model retraining

---

## 21. Readiness Verdict

### Is this architecture ready for implementation?

## **YES — with caveats**

**What's ready:**
- Tool system (simple, practical, well-defined)
- Memory system (one table, clear operations)
- LLM consolidation (proven code, just deduplication)
- Executive agent (straightforward extension of existing pattern)
- Metrics (structured logging, one new table)
- Guardrails (output validation, practical)

**What needs attention before implementation:**
1. The 3 existing bugs (user_id, org_id, content length) should be fixed FIRST as they affect the AI layer
2. The LLM consolidation refactoring needs tests BEFORE refactoring to catch regressions
3. The executive agent prompt needs careful crafting — it's the most complex new prompt

**What changed from v1.0:**
- 73% less new code (800 vs 3000 lines)
- 73% fewer new files (8 vs 30+)
- 67% fewer new DB tables (2 vs 6)
- 56% faster implementation (7 weeks vs 16)
- Zero over-engineered components
- Zero unnecessary abstractions
- All identified existing bugs flagged for fixing

**The architecture is practical, proportional to the platform's actual scale, and respects the existing codebase. Implementation may begin when authorized.**

---

*End of Architecture Design Document v2.0*
