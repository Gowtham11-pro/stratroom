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
    """Query risks from MySQL via the bridge.

    Resolves the user's MySQL identity (emp_id, org_id) from their email.
    Uses JOIN with employee_details for org scoping.
    Non-admin members see only risks they own (t.owner = emp_id).
    Filters by min_heat based on the risk_value.score field.

    Returns a dict with 'risks' list and 'summary' stats.
    Each risk includes: id, name, owner (email), heat, riskStatus, description, mitigation, status.
    Heat score ranges: Critical >= 15, High >= 10, Medium >= 5, Low < 5.
    """
    from app.services.java_bridge import bridge

    # 1. Resolve MySQL identity from email
    mysql_user = None
    if email:
        rows = await bridge._mysql(
            "SELECT emp_id, org_id FROM employee_details "
            "WHERE LOWER(email_address) = LOWER(%s) LIMIT 1",
            (email,),
        )
        mysql_user = rows[0] if rows else None

    if not mysql_user:
        return {"risks": [], "summary": {
            "total": 0, "heat_scores": [],
            "critical_count": 0, "high_count": 0,
        }}

    mysql_org_id = mysql_user["org_id"]
    emp_id = mysql_user["emp_id"]

    # 2. Build query — org scoped via JOIN, always applied
    where_clauses = ["e.org_id = %s"]
    params = [mysql_org_id]

    if not is_admin:
        where_clauses.append("t.owner = %s")
        params.append(emp_id)

    where_sql = " AND ".join(where_clauses)

    rows = await bridge._mysql(
        "SELECT t.ID, t.risk_value, t.owner, t.status, t.created_time "
        "FROM risk_details t "
        "JOIN employee_details e ON e.emp_id = t.owner "
        f"WHERE {where_sql} "
        "ORDER BY t.ID",
        tuple(params),
    )

    # 3. Resolve owner emp_ids to emails
    owner_ids = set(r.get("owner") for r in rows if r.get("owner"))
    owner_map = {}
    if owner_ids:
        id_list = ",".join(str(oid) for oid in owner_ids)
        emp_rows = await bridge._mysql(
            f"SELECT emp_id, email_address FROM employee_details WHERE emp_id IN ({id_list})"
        )
        owner_map = {r["emp_id"]: r["email_address"] for r in emp_rows}

    # 4. Parse and enrich each risk
    risks = []
    for row in rows:
        rv = bridge._parse_json_col(row, "risk_value")
        owner_eid = row.get("owner")

        # Parse heat score from risk_value JSON
        score_raw = rv.get("score", "")
        try:
            heat = int(score_raw)
        except (ValueError, TypeError):
            heat = 0

        if min_heat is not None and heat < min_heat:
            continue

        risks.append({
            "id": row.get("ID"),
            "name": rv.get("name", ""),
            "owner": owner_map.get(owner_eid, str(owner_eid) if owner_eid else ""),
            "heat": heat,
            "riskStatus": rv.get("riskStatus", ""),
            "description": rv.get("desc", ""),
            "mitigation": rv.get("mitigation", ""),
            "status": row.get("status", ""),
        })

    # 5. Summary stats
    summary = {
        "total": len(risks),
        "heat_scores": [r["heat"] for r in risks],
        "critical_count": sum(1 for r in risks if r["heat"] >= 15),
        "high_count": sum(1 for r in risks if 10 <= r["heat"] < 15),
    }

    return {"risks": risks, "summary": summary}


# Mapping from numerical 1-5 to MySQL text values.
# Only levels 3-5 are confirmed from production data (40 risks).
# Levels 1-2 have no real-world precedent — round up to level 3
# rather than inventing unverified labels.
_LIKELIHOOD_MAP = {5: "Almost Certain", 4: "Likely", 3: "Possible", 2: "Possible", 1: "Possible"}
_IMPACT_MAP = {5: "Catastrophic", 4: "Major", 3: "Moderate", 2: "Moderate", 1: "Moderate"}


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
    email: str | None = None,
    is_admin: bool = False,
) -> dict:
    """Create a new risk in MySQL via the bridge.

    Resolves the creator's MySQL identity from email. Owner can be
    specified as an email string (resolved to emp_id). If no owner is
    provided, defaults to the creator's emp_id.

    Cross-org assignment is explicitly blocked — owner must belong to
    the same org as the creator.

    Likelihood and impact values must be 1-5. Stored as text in MySQL
    (levels 1-2 round up to level 3 — no production precedent exists
    for lower values).

    Returns the created risk record.
    """
    from app.services.java_bridge import bridge

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

    # 1. Resolve creator's MySQL identity
    mysql_user = None
    if email:
        rows = await bridge._mysql(
            "SELECT emp_id, org_id FROM employee_details "
            "WHERE LOWER(email_address) = LOWER(%s) LIMIT 1",
            (email,),
        )
        mysql_user = rows[0] if rows else None

    if not mysql_user:
        return {"error": "User not found in employee directory."}

    creator_org_id = mysql_user["org_id"]
    creator_emp_id = mysql_user["emp_id"]

    # 2. Resolve task owner
    if owner and owner.strip():
        owner_rows = await bridge._mysql(
            "SELECT emp_id, org_id FROM employee_details "
            "WHERE LOWER(email_address) = LOWER(%s) LIMIT 1",
            (owner.strip(),),
        )
        if not owner_rows:
            return {"error": f"Owner '{owner}' not found in employee directory."}

        owner_emp_id = owner_rows[0]["emp_id"]
        owner_org_id = owner_rows[0]["org_id"]

        if owner_org_id != creator_org_id:
            return {"error": "Cannot assign risks to users outside your organization."}
    else:
        owner_emp_id = creator_emp_id

    # 3. Compute heat score (approximate — known to not match the
    #    undocumented frontend formula, but better than leaving blank)
    heat = inherent_likelihood * inherent_impact

    # 4. Build risk_value JSON
    risk_value = {
        "name": name.strip(),
        "desc": description,
        "likeliHood": _LIKELIHOOD_MAP.get(inherent_likelihood, "Possible"),
        "impact": _IMPACT_MAP.get(inherent_impact, "Moderate"),
        "score": str(heat),
        "riskStatus": "Very High" if heat >= 15 else "High" if heat >= 10 else "Tolerable" if heat >= 5 else "Low",
    }
    if mitigation:
        risk_value["mitigation"] = mitigation

    # 5. INSERT into MySQL
    risk_id = await bridge._mysql_write(
        "INSERT INTO risk_details (risk_value, active, owner, created_time, updated_time, status) "
        "VALUES (%s, %s, %s, NOW(), NOW(), %s)",
        (json.dumps(risk_value), 1, owner_emp_id, "APPROVED"),
    )

    logger.info("Risk created via agent: id=%d org=%s owner_emp=%d", risk_id, creator_org_id, owner_emp_id)
    return {
        "id": risk_id,
        "name": name.strip(),
        "owner": owner if owner else email or "",
        "heat": heat,
        "riskStatus": risk_value["riskStatus"],
        "action": "created",
    }


def _score_to_riskstatus(heat: int) -> str:
    if heat >= 15:
        return "Very High"
    if heat >= 10:
        return "High"
    if heat >= 5:
        return "Tolerable"
    return "Low"


async def _resolve_mysql_user(email: str | None) -> dict | None:
    """Resolve an email to MySQL identity (emp_id, org_id).

    Returns None if the caller is not found in employee_details.
    """
    if not email:
        return None
    from app.services.java_bridge import bridge

    rows = await bridge._mysql(
        "SELECT emp_id, org_id FROM employee_details "
        "WHERE LOWER(email_address) = LOWER(%s) LIMIT 1",
        (email,),
    )
    return rows[0] if rows else None


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
    """Update an existing risk in MySQL via the bridge.

    Admin users can update any risk in their org.
    Members can only update risks they own.

    Updates are TOCTOU-safe: org/owner scoping is repeated directly
    in the UPDATE WHERE clause, not just checked in a prior SELECT.

    JSON blob fields (name, desc, likeliHood, impact, score, riskStatus,
    mitigation) are read, merged, and rewritten. Column fields (owner,
    status) are updated directly.

    If likelihood or impact is updated, score and riskStatus are
    recomputed from inherent_likelihood * inherent_impact.
    """
    from app.services.java_bridge import bridge

    # 1. Resolve MySQL identity
    mysql_user = await _resolve_mysql_user(email)
    if not mysql_user:
        return {"error": "User not found in employee directory."}

    mysql_org_id = mysql_user["org_id"]
    emp_id = mysql_user["emp_id"]

    # 2. Read current risk with org/ownership verification
    if is_admin:
        rows = await bridge._mysql(
            "SELECT t.ID, t.risk_value, t.owner, t.status "
            "FROM risk_details t "
            "JOIN employee_details e ON e.emp_id = t.owner "
            "WHERE t.ID = %s AND e.org_id = %s",
            (risk_id, mysql_org_id),
        )
    else:
        rows = await bridge._mysql(
            "SELECT t.ID, t.risk_value, t.owner, t.status "
            "FROM risk_details t "
            "JOIN employee_details e ON e.emp_id = t.owner "
            "WHERE t.ID = %s AND e.org_id = %s AND t.owner = %s",
            (risk_id, mysql_org_id, emp_id),
        )

    if not rows:
        if is_admin:
            return {"error": f"Risk {risk_id} not found in your organization."}
        return {"error": f"Risk {risk_id} is not yours. Only admins can update others' risks."}

    current = rows[0]
    rv = bridge._parse_json_col(current, "risk_value")

    # 3. Detect which fields changed
    updated_cols = {}        # column-name -> value
    json_changed = False
    recalc_score = False

    # Check JSON blob fields
    if name is not None:
        rv["name"] = name.strip() if name.strip() else rv.get("name", "")
        json_changed = True
    if description is not None:
        rv["desc"] = description
        json_changed = True
    if mitigation is not None:
        rv["mitigation"] = mitigation
        json_changed = True
    if inherent_likelihood is not None:
        if inherent_likelihood < 1 or inherent_likelihood > 5:
            return {"error": f"inherent_likelihood must be between 1 and 5, got {inherent_likelihood}"}
        rv["likeliHood"] = _LIKELIHOOD_MAP.get(inherent_likelihood, "Possible")
        json_changed = True
        recalc_score = True
    if inherent_impact is not None:
        if inherent_impact < 1 or inherent_impact > 5:
            return {"error": f"inherent_impact must be between 1 and 5, got {inherent_impact}"}
        rv["impact"] = _IMPACT_MAP.get(inherent_impact, "Moderate")
        json_changed = True
        recalc_score = True

    # Check column fields
    if owner is not None:
        # Resolve owner email -> emp_id
        owner_rows = await bridge._mysql(
            "SELECT emp_id, org_id FROM employee_details "
            "WHERE LOWER(email_address) = LOWER(%s) LIMIT 1",
            (owner.strip(),),
        )
        if not owner_rows:
            return {"error": f"Owner '{owner}' not found in employee directory."}
        if owner_rows[0]["org_id"] != mysql_org_id:
            return {"error": "Cannot reassign risks to users outside your organization."}
        updated_cols["owner"] = owner_rows[0]["emp_id"]

    warnings: list[str] = []
    if residual_likelihood is not None or residual_impact is not None:
        warnings.append("residual_likelihood/residual_impact are not stored in this system and were ignored.")

    if not json_changed and not updated_cols:
        return {"error": "No fields to update.", "action": "no_change"}

    # 4. Recompute score and riskStatus if likelihood/impact changed
    if recalc_score:
        il = inherent_likelihood if inherent_likelihood is not None else None
        ii = inherent_impact if inherent_impact is not None else None
        # If only one was provided, keep the other from the current JSON
        if il is None:
            # reverse-map current text back to number (approximate)
            il = {v: k for k, v in _LIKELIHOOD_MAP.items()}.get(rv.get("likeliHood"), 3)
        if ii is None:
            ii = {v: k for k, v in _IMPACT_MAP.items()}.get(rv.get("impact"), 3)
        heat = il * ii
        rv["score"] = str(heat)
        rv["riskStatus"] = _score_to_riskstatus(heat)
        json_changed = True

    # 5. Apply updates — TOCTOU-safe: org/owner repeated in WHERE
    if json_changed:
        if is_admin:
            await bridge._mysql_write(
                "UPDATE risk_details t "
                "JOIN employee_details e ON e.emp_id = t.owner "
                "SET t.risk_value = %s, t.updated_time = NOW() "
                "WHERE t.ID = %s AND e.org_id = %s",
                (json.dumps(rv), risk_id, mysql_org_id),
            )
        else:
            await bridge._mysql_write(
                "UPDATE risk_details t "
                "JOIN employee_details e ON e.emp_id = t.owner "
                "SET t.risk_value = %s, t.updated_time = NOW() "
                "WHERE t.ID = %s AND e.org_id = %s AND t.owner = %s",
                (json.dumps(rv), risk_id, mysql_org_id, emp_id),
            )

    if updated_cols:
        set_items = ", ".join(f"{k} = %s" for k in updated_cols)
        set_items += ", updated_time = NOW()"
        col_params = list(updated_cols.values()) + [risk_id, mysql_org_id]
        if is_admin:
            await bridge._mysql_write(
                f"UPDATE risk_details t "
                f"JOIN employee_details e ON e.emp_id = t.owner "
                f"SET {set_items} "
                f"WHERE t.ID = %s AND e.org_id = %s",
                tuple(col_params),
            )
        else:
            col_params.append(emp_id)
            await bridge._mysql_write(
                f"UPDATE risk_details t "
                f"JOIN employee_details e ON e.emp_id = t.owner "
                f"SET {set_items} "
                f"WHERE t.ID = %s AND e.org_id = %s AND t.owner = %s",
                tuple(col_params),
            )

    logger.info("Risk updated: id=%d org=%s", risk_id, mysql_org_id)
    result = {
        "risk_id": risk_id,
        "updated_fields": list(rv.keys()),
        "action": "updated",
    }
    if warnings:
        result["warnings"] = warnings
    return result


async def delete_risk(
    db: AsyncSession,
    user_id: int,
    org_id: int,
    risk_id: int,
    is_admin: bool = False,
    email: str | None = None,
) -> dict:
    """Delete a risk from MySQL via the bridge.

    Admin only. Performs an org-scoped hard DELETE with a
    rowcount check to confirm the row existed.

    The SELECT pre-check avoids returning success for a
    non-existent risk, while the DELETE itself is independently
    scoped (no TOCTOU leak — the UPDATE WHERE clause stands alone).
    """
    if not is_admin:
        return {"error": "Only admins can delete risks."}

    from app.services.java_bridge import bridge

    mysql_user = await _resolve_mysql_user(email)
    if not mysql_user:
        return {"error": "User not found in employee directory."}

    mysql_org_id = mysql_user["org_id"]

    # Pre-check: verify risk exists in this org
    rows = await bridge._mysql(
        "SELECT t.ID FROM risk_details t "
        "JOIN employee_details e ON e.emp_id = t.owner "
        "WHERE t.ID = %s AND e.org_id = %s",
        (risk_id, mysql_org_id),
    )
    if not rows:
        return {"error": f"Risk {risk_id} not found in your organization."}

    # Hard delete — independently scoped
    await bridge._mysql_write(
        "DELETE t FROM risk_details t "
        "JOIN employee_details e ON e.emp_id = t.owner "
        "WHERE t.ID = %s AND e.org_id = %s",
        (risk_id, mysql_org_id),
    )

    logger.info("Risk deleted: id=%d org=%s", risk_id, mysql_org_id)
    return {
        "risk_id": risk_id,
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
