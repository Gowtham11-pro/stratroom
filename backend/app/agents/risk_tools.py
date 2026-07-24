"""Risk management tools for the AI Chat Engine.

Provides query, create, update, and delete functions that agents can invoke
via tool calls. All functions are async and accept a DB session + user context.
Supports RBAC: admin users manage all org risks, members manage only their own.
"""
import json
import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("stratroom.agents.risk_tools")

RISK_FIELDS = [
    "id", "name", "owner", "inherent_likelihood", "inherent_impact",
    "residual_likelihood", "residual_impact", "description", "mitigation",
]


async def query_risks(
    db: AsyncSession,
    user_id: int,
    org_id: int,
    status_filter: str | None = None,
    min_heat: int | None = None,
    is_admin: bool = False,
    email: str | None = None,
) -> dict:
    """Query risks for the current user's organization.

    Admin/manager users see all risks. Members see only risks they own.
    Returns a dict with 'risks' list and 'summary' stats.

    The heat score = residual_likelihood * residual_impact (max 25).
    """
    where_clauses = ["org_id = :oid"]
    params: dict = {"oid": org_id}

    if not is_admin and email:
        where_clauses.append("owner = :owner")
        params["owner"] = email

    if min_heat is not None:
        where_clauses.append("(residual_likelihood * residual_impact) >= :min_heat")
        params["min_heat"] = min_heat

    where_sql = " AND ".join(where_clauses)

    result = await db.execute(
        text(
            f"SELECT id, name, owner, inherent_likelihood, inherent_impact, "
            f"residual_likelihood, residual_impact, description, mitigation, created_at "
            f"FROM risks WHERE {where_sql} "
            f"ORDER BY (residual_likelihood * residual_impact) DESC, id"
        ),
        params,
    )
    risks = [dict(r) for r in result.mappings().all()]

    summary = {
        "total": len(risks),
        "heat_scores": [r.get("residual_likelihood", 1) * r.get("residual_impact", 1) for r in risks],
        "critical_count": sum(
            1 for r in risks
            if (r.get("residual_likelihood", 1) * r.get("residual_impact", 1)) >= 15
        ),
        "high_count": sum(
            1 for r in risks
            if 10 <= (r.get("residual_likelihood", 1) * r.get("residual_impact", 1)) < 15
        ),
    }

    return {"risks": risks, "summary": summary}


async def create_risk(
    db: AsyncSession,
    org_id: int,
    name: str,
    owner: str = "",
    description: str = "",
    mitigation: str = "",
    inherent_likelihood: int = 3,
    inherent_impact: int = 3,
    residual_likelihood: int = 2,
    residual_impact: int = 2,
) -> dict:
    """Create a new risk record in the database.

    All likelihood and impact values must be 1-5.
    Returns the created risk record.
    """
    for val, label in [
        (inherent_likelihood, "inherent_likelihood"),
        (inherent_impact, "inherent_impact"),
        (residual_likelihood, "residual_likelihood"),
        (residual_impact, "residual_impact"),
    ]:
        if val < 1 or val > 5:
            return {"error": f"{label} must be between 1 and 5, got {val}"}

    if not name or not name.strip():
        return {"error": "Risk name is required"}

    result = await db.execute(
        text(
            "INSERT INTO risks (org_id, name, owner, description, mitigation, "
            "inherent_likelihood, inherent_impact, residual_likelihood, residual_impact) "
            "VALUES (:oid, :name, :owner, :desc, :mit, :il, :ii, :rl, :ri) RETURNING id"
        ),
        {
            "oid": org_id,
            "name": name.strip(),
            "owner": owner,
            "desc": description,
            "mit": mitigation,
            "il": inherent_likelihood,
            "ii": inherent_impact,
            "rl": residual_likelihood,
            "ri": residual_impact,
        },
    )
    row = result.mappings().first()
    risk_id = row["id"]
    await db.commit()

    logger.info("Risk created: id=%d org=%s", risk_id, org_id)
    return {
        "id": risk_id,
        "name": name.strip(),
        "owner": owner,
        "inherent_heat": inherent_likelihood * inherent_impact,
        "residual_heat": residual_likelihood * residual_impact,
        "action": "created",
    }


async def update_risk(
    db: AsyncSession,
    user_id: int,
    org_id: int,
    risk_id: int,
    is_admin: bool = False,
    email: str | None = None,
    name: str | None = None,
    owner: str | None = None,
    description: str | None = None,
    mitigation: str | None = None,
    inherent_likelihood: int | None = None,
    inherent_impact: int | None = None,
    residual_likelihood: int | None = None,
    residual_impact: int | None = None,
) -> dict:
    """Update an existing risk record.

    Admin users can update any risk in their org.
    Members can only update risks they own.
    Returns the updated fields summary.
    """
    # Verify ownership
    result = await db.execute(
        text("SELECT id, owner FROM risks WHERE id = :rid AND org_id = :oid"),
        {"rid": risk_id, "oid": org_id},
    )
    risk = result.mappings().first()
    if not risk:
        return {"error": f"Risk {risk_id} not found in your organization."}

    if not is_admin and email and risk["owner"] != email:
        return {"error": f"Risk {risk_id} is owned by {risk['owner']}, not by you. Only admins can update others' risks."}

    # Build update dict
    updates = {}
    field_map = {
        "name": name, "owner": owner, "description": description,
        "mitigation": mitigation,
        "inherent_likelihood": inherent_likelihood,
        "inherent_impact": inherent_impact,
        "residual_likelihood": residual_likelihood,
        "residual_impact": residual_impact,
    }
    for key, val in field_map.items():
        if val is not None:
            updates[key] = val

    if not updates:
        return {"error": "No fields to update.", "action": "no_change"}

    # Validate ranges
    for key in ["inherent_likelihood", "inherent_impact", "residual_likelihood", "residual_impact"]:
        if key in updates and (updates[key] < 1 or updates[key] > 5):
            return {"error": f"{key} must be between 1 and 5, got {updates[key]}"}

    set_clause = ", ".join(f"{k} = :{k}" for k in updates)
    updates["rid"] = risk_id
    updates["oid"] = org_id

    await db.execute(
        text(f"UPDATE risks SET {set_clause} WHERE id = :rid AND org_id = :oid"),
        updates,
    )
    await db.commit()

    logger.info("Risk updated: id=%d org=%s fields=%s", risk_id, org_id, list(updates.keys()))
    return {
        "risk_id": risk_id,
        "updated_fields": list(field_map.keys()),
        "action": "updated",
    }


async def delete_risk(
    db: AsyncSession,
    user_id: int,
    org_id: int,
    risk_id: int,
    is_admin: bool = False,
    email: str | None = None,
) -> dict:
    """Delete a risk record from the database.

    Only admin users can delete risks.
    Returns confirmation of deletion.
    """
    if not is_admin:
        return {"error": "Only admins can delete risks."}

    result = await db.execute(
        text("SELECT id, name FROM risks WHERE id = :rid AND org_id = :oid"),
        {"rid": risk_id, "oid": org_id},
    )
    risk = result.mappings().first()
    if not risk:
        return {"error": f"Risk {risk_id} not found in your organization."}

    risk_name = risk["name"]

    await db.execute(
        text("DELETE FROM risks WHERE id = :rid AND org_id = :oid"),
        {"rid": risk_id, "oid": org_id},
    )
    await db.commit()

    logger.info("Risk deleted: id=%d name=%s org=%s", risk_id, risk_name, org_id)
    return {
        "risk_id": risk_id,
        "name": risk_name,
        "action": "deleted",
    }


def format_risk_list(risks: list[dict]) -> str:
    """Format a risk list as readable text for LLM context injection."""
    if not risks:
        return "No risks found."
    lines = []
    for r in risks:
        heat = (r.get("residual_likelihood", 1) or 1) * (r.get("residual_impact", 1) or 1)
        inherent_heat = (r.get("inherent_likelihood", 1) or 1) * (r.get("inherent_impact", 1) or 1)
        heat_icon = "🔴" if heat >= 15 else "🟠" if heat >= 10 else "🟡"

        lines.append(
            f"{heat_icon} Risk #{r['id']}: {r['name']} "
            f"| Heat: {heat}/25 (inherent: {inherent_heat}/25) "
            f"| Owner: {r.get('owner', '—')} "
            f"| Mitigation: {r.get('mitigation', '—')[:60]}"
        )
    return "\n".join(lines)
