import asyncio
import logging
import time
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from typing import Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import require_role
from app.core.config import settings
from app.agents.base import AgentRunner
from app.agents.prompts import AGENT_PROMPTS
from app.agents.task_tools import query_user_tasks, update_task_status
from app.ai.tokens import token_benchmark, sanitize_input, valid_input_chars
from app.services.java_bridge import bridge

AGENT_DOMAINS = [
    "strategy", "risk", "finance", "compliance", "audit",
    "task", "meetings", "projects", "incident", "decision",
]

logger = logging.getLogger("stratroom.agents")

router = APIRouter(prefix="/agents", tags=["agents"])


class AgentChatRequest(BaseModel):
    agent: str
    message: str
    provider: str
    api_key: str = ""
    model: str
    conversation_id: Optional[int] = None
    base_url: Optional[str] = None

    @field_validator("agent")
    @classmethod
    def validate_agent(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in AGENT_PROMPTS:
            raise ValueError(f"Unknown agent: {v}. Available: {', '.join(sorted(AGENT_PROMPTS.keys()))}")
        return v

    @field_validator("message")
    @classmethod
    def validate_message(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Message cannot be empty")
        if not valid_input_chars(v):
            raise ValueError("Message contains disallowed control characters")
        if len(v) > settings.MAX_CHAT_INPUT_CHARS:
            raise ValueError(
                f"Message exceeds maximum length of {settings.MAX_CHAT_INPUT_CHARS} characters"
            )
        if len(v) > settings.MAX_PROMPT_LENGTH:
            raise ValueError(f"Message exceeds maximum length of {settings.MAX_PROMPT_LENGTH}")
        return v

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, v: str) -> str:
        v = v.strip().lower()
        if v and v not in settings.ALLOWED_PROVIDERS:
            raise ValueError(f"Unsupported provider: {v}. Allowed: {', '.join(sorted(settings.ALLOWED_PROVIDERS))}")
        return v

    @field_validator("model")
    @classmethod
    def validate_model(cls, v: str) -> str:
        v = v.strip()
        if len(v) > 200:
            raise ValueError("Model name too long")
        return v


@router.post("/chat")
async def agent_chat(
    req: AgentChatRequest,
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("member")),
):
    user_id = ctx["user_id"]
    org_id = ctx["org_id"]
    is_admin = ctx["is_admin"]

    # ── Provider resolution ────────────────────────────────────────────
    # If the request carries its own api_key or a custom endpoint, honor it
    # fully. Otherwise fall back to the server-side default (AI_PROVIDER /
    # AI_API_KEY / AI_MODEL) so the chat works without per-user setup.
    if req.api_key or req.base_url:
        provider = (req.provider or settings.AI_DEFAULT_PROVIDER).lower()
        model = req.model or settings.AI_DEFAULT_MODEL
        api_key = req.api_key or settings.AI_DEFAULT_API_KEY
    else:
        provider = (settings.AI_DEFAULT_PROVIDER or req.provider).lower()
        model = settings.AI_DEFAULT_MODEL or req.model
        api_key = settings.AI_DEFAULT_API_KEY or req.api_key

    if not provider or provider not in settings.ALLOWED_PROVIDERS:
        raise HTTPException(
            status_code=422,
            detail="No usable AI provider. Provide a provider/api_key in the request or configure AI_PROVIDER on the server.",
        )
    if not model:
        raise HTTPException(
            status_code=422,
            detail="No usable AI model. Provide a model in the request or configure AI_MODEL on the server.",
        )
    if not api_key and provider not in ("ollama", "mock"):
        if settings.AI_DEFAULT_API_KEY:
            api_key = settings.AI_DEFAULT_API_KEY
        else:
            provider = "mock"
            model = "mock"

    runner = AgentRunner(req.agent)
    try:
        if req.conversation_id:
            conv = await bridge.get(
                bridge.db_service, f"/conversations/{req.conversation_id}",
                params={"uid": user_id},
            )
            if not conv:
                raise HTTPException(status_code=404, detail="Conversation not found")

        result = await runner.run(
            db=db,
            user_message=req.message,
            provider=provider,
            api_key=api_key,
            model=model,
            user_id=user_id,
            org_id=org_id,
            conversation_id=req.conversation_id,
            base_url=req.base_url,
            is_admin=is_admin,
            ctx=ctx,
        )
        return result
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as exc:
        logger.exception("Agent chat failed [user=%s agent=%s]", user_id, req.agent)
        raise HTTPException(status_code=502, detail="Agent request failed. Please try again later.")


@router.get("/benchmark")
async def agent_token_benchmark(ctx: dict = Depends(require_role("member"))):
    """In-memory token benchmark — average tokens consumed per response.

    Returns the aggregate estimate plus the rolling recent window. This is a
    monitoring aid for operators reviewing token consumption; it does not
    disclose raw user messages.
    """
    return {"averages": token_benchmark.snapshot(), "recent": token_benchmark.recent()}


@router.get("/effective-config")
async def effective_agent_config(ctx: dict = Depends(require_role("member"))):
    """Return the server-side default AI provider/model so the UI can show the
    real provider badge (e.g. TOGETHER) instead of hardcoded marketing text.
    """
    return {
        "provider": settings.AI_DEFAULT_PROVIDER or "",
        "model": settings.AI_DEFAULT_MODEL or "",
        "key_configured": bool(settings.AI_DEFAULT_API_KEY),
    }


class TaskActionRequest(BaseModel):
    action: str  # 'query', 'update', or 'update_progress'
    task_id: Optional[int] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    progress: Optional[int] = None


@router.post("/task-action")
async def task_action(
    req: TaskActionRequest,
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("member")),
):
    """Direct task management tool — executes without LLM round-trip."""
    user_id = ctx["user_id"]
    org_id = ctx["org_id"]
    is_admin = ctx["is_admin"]

    try:
        if req.action == "query":
            result = await query_user_tasks(
                db, user_id, org_id,
                status_filter=req.status,
                priority_filter=req.priority,
                is_admin=is_admin,
                email=ctx.get("email"),
            )
            return result

        elif req.action == "update":
            if not req.task_id:
                raise HTTPException(status_code=422, detail="task_id is required for update action")
            result = await update_task_status(
                db, user_id, org_id, req.task_id, req.status, is_admin,
                email=ctx.get("email"),
            )
            if "error" in result:
                raise HTTPException(status_code=404, detail=result["error"])
            return result

        elif req.action == "update_progress":
            if not req.task_id:
                raise HTTPException(status_code=422, detail="task_id is required for update_progress action")
            from app.agents.task_tools import update_task_progress
            result = await update_task_progress(
                db, user_id, org_id, req.task_id, req.progress, is_admin,
                email=ctx.get("email"),
            )
            if "error" in result:
                raise HTTPException(status_code=404, detail=result["error"])
            return result

        else:
            raise HTTPException(status_code=422, detail=f"Unknown action: {req.action}. Use 'query', 'update', or 'update_progress'.")

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Task action failed [user=%s action=%s]", user_id, req.action)
        raise HTTPException(status_code=500, detail="Task action failed. Please try again later.")


class InitiativeActionRequest(BaseModel):
    action: str  # 'query' or 'update_progress'
    initiative_id: Optional[int] = None
    progress: Optional[int] = None


@router.post("/initiative-action")
async def initiative_action(
    req: InitiativeActionRequest,
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("member")),
):
    """Direct initiative management tool — executes without LLM round-trip."""
    from app.agents.initiative_tools import query_initiatives, update_initiative_progress

    user_id = ctx["user_id"]
    org_id = ctx["org_id"]
    is_admin = ctx["is_admin"]
    email = ctx.get("email")

    try:
        if req.action == "query":
            return await query_initiatives(
                db, user_id, org_id,
                is_admin=is_admin,
                email=email,
            )

        elif req.action == "update_progress":
            if not req.initiative_id:
                raise HTTPException(status_code=422, detail="initiative_id is required for update_progress action")
            result = await update_initiative_progress(
                db, user_id, org_id,
                initiative_id=req.initiative_id,
                progress=req.progress,
                is_admin=is_admin,
                email=email,
            )
            if "error" in result:
                raise HTTPException(status_code=404, detail=result["error"])
            return result

        else:
            raise HTTPException(status_code=422, detail=f"Unknown action: {req.action}. Use 'query' or 'update_progress'.")

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Initiative action failed [user=%s action=%s]", user_id, req.action)
        raise HTTPException(status_code=500, detail="Initiative action failed. Please try again later.")


@router.get("/conversations")
async def list_conversations(
    agent: Optional[str] = None,
    ctx: dict = Depends(require_role("member")),
):
    params = {"uid": ctx["user_id"], "oid": ctx["org_id"]}
    if agent:
        params["agent"] = agent
    result = await bridge.get(
        bridge.db_service, "/conversations",
        params=params,
    )
    return {"conversations": result if isinstance(result, list) else []}


@router.get("/messages/{conversation_id}")
async def get_messages(
    conversation_id: int,
    ctx: dict = Depends(require_role("member")),
):
    conv = await bridge.get(
        bridge.db_service, f"/conversations/{conversation_id}",
        params={"uid": ctx["user_id"]},
    )
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    messages = await bridge.get(
        bridge.db_service, f"/conversations/{conversation_id}/messages",
    )
    return {"messages": messages if isinstance(messages, list) else []}


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: int,
    ctx: dict = Depends(require_role("member")),
):
    conv = await bridge.get(
        bridge.db_service, f"/conversations/{conversation_id}",
        params={"uid": ctx["user_id"]},
    )
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    await bridge.delete(bridge.db_service, f"/conversations/{conversation_id}/messages")
    await bridge.delete(bridge.db_service, f"/conversations/{conversation_id}")
    return {"ok": True}


@router.get("/test-ollama")
async def test_ollama_connection(
    endpoint: str = "",
    ctx: dict = Depends(require_role("member")),
):
    import httpx
    import os
    # If inside Docker, rewrite localhost to host.docker.internal
    in_docker = os.path.exists("/.dockerenv")
    if not endpoint:
        endpoint = "http://host.docker.internal:11434" if in_docker else "http://localhost:11434"
    elif in_docker:
        endpoint = endpoint.replace("://localhost:", "://host.docker.internal:")
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(endpoint.rstrip("/") + "/api/tags")
            if r.status_code == 200:
                data = r.json()
                models = [m.get("name", "?") for m in data.get("models", [])]
                return {"ok": True, "models": models, "endpoint": endpoint}
            return {"ok": False, "error": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"ok": False, "error": f"Unable to connect to Ollama at {endpoint}: {str(e)}"}


@router.get("/status")
async def get_agent_status(
    ctx: dict = Depends(require_role("member")),
):
    start_t = time.time()
    user_id = ctx["user_id"]
    agents = {}
    metrics = {
        "total_runs": 0,
        "successful_runs": 0,
        "failed_runs": 0,
    }

    for domain in AGENT_DOMAINS:
        last_run_row = None
        conversation_count = 0
        last_finding = ""
        domain_total = 0
        domain_success = 0
        domain_failed = 0

        try:
            rows = await bridge._mysql(
                "SELECT id, provider, model, status, duration_ms, "
                "error_message, created_at "
                "FROM ai_agent_runs "
                "WHERE agent_name = %s AND user_id = %s "
                "ORDER BY created_at DESC LIMIT 1",
                (domain, user_id),
            )
            last_run_row = rows[0] if rows else None
        except Exception:
            logger.warning("Failed to query ai_agent_runs for agent=%s", domain)

        try:
            rows = await bridge._mysql(
                "SELECT COUNT(*) as cnt FROM agent_conversations "
                "WHERE agent_name = %s AND user_id = %s",
                (domain, user_id),
            )
            conversation_count = int(rows[0]["cnt"]) if rows else 0
        except Exception:
            logger.warning("Failed to query conversations for agent=%s", domain)

        try:
            rows = await bridge._mysql(
                "SELECT content FROM agent_messages "
                "WHERE conversation_id IN ("
                "  SELECT id FROM agent_conversations "
                "  WHERE agent_name = %s AND user_id = %s "
                "  ORDER BY created_at DESC LIMIT 1"
                ") AND role = 'assistant' "
                "ORDER BY id DESC LIMIT 1",
                (domain, user_id),
            )
            if rows:
                last_finding = (rows[0]["content"] or "")[:300]
        except Exception:
            logger.warning("Failed to query last finding for agent=%s", domain)

        try:
            rows = await bridge._mysql(
                "SELECT COUNT(*) as total, "
                "  SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success, "
                "  SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as failed "
                "FROM ai_agent_runs "
                "WHERE agent_name = %s AND user_id = %s",
                (domain, user_id),
            )
            if rows:
                agg = rows[0]
                domain_total = int(agg["total"] or 0)
                domain_success = int(agg["success"] or 0)
                domain_failed = int(agg["failed"] or 0)
                metrics["total_runs"] += domain_total
                metrics["successful_runs"] += domain_success
                metrics["failed_runs"] += domain_failed
        except Exception:
            logger.warning("Failed to query run counts for agent=%s", domain)

        agent_status = "standby"
        last_run = None
        duration_ms = None
        provider = None
        model = None
        last_error = None

        if last_run_row:
            created_at = last_run_row.get("created_at")
            last_run = created_at.isoformat() if created_at and hasattr(created_at, "isoformat") else (str(created_at) if created_at else None)
            duration_ms = last_run_row.get("duration_ms")
            provider = last_run_row.get("provider")
            model = last_run_row.get("model")
            last_error = last_run_row.get("error_message")

            if last_run_row.get("status") == "error":
                agent_status = "error"
            elif created_at:
                try:
                    age = (datetime.utcnow() - created_at).total_seconds()
                    if age < 300:
                        agent_status = "active"
                except Exception:
                    agent_status = "standby"
        else:
            agent_status = "standby"

        agents[domain] = {
            "status": agent_status,
            "last_run": last_run,
            "duration_ms": duration_ms,
            "provider": provider,
            "model": model,
            "last_error": last_error or None,
            "conversation_count": conversation_count,
            "last_finding": last_finding,
            "total_runs": domain_total,
            "successful_runs": domain_success,
            "failed_runs": domain_failed,
        }

    elapsed = round((time.time() - start_t) * 1000, 1)
    logger.info(
        "Agent status loaded: %d agents, %d total runs, %sms [user=%s]",
        len(agents), metrics["total_runs"], elapsed, user_id,
    )

    return {"agents": agents, "metrics": metrics}


@router.get("/history/{agent_name}")
async def get_agent_history(
    agent_name: str,
    ctx: dict = Depends(require_role("member")),
):
    agent_name = agent_name.strip().lower()
    if agent_name not in AGENT_PROMPTS:
        raise HTTPException(status_code=404, detail=f"Unknown agent: {agent_name}")

    user_id = ctx["user_id"]

    try:
        rows = await bridge._mysql(
            "SELECT id, provider, model, status, duration_ms, "
            "error_message, created_at "
            "FROM ai_agent_runs "
            "WHERE agent_name = %s AND user_id = %s "
            "ORDER BY created_at DESC LIMIT 20",
            (agent_name, user_id),
        )
        # Convert datetime objects to isoformat strings
        result = []
        for r in rows:
            d = dict(r)
            if d.get("created_at"):
                d["created_at"] = d["created_at"].isoformat() if hasattr(d["created_at"], "isoformat") else str(d["created_at"])
            result.append(d)
        return {"history": result}
    except Exception:
        logger.exception("Failed to query history for agent=%s", agent_name)
        raise HTTPException(status_code=500, detail="Failed to load agent history")


@router.get("/metrics/{agent_name}")
async def get_agent_metrics(
    agent_name: str,
    ctx: dict = Depends(require_role("member")),
):
    agent_name = agent_name.strip().lower()
    if agent_name not in AGENT_PROMPTS:
        raise HTTPException(status_code=404, detail=f"Unknown agent: {agent_name}")

    user_id = ctx["user_id"]

    metrics = {
        "total_runs": 0,
        "successful_runs": 0,
        "failed_runs": 0,
        "avg_duration_ms": 0,
        "last_run": None,
        "last_status": None,
        "last_provider": None,
        "last_model": None,
        "last_error": None,
        "conversation_count": 0,
    }

    try:
        rows = await bridge._mysql(
            "SELECT "
            "  COUNT(*) as total_runs, "
            "  SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as successful_runs, "
            "  SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as failed_runs, "
            "  ROUND(AVG(duration_ms)) as avg_duration_ms "
            "FROM ai_agent_runs "
            "WHERE agent_name = %s AND user_id = %s",
            (agent_name, user_id),
        )
        if rows:
            r = rows[0]
            metrics["total_runs"] = int(r["total_runs"] or 0)
            metrics["successful_runs"] = int(r["successful_runs"] or 0)
            metrics["failed_runs"] = int(r["failed_runs"] or 0)
            metrics["avg_duration_ms"] = int(r["avg_duration_ms"] or 0)
    except Exception:
        logger.warning("Failed to query metrics for agent=%s", agent_name)

    try:
        rows = await bridge._mysql(
            "SELECT provider, model, status, duration_ms, error_message, created_at "
            "FROM ai_agent_runs "
            "WHERE agent_name = %s AND user_id = %s "
            "ORDER BY created_at DESC LIMIT 1",
            (agent_name, user_id),
        )
        if rows:
            r = rows[0]
            ca = r.get("created_at")
            metrics["last_run"] = ca.isoformat() if ca and hasattr(ca, "isoformat") else (str(ca) if ca else None)
            metrics["last_status"] = r["status"]
            metrics["last_provider"] = r["provider"]
            metrics["last_model"] = r["model"]
            metrics["last_error"] = r.get("error_message")
    except Exception:
        logger.warning("Failed to query last run for agent=%s", agent_name)

    try:
        rows = await bridge._mysql(
            "SELECT COUNT(*) as cnt FROM agent_conversations "
            "WHERE agent_name = %s AND user_id = %s",
            (agent_name, user_id),
        )
        if rows:
            metrics["conversation_count"] = int(rows[0]["cnt"] or 0)
    except Exception:
        logger.warning("Failed to count conversations for agent=%s", agent_name)

    return metrics


@router.get("/intelligence/context")
async def get_decision_intelligence_context(
    ctx: dict = Depends(require_role("member")),
):
    """Consolidate contextual data across PESTEL, SWOT, Risks, Initiatives, and Decisions

    for the AI Decision Intelligence Layer.
    """
    emp_id = ctx["user_id"]
    try:
        pestel_data, swot_data, risk_data, init_data, decision_data = await asyncio.gather(
            bridge.get(bridge.db_service, "/pestelList"),
            bridge.get(bridge.db_service, "/swotList"),
            bridge._mysql("SELECT ID, risk_value, owner, status, page_name FROM risk_details WHERE active = 1"),
            bridge.get(bridge.db_service, "/initiativesList/"),
            bridge.get(bridge.db_service, "/decisions"),
        )
    except Exception as exc:
        logger.warning("Intelligence context gather warning: %s", exc)
        pestel_data, swot_data, risk_data, init_data, decision_data = [], [], [], [], []

    pestels = pestel_data if isinstance(pestel_data, list) else (pestel_data.get("items", []) if isinstance(pestel_data, dict) else [])
    swots = swot_data if isinstance(swot_data, list) else (swot_data.get("items", []) if isinstance(swot_data, dict) else [])
    inits = init_data if isinstance(init_data, list) else (init_data.get("initiatives", []) if isinstance(init_data, dict) else [])
    decisions = decision_data if isinstance(decision_data, list) else (decision_data.get("decisions", []) if isinstance(decision_data, dict) else [])

    risks_parsed = []
    for r in (risk_data or []):
        rv = bridge._parse_json_col(r, "risk_value")
        risks_parsed.append({
            "id": r.get("ID"),
            "name": rv.get("name") or rv.get("title", ""),
            "score": rv.get("score") or 0,
            "owner": r.get("owner"),
            "page_name": r.get("page_name"),
        })

    return {
        "pestel": pestels,
        "swot": swots,
        "risks": risks_parsed,
        "initiatives": inits,
        "decisions": decisions,
        "timestamp": datetime.now().isoformat(),
    }

