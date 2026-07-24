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
from app.agents.task_tools import query_user_tasks, update_task_progress

AGENT_DOMAINS = [
    "strategy", "risk", "finance", "compliance", "audit",
    "task", "meetings", "projects", "incident",
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
        if len(v) > settings.MAX_PROMPT_LENGTH:
            raise ValueError(f"Message exceeds maximum length of {settings.MAX_PROMPT_LENGTH}")
        return v

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in settings.ALLOWED_PROVIDERS:
            raise ValueError(f"Unsupported provider: {v}. Allowed: {', '.join(sorted(settings.ALLOWED_PROVIDERS))}")
        return v

    @field_validator("model")
    @classmethod
    def validate_model(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Model name is required")
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

    runner = AgentRunner(req.agent)
    try:
        if req.conversation_id:
            ownership = await db.execute(
                text("SELECT id FROM agent_conversations WHERE id = :cid AND user_id = :uid"),
                {"cid": req.conversation_id, "uid": user_id},
            )
            if not ownership.first():
                raise HTTPException(status_code=404, detail="Conversation not found")

        result = await runner.run(
            db=db,
            user_message=req.message,
            provider=req.provider,
            api_key=req.api_key,
            model=req.model,
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


class TaskActionRequest(BaseModel):
    action: str  # 'query' or 'update'
    task_id: Optional[int] = None
    status: Optional[str] = None
    priority: Optional[str] = None


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
            )
            return result

        elif req.action == "update":
            if not req.task_id:
                raise HTTPException(status_code=422, detail="task_id is required for update action")
            result = await update_task_progress(
                db, user_id, org_id, req.task_id, req.status, is_admin,
            )
            if "error" in result:
                raise HTTPException(status_code=404, detail=result["error"])
            return result

        else:
            raise HTTPException(status_code=422, detail=f"Unknown action: {req.action}. Use 'query' or 'update'.")

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Task action failed [user=%s action=%s]", user_id, req.action)
        raise HTTPException(status_code=500, detail="Task action failed. Please try again later.")


@router.get("/conversations")
async def list_conversations(
    agent: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("member")),
):
    user_id = ctx["user_id"]
    org_id = ctx["org_id"]

    if agent:
        result = await db.execute(
            text(
                "SELECT id, agent_name, title, created_at "
                "FROM agent_conversations WHERE agent_name = :agent "
                "AND user_id = :uid AND org_id = :oid "
                "ORDER BY created_at DESC LIMIT 50"
            ),
            {"agent": agent, "uid": user_id, "oid": org_id},
        )
    else:
        result = await db.execute(
            text(
                "SELECT id, agent_name, title, created_at "
                "FROM agent_conversations WHERE user_id = :uid AND org_id = :oid "
                "ORDER BY created_at DESC LIMIT 50"
            ),
            {"uid": user_id, "oid": org_id},
        )
    rows = result.mappings().all()
    return {"conversations": [dict(r) for r in rows]}


@router.get("/messages/{conversation_id}")
async def get_messages(
    conversation_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("member")),
):
    user_id = ctx["user_id"]

    ownership = await db.execute(
        text("SELECT id FROM agent_conversations WHERE id = :cid AND user_id = :uid"),
        {"cid": conversation_id, "uid": user_id},
    )
    if not ownership.first():
        raise HTTPException(status_code=404, detail="Conversation not found")

    result = await db.execute(
        text(
            "SELECT id, role, content, created_at "
            "FROM agent_messages WHERE conversation_id = :cid ORDER BY id"
        ),
        {"cid": conversation_id},
    )
    rows = result.mappings().all()
    return {"messages": [dict(r) for r in rows]}


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("member")),
):
    user_id = ctx["user_id"]

    ownership = await db.execute(
        text("SELECT id FROM agent_conversations WHERE id = :cid AND user_id = :uid"),
        {"cid": conversation_id, "uid": user_id},
    )
    if not ownership.first():
        raise HTTPException(status_code=404, detail="Conversation not found")

    await db.execute(
        text("DELETE FROM agent_messages WHERE conversation_id = :cid"),
        {"cid": conversation_id},
    )
    await db.execute(
        text("DELETE FROM agent_conversations WHERE id = :cid AND user_id = :uid"),
        {"cid": conversation_id, "uid": user_id},
    )
    await db.commit()
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
    db: AsyncSession = Depends(get_db),
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
            result = await db.execute(
                text(
                    "SELECT id, provider, model, status, duration_ms, "
                    "error_message, created_at "
                    "FROM ai_agent_runs "
                    "WHERE agent_name = :agent AND user_id = :uid "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"agent": domain, "uid": user_id},
            )
            last_run_row = result.mappings().first()
        except Exception:
            logger.warning("Failed to query ai_agent_runs for agent=%s", domain)

        try:
            result = await db.execute(
                text(
                    "SELECT COUNT(*) FROM agent_conversations "
                    "WHERE agent_name = :agent AND user_id = :uid"
                ),
                {"agent": domain, "uid": user_id},
            )
            conversation_count = result.scalar() or 0
        except Exception:
            logger.warning("Failed to query conversations for agent=%s", domain)

        try:
            result = await db.execute(
                text(
                    "SELECT content FROM agent_messages "
                    "WHERE conversation_id IN ("
                    "  SELECT id FROM agent_conversations "
                    "  WHERE agent_name = :agent AND user_id = :uid "
                    "  ORDER BY created_at DESC LIMIT 1"
                    ") AND role = 'assistant' "
                    "ORDER BY id DESC LIMIT 1"
                ),
                {"agent": domain, "uid": user_id},
            )
            row = result.mappings().first()
            if row:
                last_finding = (row["content"] or "")[:300]
        except Exception:
            logger.warning("Failed to query last finding for agent=%s", domain)

        try:
            result = await db.execute(
                text(
                    "SELECT COUNT(*) as total, "
                    "  SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success, "
                    "  SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as failed "
                    "FROM ai_agent_runs "
                    "WHERE agent_name = :agent AND user_id = :uid"
                ),
                {"agent": domain, "uid": user_id},
            )
            agg = result.mappings().first()
            if agg:
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
            last_run = last_run_row["created_at"].isoformat() if last_run_row["created_at"] else None
            duration_ms = last_run_row["duration_ms"]
            provider = last_run_row["provider"]
            model = last_run_row["model"]
            last_error = last_run_row["error_message"]

            if last_run_row["status"] == "error":
                agent_status = "error"
            elif last_run_row["created_at"]:
                age = (datetime.utcnow() - last_run_row["created_at"].replace(tzinfo=None)).total_seconds()
                if age < 300:
                    agent_status = "active"
                else:
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
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("member")),
):
    agent_name = agent_name.strip().lower()
    if agent_name not in AGENT_PROMPTS:
        raise HTTPException(status_code=404, detail=f"Unknown agent: {agent_name}")

    user_id = ctx["user_id"]

    try:
        result = await db.execute(
            text(
                "SELECT id, provider, model, status, duration_ms, "
                "error_message, created_at "
                "FROM ai_agent_runs "
                "WHERE agent_name = :agent AND user_id = :uid "
                "ORDER BY created_at DESC LIMIT 20"
            ),
            {"agent": agent_name, "uid": user_id},
        )
        rows = result.mappings().all()
        return {"history": [dict(r) for r in rows]}
    except Exception:
        logger.exception("Failed to query history for agent=%s", agent_name)
        raise HTTPException(status_code=500, detail="Failed to load agent history")


@router.get("/metrics/{agent_name}")
async def get_agent_metrics(
    agent_name: str,
    db: AsyncSession = Depends(get_db),
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
        result = await db.execute(
            text(
                "SELECT "
                "  COUNT(*) as total_runs, "
                "  SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as successful_runs, "
                "  SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as failed_runs, "
                "  ROUND(AVG(duration_ms)) as avg_duration_ms "
                "FROM ai_agent_runs "
                "WHERE agent_name = :agent AND user_id = :uid"
            ),
            {"agent": agent_name, "uid": user_id},
        )
        row = result.mappings().first()
        if row:
            metrics["total_runs"] = row["total_runs"] or 0
            metrics["successful_runs"] = row["successful_runs"] or 0
            metrics["failed_runs"] = row["failed_runs"] or 0
            metrics["avg_duration_ms"] = int(row["avg_duration_ms"] or 0)
    except Exception:
        logger.warning("Failed to query metrics for agent=%s", agent_name)

    try:
        result = await db.execute(
            text(
                "SELECT provider, model, status, duration_ms, error_message, created_at "
                "FROM ai_agent_runs "
                "WHERE agent_name = :agent AND user_id = :uid "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"agent": agent_name, "uid": user_id},
        )
        row = result.mappings().first()
        if row:
            metrics["last_run"] = row["created_at"].isoformat() if row["created_at"] else None
            metrics["last_status"] = row["status"]
            metrics["last_provider"] = row["provider"]
            metrics["last_model"] = row["model"]
            metrics["last_error"] = row["error_message"]
    except Exception:
        logger.warning("Failed to query last run for agent=%s", agent_name)

    try:
        result = await db.execute(
            text(
                "SELECT COUNT(*) FROM agent_conversations "
                "WHERE agent_name = :agent AND user_id = :uid"
            ),
            {"agent": agent_name, "uid": user_id},
        )
        metrics["conversation_count"] = result.scalar() or 0
    except Exception:
        logger.warning("Failed to count conversations for agent=%s", agent_name)

    return metrics
