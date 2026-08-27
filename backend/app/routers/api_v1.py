import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import require_role, get_current_user, get_current_user_with_employee
from app.core.security import create_access_token
from app.services.java_bridge import bridge
from app.core.rbac import resolve_rbac_role

logger = logging.getLogger("stratroom.api_v1")

router = APIRouter(prefix="/api/v1", tags=["api_v1"])


class V1LoginRequest(BaseModel):
    email: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ── Phase 2: Passwordless Auth ──

@router.post("/auth/login", response_model=TokenResponse)
async def v1_auth_login(payload: V1LoginRequest):
    email = payload.email.strip().lower()
    from app.services.java_bridge import bridge

    rows = await bridge._mysql(
        "SELECT email FROM users WHERE LOWER(email) = %s",
        (email,),
    )
    if rows:
        return TokenResponse(access_token=create_access_token(email))

    try:
        users = await bridge.get(bridge.user_service, "/userList") or []
        if isinstance(users, dict):
            users = users.get("users", users.get("list", []))
        for u in users:
            if isinstance(u, dict) and str(u.get("email_address", "")).lower() == email:
                return TokenResponse(access_token=create_access_token(u["email_address"]))
    except Exception:
        pass

    raise HTTPException(status_code=401, detail="User not found")


# ── Existing kpis endpoint ──

@router.get("/dashboard/kpis")
async def v1_dashboard_kpis(
    ctx: dict = Depends(require_role("member")),
):
    org_id = ctx["org_id"]
    row = {"total": 0, "on_track": 0, "critical": 0, "at_risk": 0}
    try:
        from app.routers.scorecards import JUNK_KPIS_SQL
        rows = await bridge._mysql(
            "SELECT status FROM scorecard_kpis WHERE id IN ("
            f"SELECT MIN(id) FROM scorecard_kpis WHERE org_id = %s {JUNK_KPIS_SQL} "
            "GROUP BY perspective, kpi_name, target, actual, status"
            ")",
            (org_id,),
        )
        for r in rows or []:
            row["total"] += 1
            st = (r.get("status") or "").lower().strip()
            if st in ("on-track", "on track", "completed", "on_target"):
                row["on_track"] += 1
            elif st in ("at-risk", "at risk", "overdue", "warning"):
                row["at_risk"] += 1
            elif st in ("critical", "off-track", "off_track", "missed"):
                row["critical"] += 1
    except Exception as exc:
        logger.warning("v1_kpis query failed for org=%s: %s", org_id, exc)
    return {
        "total": int(row["total"]),
        "on_track": int(row["on_track"]),
        "critical": int(row["critical"]),
        "at_risk": int(row["at_risk"]),
    }


# ── Chat ──

@router.post("/chat/")
async def v1_chat(
    payload: dict,
    identity: dict = Depends(get_current_user_with_employee),
):
    try:
        result = await bridge.post(
            bridge.db_service, "/chat",
            json={"prompt": payload.get("prompt", ""),
                  "project_id": payload.get("project_id"),
                  "org_id": identity.get("org_id"),
                  "mode": payload.get("mode", "general"),
                  "session_id": payload.get("session_id"),
                  "user_email": identity.get("email")},
        )
        return result if isinstance(result, dict) else {"response": str(result)}
    except Exception as exc:
        logger.warning("Chat bridge call failed: %s", exc)
        return {"response": "AI chat is currently unavailable."}


# ── Sessions / Suggested Tasks ──

@router.get("/sessions/suggested-tasks")
async def v1_suggested_tasks(
    emp_id: str = "",
    status: str = "",
    page: int = 1,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("member")),
):
    org_id = ctx["org_id"]
    params = {"oid": org_id, "limit": limit, "offset": (page - 1) * limit}
    conditions = ""
    if emp_id:
        conditions += " AND (assigned_user_id = :eid::integer OR owner = :eid)"
        params["eid"] = emp_id
    if status:
        conditions += " AND status = :st"
        params["st"] = status
    result = await db.execute(
        text(f"SELECT * FROM tasks WHERE org_id = :oid{conditions} ORDER BY created_at DESC LIMIT :limit OFFSET :offset"),
        params,
    )
    rows = [dict(r) for r in result.mappings().all()]
    return {"tasks": rows, "page": page, "limit": limit}


@router.get("/sessions/")
async def v1_sessions(
    emp_id: str = "",
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("member")),
):
    org_id = ctx["org_id"]
    if emp_id:
        result = await db.execute(
            text("SELECT * FROM tasks WHERE org_id = :oid AND (assigned_user_id = :eid::integer OR owner = :eid) ORDER BY created_at DESC"),
            {"oid": org_id, "eid": emp_id},
        )
    else:
        result = await db.execute(
            text("SELECT * FROM tasks WHERE org_id = :oid ORDER BY created_at DESC LIMIT 100"),
            {"oid": org_id},
        )
    rows = [dict(r) for r in result.mappings().all()]
    return {"sessions": rows}


# ── Task Approve / Reject ──

@router.post("/tasks/approve")
async def v1_tasks_approve(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("member")),
):
    org_id = ctx["org_id"]
    task_id = payload.get("task_id")
    if not task_id:
        raise HTTPException(status_code=400, detail="task_id required")
    await db.execute(
        text("UPDATE tasks SET status = 'approved' WHERE id = :id AND org_id = :oid"),
        {"id": task_id, "oid": org_id},
    )
    await db.commit()
    return {"status": "approved"}


@router.post("/tasks/approve-all")
async def v1_tasks_approve_all(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("member")),
):
    org_id = ctx["org_id"]
    ids = payload.get("task_ids", [])
    if not ids:
        raise HTTPException(status_code=400, detail="task_ids required")
    await db.execute(
        text("UPDATE tasks SET status = 'approved' WHERE id = ANY(:ids) AND org_id = :oid"),
        {"ids": ids, "oid": org_id},
    )
    await db.commit()
    return {"status": "approved", "count": len(ids)}


@router.post("/tasks/reject/{task_id}")
async def v1_tasks_reject(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("member")),
):
    org_id = ctx["org_id"]
    await db.execute(
        text("UPDATE tasks SET status = 'rejected' WHERE id = :id AND org_id = :oid"),
        {"id": task_id, "oid": org_id},
    )
    await db.commit()
    return {"status": "rejected", "task_id": task_id}


@router.get("/tasks/modules")
async def v1_tasks_modules(
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("member")),
):
    org_id = ctx["org_id"]
    result = await db.execute(
        text("SELECT DISTINCT agent FROM tasks WHERE org_id = :oid AND agent IS NOT NULL ORDER BY agent"),
        {"oid": org_id},
    )
    modules = [r[0] for r in result.fetchall()]
    return {"modules": modules}


# ── Dashboard ──

@router.get("/dashboard/summary")
async def v1_dashboard_summary(
    ctx: dict = Depends(require_role("member")),
):
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]
    is_admin = ctx["is_admin"]

    async def _safe_get(service, path, default=None):
        try:
            data = await bridge.get(service, path)
            return data or default
        except Exception as exc:
            logger.warning("bridge get %s failed: %s", path, exc)
            return default

    def to_list(data):
        if data is None:
            return []
        return data if isinstance(data, list) else data.get("list", data.get("data", []))

    risks_list = to_list(await _safe_get(bridge.db_service, "/riskListView"))
    initiatives_list = to_list(await _safe_get(bridge.db_service, "/initiativesList/"))
    incidents_list = to_list(await _safe_get(bridge.db_service, "/universalIncidentList"))
    scorecards_list = to_list(await _safe_get(bridge.db_service, "/scoreCardList"))
    users_list = to_list(await _safe_get(bridge.user_service, "/userList"))
    audits_list = to_list(await _safe_get(bridge.db_service, "/auditManagementList"))

    audit_ratings = [a.get("rating", "").strip().lower() for a in audits_list if a.get("rating")]
    passing = sum(1 for r in audit_ratings if r in ("low", "medium"))
    compliance_score = round(passing / len(audit_ratings) * 100, 1) if audit_ratings else 0.0

    tasks_data = await _safe_get(bridge.db_service, f"/retrieveTaskList/{user_id}") or []
    tasks_list = tasks_data if isinstance(tasks_data, list) else tasks_data.get("tasks", tasks_data.get("list", []))
    total_tasks = len(tasks_list)

    return {
        "total_risks": len(risks_list),
        "total_initiatives": len(initiatives_list),
        "total_incidents": len(incidents_list),
        "open_incidents": sum(1 for i in incidents_list if (i.get("status") or "").lower() != "resolved"),
        "total_scorecards": len(scorecards_list),
        "active_org_members": len(users_list),
        "total_tasks": total_tasks,
        "compliance_score": compliance_score,
        "rbac_role": ctx.get("rbac_role", "member"),
    }


@router.get("/dashboard/compliance")
async def v1_dashboard_compliance(
    ctx: dict = Depends(require_role("member")),
):
    try:
        data = await bridge.get(bridge.db_service, "/compliance")
        if isinstance(data, dict):
            data = data.get("list", data.get("data", data))
    except Exception as exc:
        logger.warning("compliance bridge failed: %s", exc)
        data = []
    return {"compliance": data if isinstance(data, list) else []}


# ── Organization ──

@router.get("/organization/structure")
async def v1_organization_structure(
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("member")),
):
    from app.routers.org import get_org_full
    return await get_org_full(db=db, ctx=ctx)


# ── AI Insights (proxied via JavaBridge) ──

@router.post("/ai-insights/signals")
async def v1_ai_signals(payload: dict, identity: dict = Depends(get_current_user_with_employee)):
    return _bridge_ai_call("/ai/signals", payload, identity)


@router.post("/ai-insights/recommendations")
async def v1_ai_recommendations(payload: dict, identity: dict = Depends(get_current_user_with_employee)):
    return _bridge_ai_call("/ai/recommendations", payload, identity)


@router.post("/ai-insights/analysis")
async def v1_ai_analysis(payload: dict, identity: dict = Depends(get_current_user_with_employee)):
    return _bridge_ai_call("/ai/analysis", payload, identity)


@router.post("/ai-insights/tasks")
async def v1_ai_tasks(payload: dict, identity: dict = Depends(get_current_user_with_employee)):
    return _bridge_ai_call("/ai/tasks", payload, identity)


async def _bridge_ai_call(path: str, payload: dict, identity: dict) -> dict:
    try:
        payload["org_id"] = identity.get("org_id")
        payload["user_email"] = identity.get("email")
        result = await bridge.post(bridge.db_service, path, json=payload)
        return result if isinstance(result, dict) else {"result": result}
    except Exception as exc:
        logger.warning("AI insights call %s failed: %s", path, exc)
        return {"result": None, "error": str(exc)}


# ── Entity Management (aliased to PostgreSQL) ──

@router.get("/incidents/")
async def v1_incidents(
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("member")),
):
    org_id = ctx["org_id"]
    result = await db.execute(
        text("SELECT * FROM incidents WHERE org_id = :oid ORDER BY created_at DESC"),
        {"oid": org_id},
    )
    return {"incidents": [dict(r) for r in result.mappings().all()]}


@router.get("/audit/")
async def v1_audit_list(
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("member")),
):
    org_id = ctx["org_id"]
    result = await db.execute(
        text("SELECT * FROM audit_findings WHERE org_id = :oid ORDER BY created_at DESC"),
        {"oid": org_id},
    )
    return {"audit": [dict(r) for r in result.mappings().all()]}


@router.put("/audit/{finding_id}")
async def v1_audit_update(
    finding_id: int,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("member")),
):
    org_id = ctx["org_id"]
    allowed = {"title", "severity", "owner", "due_date", "status"}
    set_clauses = []
    params = {"id": finding_id, "oid": org_id}
    for k, v in payload.items():
        if k in allowed:
            set_clauses.append(f"{k} = :{k}")
            params[k] = v
    if not set_clauses:
        raise HTTPException(status_code=400, detail="No valid fields to update")
    await db.execute(
        text(f"UPDATE audit_findings SET {', '.join(set_clauses)} WHERE id = :id AND org_id = :oid"),
        params,
    )
    await db.commit()
    return {"status": "updated", "id": finding_id}


@router.get("/meetings/")
async def v1_meetings(
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("member")),
):
    org_id = ctx["org_id"]
    result = await db.execute(
        text("SELECT * FROM meetings WHERE org_id = :oid ORDER BY meeting_date DESC"),
        {"oid": org_id},
    )
    return {"meetings": [dict(r) for r in result.mappings().all()]}


@router.get("/initiatives/")
async def v1_initiatives(
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("member")),
):
    org_id = ctx["org_id"]
    result = await db.execute(
        text("SELECT * FROM initiatives WHERE org_id = :oid ORDER BY created_at DESC"),
        {"oid": org_id},
    )
    return {"initiatives": [dict(r) for r in result.mappings().all()]}


@router.get("/risk/register")
async def v1_risk_register(
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("member")),
):
    org_id = ctx["org_id"]
    result = await db.execute(
        text("SELECT * FROM risks WHERE org_id = :oid ORDER BY created_at DESC"),
        {"oid": org_id},
    )
    return {"risks": [dict(r) for r in result.mappings().all()]}
