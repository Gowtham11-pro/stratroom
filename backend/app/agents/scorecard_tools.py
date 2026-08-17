"""Scorecard management tools for the AI Chat Engine.

Provides query, create, update, and delete functions that agents can invoke
via tool calls. All functions are async and accept a DB session + user context.
Supports RBAC: admin users manage all org scorecards, members manage only assigned.
"""
import logging

logger = logging.getLogger("stratroom.agents.scorecard_tools")

VALID_SC_STATUSES = {"on-track", "at-risk", "critical"}


JUNK_KPIS_AGENT_SQL = (
    "AND LOWER(TRIM(kpi_name)) NOT IN ('baby','news','newws','sirenn','tron','jessi','jess','dracks',"
    "'trans','punitha','narayanan','rose','tset2','kpifere','finnce','score','kpi 2','kpi new','kpi02','kpi01',"
    "'kpi - objective - fin1','fin_obj1_kpi1','customer kpi','kpi','obj1 kpi1','sironn') "
    "AND LOWER(kpi_name) NOT LIKE '%%newws%%' "
    "AND LOWER(kpi_name) NOT LIKE '%%sirenn%%' "
    "AND LOWER(kpi_name) NOT LIKE '%%tset2%%' "
    "AND LOWER(kpi_name) NOT LIKE '%%kpifere%%' "
    "AND LOWER(kpi_name) NOT LIKE '%%finnce%%' "
    "AND LOWER(kpi_name) NOT LIKE '%%fin_obj1_kpi1%%'"
)

PERSP_ALIAS_MAP = {
    "financial performance": "Financial",
    "financial performance and growth": "Financial",
    "financial": "Financial",
    "customer": "Customer",
    "customer and market": "Customer",
    "ops": "Internal Processes",
    "internal processes": "Internal Processes",
    "manufacturing and operational excellence": "Internal Processes",
    "people": "Learning & Growth",
    "people and organisational capability": "Learning & Growth",
    "learning & growth": "Learning & Growth",
    "esg": "ESG & Compliance",
    "esg & compliance": "ESG & Compliance",
    "risk": "Risk & Security",
    "risk & security": "Risk & Security",
    "governance risk and compliance": "Risk & Security",
}


async def query_scorecards(
    user_id: int,
    org_id: int,
    perspective_filter: str | None = None,
    status_filter: str | None = None,
    is_admin: bool = False,
    is_manager: bool = False,
) -> dict:
    """Query scorecards (KPIs) from MySQL scorecard_kpis via the bridge."""
    from app.services.java_bridge import bridge

    where_clauses = ["org_id = %s"]
    params = [org_id]

    if not is_admin and not is_manager:
        where_clauses.append("assigned_user_id = %s")
        params.append(user_id)

    if perspective_filter:
        raw_p = perspective_filter.strip().lower()
        norm_p = PERSP_ALIAS_MAP.get(raw_p, perspective_filter.strip())
        where_clauses.append("(LOWER(perspective) = LOWER(%s) OR LOWER(perspective) LIKE LOWER(%s))")
        params.extend([norm_p, f"%{norm_p}%"])

    if status_filter:
        statuses = [s.strip().replace("_", "-").lower() for s in status_filter.split(",") if s.strip()]
        valid_requested = [s for s in statuses if s in VALID_SC_STATUSES]
        if valid_requested:
            placeholders = ", ".join(["%s"] * len(valid_requested))
            where_clauses.append(f"LOWER(status) IN ({placeholders})")
            params.extend(valid_requested)

    where_sql = " AND ".join(where_clauses)

    rows = await bridge._mysql(
        f"SELECT id, perspective, kpi_name, target, actual, owner, status, assigned_user_id "
        f"FROM scorecard_kpis WHERE id IN ("
        f"SELECT MIN(id) FROM scorecard_kpis WHERE {where_sql} {JUNK_KPIS_AGENT_SQL} "
        f"GROUP BY perspective, kpi_name, target, actual, status"
        f") ORDER BY perspective, id",
        tuple(params),
    )

    # Convert Decimals and compute gap analysis
    for sc in rows:
        t = float(sc["target"]) if sc.get("target") is not None else None
        a = float(sc["actual"]) if sc.get("actual") is not None else None
        sc["target"] = t
        sc["actual"] = a
        if t and t != 0:
            sc["gap_pct"] = round(((a or 0.0) - t) / t * 100, 1)
        else:
            sc["gap_pct"] = 0.0

    summary = {
        "total": len(rows),
        "on_track": sum(1 for s in rows if s.get("status") == "on-track"),
        "at_risk": sum(1 for s in rows if s.get("status") == "at-risk"),
        "critical": sum(1 for s in rows if s.get("status") == "critical"),
        "perspectives": list(set(s.get("perspective") for s in rows if s.get("perspective"))),
    }

    return {"scorecards": rows, "summary": summary}


async def query_scorecard_summary(
    user_id: int,
    org_id: int,
    is_admin: bool = False,
    is_manager: bool = False,
) -> dict:
    """Get an aggregated summary of scorecard perspectives."""
    from app.services.java_bridge import bridge

    if is_admin or is_manager:
        rows = await bridge._mysql(
            "SELECT perspective, "
            "ROUND(AVG(actual)) as avg_score, "
            "COUNT(*) as kpi_count, "
            "SUM(CASE WHEN status = 'on-track' THEN 1 ELSE 0 END) as on_track, "
            "SUM(CASE WHEN status = 'at-risk' THEN 1 ELSE 0 END) as at_risk, "
            "SUM(CASE WHEN status = 'critical' THEN 1 ELSE 0 END) as critical "
            f"FROM (SELECT MIN(id) as mid, perspective, actual, status "
            f"FROM scorecard_kpis WHERE org_id = %s {JUNK_KPIS_AGENT_SQL} "
            "GROUP BY perspective, kpi_name, target, actual, status) t "
            "GROUP BY perspective ORDER BY MIN(mid)",
            (org_id,),
        )
    else:
        rows = await bridge._mysql(
            "SELECT perspective, "
            "ROUND(AVG(actual)) as avg_score, "
            "COUNT(*) as kpi_count, "
            "SUM(CASE WHEN status = 'on-track' THEN 1 ELSE 0 END) as on_track, "
            "SUM(CASE WHEN status = 'at-risk' THEN 1 ELSE 0 END) as at_risk, "
            "SUM(CASE WHEN status = 'critical' THEN 1 ELSE 0 END) as critical "
            f"FROM (SELECT MIN(id) as mid, perspective, actual, status "
            f"FROM scorecard_kpis WHERE org_id = %s AND assigned_user_id = %s {JUNK_KPIS_AGENT_SQL} "
            "GROUP BY perspective, kpi_name, target, actual, status) t "
            "GROUP BY perspective ORDER BY MIN(mid)",
            (org_id, user_id),
        )

    # Convert numeric types for JSON serialization
    result = []
    for r in rows:
        result.append({
            "perspective": r["perspective"],
            "avg_score": int(r["avg_score"]) if r.get("avg_score") is not None else 0,
            "kpi_count": int(r.get("kpi_count", 0)),
            "on_track": int(r.get("on_track", 0)),
            "at_risk": int(r.get("at_risk", 0)),
            "critical": int(r.get("critical", 0)),
        })

    return {"perspectives": result}


async def create_scorecard(
    org_id: int,
    perspective: str,
    kpi_name: str,
    target: float | None = None,
    actual: float | None = None,
    owner: str = "",
    status: str = "on-track",
    assigned_user_id: int | None = None,
    is_admin: bool = False,
    is_manager: bool = False,
) -> dict:
    """Create a new scorecard/KPI record in MySQL scorecard_kpis via the bridge.

    Restricted to managers/admins (matching the HTTP endpoint and query_scorecards).
    Status must be one of: on-track, at-risk, critical.
    Returns the created scorecard record with its new ID.
    """
    from app.services.java_bridge import bridge

    if not is_admin and not is_manager:
        return {"error": "Only managers and admins can create scorecards."}

    if not perspective or not perspective.strip():
        return {"error": "Perspective is required"}
    if not kpi_name or not kpi_name.strip():
        return {"error": "KPI name is required"}
    if status not in VALID_SC_STATUSES:
        return {"error": f"Invalid status '{status}'. Must be one of: {', '.join(sorted(VALID_SC_STATUSES))}"}

    # Verify assigned user if provided (MySQL users table)
    if assigned_user_id is not None:
        user_check = await bridge._mysql(
            "SELECT id FROM users WHERE id = %s AND org_id = %s",
            (assigned_user_id, org_id),
        )
        if not user_check:
            return {"error": "Assigned user not found in this organization"}

    sc_id = await bridge._mysql_write(
        "INSERT INTO scorecard_kpis (org_id, perspective, kpi_name, target, actual, owner, status, assigned_user_id) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (org_id, perspective.strip(), kpi_name.strip(), target, actual, owner, status, assigned_user_id),
    )

    logger.info("Scorecard created: id=%d org=%s perspective=%s kpi=%s", sc_id, org_id, perspective, kpi_name)
    return {
        "id": sc_id,
        "perspective": perspective.strip(),
        "kpi_name": kpi_name.strip(),
        "status": status,
        "action": "created",
    }


async def update_scorecard(
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
    """Update an existing scorecard/KPI record in MySQL scorecard_kpis via the bridge.

    Admin users can update any scorecard in their org.
    Members can only update scorecards assigned to them.
    Returns the updated fields summary.
    """
    from app.services.java_bridge import bridge

    # Verify ownership
    if is_admin:
        existing = await bridge._mysql(
            "SELECT id, assigned_user_id FROM scorecard_kpis WHERE id = %s AND org_id = %s",
            (scorecard_id, org_id),
        )
    else:
        existing = await bridge._mysql(
            "SELECT id, assigned_user_id FROM scorecard_kpis WHERE id = %s AND org_id = %s AND assigned_user_id = %s",
            (scorecard_id, org_id, user_id),
        )
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
        user_check = await bridge._mysql(
            "SELECT id FROM users WHERE id = %s AND org_id = %s",
            (assigned_user_id, org_id),
        )
        if not user_check:
            return {"error": "Assigned user not found in this organization"}
        updates["assigned_user_id"] = assigned_user_id

    if not updates:
        return {"error": "No fields to update.", "action": "no_change"}

    # Dynamic UPDATE with %s placeholders for MySQL
    set_clause = ", ".join(f"{k} = %s" for k in updates)
    params = list(updates.values())
    params.extend([scorecard_id, org_id])

    await bridge._mysql_write(
        f"UPDATE scorecard_kpis SET {set_clause} WHERE id = %s AND org_id = %s",
        tuple(params),
    )

    logger.info("Scorecard updated: id=%d org=%s fields=%s", scorecard_id, org_id, list(updates.keys()))
    return {
        "scorecard_id": scorecard_id,
        "updated_fields": list(updates.keys()),
        "action": "updated",
    }


async def delete_scorecard(
    user_id: int,
    org_id: int,
    scorecard_id: int,
    is_admin: bool = False,
) -> dict:
    """Delete a scorecard/KPI record from MySQL scorecard_kpis via the bridge.

    Only admin users can delete scorecards.
    Returns confirmation of deletion.
    """
    from app.services.java_bridge import bridge

    if not is_admin:
        return {"error": "Only admins can delete scorecards."}

    existing = await bridge._mysql(
        "SELECT id, kpi_name FROM scorecard_kpis WHERE id = %s AND org_id = %s",
        (scorecard_id, org_id),
    )
    if not existing:
        return {"error": f"Scorecard {scorecard_id} not found in your organization."}

    kpi_name = existing[0]["kpi_name"]

    await bridge._mysql_write(
        "DELETE FROM scorecard_kpis WHERE id = %s AND org_id = %s",
        (scorecard_id, org_id),
    )

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
