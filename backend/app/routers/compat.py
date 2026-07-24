"""
Compatibility Router — maps legacy frontend API paths to actual backend logic.

The frontend (31may_index.html) was originally built for a different backend
and calls endpoints like /stratroom/riskList/1, /stratroom/scoreCardList, etc.
This router translates those calls to the actual FastAPI database logic.
"""

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import require_role

logger = logging.getLogger("stratroom.compat")

router = APIRouter(prefix="/stratroom", tags=["compat"])


# ── Master Value (GL accounts, dropdown data) ──
@router.get("/masterValue")
async def compat_master_value(
    value_type: str = Query(default="", alias="type"),
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("member")),
):
    org_id = ctx["org_id"]

    if value_type == "GL_ACCOUNT":
        result = await db.execute(
            text(
                "SELECT DISTINCT gl_account, gl_name "
                "FROM budget_lines WHERE org_id = :oid "
                "AND gl_account IS NOT NULL "
                "ORDER BY gl_account"
            ),
            {"oid": org_id},
        )
        rows = result.mappings().all()
        return {"values": [dict(r) for r in rows]}

    return {"values": []}


# ── Scorecards ──
@router.get("/scoreCardList")
async def compat_scorecard_list(
    limit: int = Query(default=0),
    pageId: int = Query(default=0),
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("member")),
):
    org_id = ctx["org_id"]
    is_admin = ctx["is_admin"]
    is_manager = ctx["is_manager"]
    user_id = ctx["user_id"]

    if is_admin or is_manager:
        result = await db.execute(
            text(
                "SELECT id, perspective, kpi_name, target, actual, owner, status, assigned_user_id "
                "FROM scorecards WHERE org_id = :oid ORDER BY id"
            ),
            {"oid": org_id},
        )
    else:
        result = await db.execute(
            text(
                "SELECT id, perspective, kpi_name, target, actual, owner, status, assigned_user_id "
                "FROM scorecards WHERE org_id = :oid AND assigned_user_id = :uid ORDER BY id"
            ),
            {"oid": org_id, "uid": user_id},
        )
    rows = result.mappings().all()
    data = [dict(r) for r in rows]
    if limit > 0:
        data = data[:limit]
    return {"scorecards": data}


# ── Risk List ──
@router.get("/riskList/{emp_id}")
async def compat_risk_list(
    emp_id: int,
    pageId: int = Query(default=0),
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("member")),
):
    org_id = ctx["org_id"]
    is_admin = ctx["is_admin"]
    is_manager = ctx["is_manager"]

    if is_admin or is_manager:
        result = await db.execute(
            text(
                "SELECT id, name, owner, inherent_likelihood, inherent_impact, "
                "residual_likelihood, residual_impact, description, mitigation "
                "FROM risks WHERE org_id = :oid ORDER BY created_at DESC"
            ),
            {"oid": org_id},
        )
    else:
        result = await db.execute(
            text(
                "SELECT id, name, owner, inherent_likelihood, inherent_impact, "
                "residual_likelihood, residual_impact, description, mitigation "
                "FROM risks WHERE org_id = :oid AND owner = :owner ORDER BY created_at DESC"
            ),
            {"oid": org_id, "owner": ctx["email"]},
        )
    rows = result.mappings().all()
    return {"risks": [dict(r) for r in rows]}


# ── KPI List (returns scorecard summary by perspective) ──
@router.get("/kpiList/{emp_id}")
async def compat_kpi_list(
    emp_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("member")),
):
    org_id = ctx["org_id"]
    is_admin = ctx["is_admin"]
    is_manager = ctx["is_manager"]
    user_id = ctx["user_id"]

    if is_admin or is_manager:
        result = await db.execute(
            text(
                "SELECT perspective, "
                "ROUND(AVG(actual)) as avg_score, "
                "COUNT(*) as kpi_count, "
                "SUM(CASE WHEN status = 'on-track' THEN 1 ELSE 0 END) as on_track, "
                "SUM(CASE WHEN status = 'at-risk' THEN 1 ELSE 0 END) as at_risk, "
                "SUM(CASE WHEN status = 'critical' THEN 1 ELSE 0 END) as critical "
                "FROM scorecards WHERE org_id = :oid "
                "GROUP BY perspective ORDER BY MIN(id)"
            ),
            {"oid": org_id},
        )
    else:
        result = await db.execute(
            text(
                "SELECT perspective, "
                "ROUND(AVG(actual)) as avg_score, "
                "COUNT(*) as kpi_count, "
                "SUM(CASE WHEN status = 'on-track' THEN 1 ELSE 0 END) as on_track, "
                "SUM(CASE WHEN status = 'at-risk' THEN 1 ELSE 0 END) as at_risk, "
                "SUM(CASE WHEN status = 'critical' THEN 1 ELSE 0 END) as critical "
                "FROM scorecards WHERE org_id = :oid AND assigned_user_id = :uid "
                "GROUP BY perspective ORDER BY MIN(id)"
            ),
            {"oid": org_id, "uid": user_id},
        )
    rows = result.mappings().all()
    return {"kpis": [dict(r) for r in rows]}


# ── Initiatives List ──
@router.get("/initiativesList")
async def compat_initiatives_list(
    pageId: int = Query(default=0),
    loadFlag: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("member")),
):
    org_id = ctx["org_id"]
    result = await db.execute(
        text(
            "SELECT id, name, percent_complete, budget_planned, budget_actual, status "
            "FROM initiatives WHERE org_id = :oid ORDER BY id"
        ),
        {"oid": org_id},
    )
    rows = result.mappings().all()
    return {"initiatives": [dict(r) for r in rows]}


# ── Budgets List ──
@router.get("/budgetsList/{page_id}")
async def compat_budgets_list(
    page_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("member")),
):
    org_id = ctx["org_id"]
    is_admin = ctx["is_admin"]
    is_manager = ctx["is_manager"]

    if is_admin or is_manager:
        result = await db.execute(
            text(
                "SELECT id, year, month, gl_account, gl_name, budget_type, project, total, department, employee, notes "
                "FROM budget_lines WHERE org_id = :oid ORDER BY year, id"
            ),
            {"oid": org_id},
        )
    else:
        result = await db.execute(
            text(
                "SELECT id, year, month, gl_account, gl_name, budget_type, project, total, department, employee, notes "
                "FROM budget_lines WHERE org_id = :oid AND employee = :email ORDER BY year, id"
            ),
            {"oid": org_id, "email": ctx["email"]},
        )
    rows = result.mappings().all()
    return {"budgets": [dict(r) for r in rows]}


# ── Audit Management List ──
@router.get("/auditManagementList")
async def compat_audit_list(
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("member")),
):
    org_id = ctx["org_id"]
    is_admin = ctx["is_admin"]
    is_manager = ctx["is_manager"]
    user_id = ctx["user_id"]

    if is_admin or is_manager:
        result = await db.execute(
            text(
                "SELECT id, title, severity, owner, due_date, status, assigned_user_id "
                "FROM audit_findings WHERE org_id = :oid "
                "ORDER BY CASE severity WHEN 'Critical' THEN 1 WHEN 'High' THEN 2 WHEN 'Medium' THEN 3 ELSE 4 END, id"
            ),
            {"oid": org_id},
        )
    else:
        result = await db.execute(
            text(
                "SELECT id, title, severity, owner, due_date, status, assigned_user_id "
                "FROM audit_findings WHERE org_id = :oid AND assigned_user_id = :uid "
                "ORDER BY CASE severity WHEN 'Critical' THEN 1 WHEN 'High' THEN 2 WHEN 'Medium' THEN 3 ELSE 4 END, id"
            ),
            {"oid": org_id, "uid": user_id},
        )
    rows = result.mappings().all()
    return {"findings": [dict(r) for r in rows]}


# ── Risk Event List (incidents) ──
@router.get("/riskeventlist")
async def compat_risk_event_list(
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("member")),
):
    org_id = ctx["org_id"]
    result = await db.execute(
        text(
            "SELECT id, code, title, severity, status, region, mttr_hours, sla_hours "
            "FROM incidents WHERE org_id = :oid ORDER BY created_at DESC"
        ),
        {"oid": org_id},
    )
    rows = result.mappings().all()
    return {"incidents": [dict(r) for r in rows]}


# ── Retrieve Task List ──
@router.get("/retrieveTaskList/{emp_id}")
async def compat_task_list(
    emp_id: int,
    dateRange: str = Query(default="current"),
    task_type: str = Query(default="all", alias="type"),
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("member")),
):
    org_id = ctx["org_id"]
    is_admin = ctx["is_admin"]
    is_manager = ctx["is_manager"]
    user_id = ctx["user_id"]

    if is_admin or is_manager:
        result = await db.execute(
            text(
                "SELECT id, title, agent, priority, owner, due_date, status, assigned_user_id "
                "FROM tasks WHERE org_id = :oid "
                "ORDER BY CASE priority WHEN 'Critical' THEN 1 WHEN 'High' THEN 2 WHEN 'Medium' THEN 3 ELSE 4 END, id"
            ),
            {"oid": org_id},
        )
    else:
        result = await db.execute(
            text(
                "SELECT id, title, agent, priority, owner, due_date, status, assigned_user_id "
                "FROM tasks WHERE org_id = :oid AND assigned_user_id = :uid "
                "ORDER BY CASE priority WHEN 'Critical' THEN 1 WHEN 'High' THEN 2 WHEN 'Medium' THEN 3 ELSE 4 END, id"
            ),
            {"oid": org_id, "uid": user_id},
        )
    rows = result.mappings().all()
    return {"tasks": [dict(r) for r in rows]}


# ── Meeting Management List ──
@router.get("/meetingManagementList/{emp_id}")
async def compat_meeting_list(
    emp_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("member")),
):
    org_id = ctx["org_id"]
    is_admin = ctx["is_admin"]
    is_manager = ctx["is_manager"]

    if is_admin or is_manager:
        result = await db.execute(
            text(
                "SELECT id, title, meeting_date, meeting_time, location, duration, attendees, priority "
                "FROM meetings WHERE org_id = :oid ORDER BY id"
            ),
            {"oid": org_id},
        )
    else:
        email = ctx["email"]
        result = await db.execute(
            text(
                "SELECT id, title, meeting_date, meeting_time, location, duration, attendees, priority "
                "FROM meetings WHERE org_id = :oid AND attendees ILIKE :email ORDER BY id"
            ),
            {"oid": org_id, "email": f"%{email}%"},
        )
    rows = result.mappings().all()
    return {"meetings": [dict(r) for r in rows]}


# ── Retrieve Compliance Value ──
@router.get("/retrieveComplinValue")
async def compat_compliance_list(
    dateRange: str = Query(default="current"),
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("member")),
):
    org_id = ctx["org_id"]
    result = await db.execute(
        text(
            "SELECT id, name, description, score, status "
            "FROM compliance_frameworks WHERE org_id = :oid ORDER BY id"
        ),
        {"oid": org_id},
    )
    rows = result.mappings().all()
    return {"compliance": [dict(r) for r in rows]}
