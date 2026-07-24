import logging

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import require_role
from app.core.utils import resolve_full_identity
from app.core.rbac import resolve_rbac_role

logger = logging.getLogger("stratroom.dashboard")

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/stats")
async def get_stats(db: AsyncSession = Depends(get_db), ctx: dict = Depends(require_role("member"))):
    org_id = ctx["org_id"]
    is_admin = ctx["is_admin"]
    is_manager = ctx["is_manager"]
    user_id = ctx["user_id"]

    counts = await db.execute(
        text(
            "SELECT "
            "(SELECT COUNT(*) FROM risks WHERE org_id = :oid) AS total_risks, "
            "(SELECT COUNT(*) FROM incidents WHERE org_id = :oid) AS total_incidents, "
            "(SELECT COUNT(*) FROM incidents WHERE org_id = :oid AND status != 'resolved') AS open_incidents, "
            "(SELECT COUNT(*) FROM initiatives WHERE org_id = :oid) AS total_initiatives, "
            "(SELECT COALESCE(AVG(percent_complete), 0) FROM initiatives WHERE org_id = :oid) AS avg_progress, "
            "(SELECT COALESCE(SUM(budget_planned), 0) FROM initiatives WHERE org_id = :oid) AS budget_planned, "
            "(SELECT COALESCE(SUM(budget_actual), 0) FROM initiatives WHERE org_id = :oid) AS budget_actual, "
            "(SELECT COUNT(*) FROM incidents WHERE org_id = :oid AND severity = 'P1' AND status != 'resolved') AS p1_open, "
            "(SELECT COUNT(*) FROM risks WHERE org_id = :oid AND (inherent_likelihood * inherent_impact) >= 12) AS high_risks"
        ),
        {"oid": org_id},
    )
    c = counts.mappings().one()

    breakdowns = await db.execute(
        text(
            "SELECT 'severity' AS btype, severity AS key, COUNT(*) AS val "
            "FROM incidents WHERE org_id = :oid GROUP BY severity "
            "UNION ALL "
            "SELECT 'region' AS btype, region AS key, COUNT(*) AS val "
            "FROM incidents WHERE org_id = :oid AND region IS NOT NULL GROUP BY region"
        ),
        {"oid": org_id},
    )
    severity_map = {}
    region_map = {}
    for row in breakdowns.mappings().all():
        if row["btype"] == "severity":
            severity_map[row["key"]] = row["val"]
        else:
            region_map[row["key"]] = row["val"]

    org_stats = await db.execute(
        text(
            "SELECT "
            "(SELECT COALESCE(AVG(score), 0) FROM compliance_frameworks WHERE org_id = :oid) AS compliance_avg, "
            "(SELECT COUNT(*) FROM org_members WHERE org_id = :oid) AS org_members, "
            "(SELECT COUNT(*) FROM scorecards WHERE org_id = :oid) AS total_scorecards"
        ),
        {"oid": org_id},
    )
    o = org_stats.mappings().one()

    if is_admin or is_manager:
        task_count = await db.execute(
            text("SELECT COUNT(*) as cnt FROM tasks WHERE org_id = :oid"),
            {"oid": org_id},
        )
    else:
        task_count = await db.execute(
            text("SELECT COUNT(*) as cnt FROM tasks WHERE org_id = :oid AND assigned_user_id = :uid"),
            {"oid": org_id, "uid": user_id},
        )
    total_tasks = task_count.scalar()

    return {
        "total_risks": c["total_risks"],
        "total_incidents": c["total_incidents"],
        "open_incidents": c["open_incidents"],
        "total_initiatives": c["total_initiatives"],
        "avg_progress": round(float(c["avg_progress"]), 1),
        "budget_planned": float(c["budget_planned"]),
        "budget_actual": float(c["budget_actual"]),
        "p1_open": c["p1_open"],
        "high_risks": c["high_risks"],
        "severity_breakdown": severity_map,
        "region_breakdown": region_map,
        "compliance_score": round(float(o["compliance_avg"]), 1),
        "active_org_members": o["org_members"],
        "total_scorecards": o["total_scorecards"],
        "total_tasks": total_tasks,
        "rbac_role": ctx["rbac_role"],
    }
