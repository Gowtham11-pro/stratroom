"""Scorecard management tools for the AI Chat Engine.

Provides query, create, update, and delete functions that agents can invoke
via tool calls. All functions are async and accept a DB session + user context.
Supports RBAC: admin users manage all org scorecards, members manage only assigned.
"""
import json
import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("stratroom.agents.scorecard_tools")

VALID_SC_STATUSES = {"on-track", "at-risk", "critical"}


async def query_scorecards(
    db: AsyncSession,
    user_id: int,
    org_id: int,
    perspective_filter: str | None = None,
    status_filter: str | None = None,
    is_admin: bool = False,
    is_manager: bool = False,
) -> dict:
    """Query scorecards (KPIs) for the current user's organization.

    Admin/manager users see all scorecards. Members see only assigned.
    Returns a dict with 'scorecards' list and 'summary' stats.
    """
    where_clauses = ["org_id = :oid"]
    params: dict = {"oid": org_id}

    if not is_admin and not is_manager:
        where_clauses.append("assigned_user_id = :uid")
        params["uid"] = user_id

    if perspective_filter:
        where_clauses.append("perspective = :perspective")
        params["perspective"] = perspective_filter

    if status_filter:
        if status_filter in VALID_SC_STATUSES:
            where_clauses.append("status = :status")
            params["status"] = status_filter

    where_sql = " AND ".join(where_clauses)

    result = await db.execute(
        text(
            f"SELECT id, perspective, kpi_name, target, actual, owner, status, assigned_user_id "
            f"FROM scorecards WHERE {where_sql} "
            f"ORDER BY perspective, id"
        ),
        params,
    )
    scorecards = [dict(r) for r in result.mappings().all()]

    # Compute gap analysis
    for sc in scorecards:
        t = sc.get("target")
        a = sc.get("actual")
        if t and t != 0:
            sc["gap_pct"] = round(((a or 0) - t) / t * 100, 1)
        else:
            sc["gap_pct"] = 0

    summary = {
        "total": len(scorecards),
        "on_track": sum(1 for s in scorecards if s["status"] == "on-track"),
        "at_risk": sum(1 for s in scorecards if s["status"] == "at-risk"),
        "critical": sum(1 for s in scorecards if s["status"] == "critical"),
        "perspectives": list(set(s["perspective"] for s in scorecards)),
    }

    return {"scorecards": scorecards, "summary": summary}


async def query_scorecard_summary(
    db: AsyncSession,
    user_id: int,
    org_id: int,
    is_admin: bool = False,
    is_manager: bool = False,
) -> dict:
    """Get an aggregated summary of scorecard perspectives.

    Returns avg actual scores, KPI counts, and status breakdown per perspective.
    """
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
    return {"perspectives": [dict(r) for r in rows]}


async def create_scorecard(
    db: AsyncSession,
    org_id: int,
    perspective: str,
    kpi_name: str,
    target: float | None = None,
    actual: float | None = None,
    owner: str = "",
    status: str = "on-track",
    assigned_user_id: int | None = None,
) -> dict:
    """Create a new scorecard/KPI record in the database.

    Status must be one of: on-track, at-risk, critical.
    Returns the created scorecard record.
    """
    if not perspective or not perspective.strip():
        return {"error": "Perspective is required"}
    if not kpi_name or not kpi_name.strip():
        return {"error": "KPI name is required"}
    if status not in VALID_SC_STATUSES:
        return {"error": f"Invalid status '{status}'. Must be one of: {', '.join(sorted(VALID_SC_STATUSES))}"}

    # Verify assigned user if provided
    if assigned_user_id is not None:
        user_check = await db.execute(
            text("SELECT id FROM users WHERE id = :uid AND org_id = :oid"),
            {"uid": assigned_user_id, "oid": org_id},
        )
        if not user_check.first():
            return {"error": "Assigned user not found in this organization"}

    result = await db.execute(
        text(
            "INSERT INTO scorecards (org_id, perspective, kpi_name, target, actual, owner, status, assigned_user_id) "
            "VALUES (:oid, :perspective, :kpi_name, :target, :actual, :owner, :status, :assigned_user_id) "
            "RETURNING id"
        ),
        {
            "oid": org_id,
            "perspective": perspective.strip(),
            "kpi_name": kpi_name.strip(),
            "target": target,
            "actual": actual,
            "owner": owner,
            "status": status,
            "assigned_user_id": assigned_user_id,
        },
    )
    row = result.mappings().first()
    sc_id = row["id"]
    await db.commit()

    logger.info("Scorecard created: id=%d org=%s perspective=%s kpi=%s", sc_id, org_id, perspective, kpi_name)
    return {
        "id": sc_id,
        "perspective": perspective.strip(),
        "kpi_name": kpi_name.strip(),
        "status": status,
        "action": "created",
    }


async def update_scorecard(
    db: AsyncSession,
    user_id: int,
    org_id: int,
    scorecard_id: int,
    is_admin: bool = False,
    perspective: str | None = None,
    kpi_name: str | None = None,
    target: float | None = None,
    actual: float | None = None,
    owner: str | None = None,
    status: str | None = None,
    assigned_user_id: int | None = None,
) -> dict:
    """Update an existing scorecard/KPI record.

    Admin users can update any scorecard in their org.
    Members can only update scorecards assigned to them.
    Returns the updated fields summary.
    """
    # Verify ownership
    if is_admin:
        result = await db.execute(
            text("SELECT id, assigned_user_id FROM scorecards WHERE id = :sid AND org_id = :oid"),
            {"sid": scorecard_id, "oid": org_id},
        )
    else:
        result = await db.execute(
            text("SELECT id, assigned_user_id FROM scorecards WHERE id = :sid AND org_id = :oid AND assigned_user_id = :uid"),
            {"sid": scorecard_id, "oid": org_id, "uid": user_id},
        )
    existing = result.mappings().first()
    if not existing:
        return {"error": f"Scorecard {scorecard_id} not found or not assigned to you."}

    # Validate status if provided
    if status is not None and status not in VALID_SC_STATUSES:
        return {"error": f"Invalid status '{status}'. Must be one of: {', '.join(sorted(VALID_SC_STATUSES))}"}

    updates = {}
    field_map = {
        "perspective": perspective,
        "kpi_name": kpi_name,
        "target": target,
        "actual": actual,
        "owner": owner,
        "status": status,
    }
    for key, val in field_map.items():
        if val is not None:
            updates[key] = val

    # Handle reassignment (admin only)
    if assigned_user_id is not None:
        if not is_admin:
            return {"error": "Only admins can reassign scorecards."}
        user_check = await db.execute(
            text("SELECT id FROM users WHERE id = :uid AND org_id = :oid"),
            {"uid": assigned_user_id, "oid": org_id},
        )
        if not user_check.first():
            return {"error": "Assigned user not found in this organization"}
        updates["assigned_user_id"] = assigned_user_id

    if not updates:
        return {"error": "No fields to update.", "action": "no_change"}

    set_clause = ", ".join(f"{k} = :{k}" for k in updates)
    updates["sid"] = scorecard_id
    updates["oid"] = org_id

    await db.execute(
        text(f"UPDATE scorecards SET {set_clause} WHERE id = :sid AND org_id = :oid"),
        updates,
    )
    await db.commit()

    logger.info("Scorecard updated: id=%d org=%s fields=%s", scorecard_id, org_id, list(updates.keys()))
    return {
        "scorecard_id": scorecard_id,
        "updated_fields": list(updates.keys()),
        "action": "updated",
    }


async def delete_scorecard(
    db: AsyncSession,
    user_id: int,
    org_id: int,
    scorecard_id: int,
    is_admin: bool = False,
) -> dict:
    """Delete a scorecard/KPI record from the database.

    Only admin users can delete scorecards.
    Returns confirmation of deletion.
    """
    if not is_admin:
        return {"error": "Only admins can delete scorecards."}

    result = await db.execute(
        text("SELECT id, kpi_name FROM scorecards WHERE id = :sid AND org_id = :oid"),
        {"sid": scorecard_id, "oid": org_id},
    )
    scorecard = result.mappings().first()
    if not scorecard:
        return {"error": f"Scorecard {scorecard_id} not found in your organization."}

    kpi_name = scorecard["kpi_name"]

    await db.execute(
        text("DELETE FROM scorecards WHERE id = :sid AND org_id = :oid"),
        {"sid": scorecard_id, "oid": org_id},
    )
    await db.commit()

    logger.info("Scorecard deleted: id=%d kpi=%s org=%s", scorecard_id, kpi_name, org_id)
    return {
        "scorecard_id": scorecard_id,
        "kpi_name": kpi_name,
        "action": "deleted",
    }


def format_scorecard_list(scorecards: list[dict]) -> str:
    """Format a scorecard list as readable text for LLM context injection."""
    if not scorecards:
        return "No scorecards found."
    lines = []
    for s in scorecards:
        status_icon = {"on-track": "✅", "at-risk": "🟠", "critical": "🔴"}.get(s["status"], "❓")
        gap = s.get("gap_pct", 0)
        gap_str = f"{gap:+.1f}%" if gap != 0 else "on target"
        lines.append(
            f"{status_icon} [{s['perspective']}] {s['kpi_name']}: "
            f"target={s.get('target', '—')} actual={s.get('actual', '—')} "
            f"({gap_str}) | Owner: {s.get('owner', '—')}"
        )
    return "\n".join(lines)
