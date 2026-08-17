"""Incident management tools for the AI Chat Engine.

Provides update functions that agents can invoke via tool calls.
All functions are async and accept a DB session + user context.
Supports RBAC: admin users update incidents across the org, members
can only update incidents they own.
"""
import json
import logging
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("stratroom.agents.incident_tools")

VALID_SEVERITIES = {"Critical", "High", "Medium", "Low"}
VALID_STATUSES = {"Under Investigation", "In Review", "Escalated", "Closed"}


def _normalize_severity(value: str) -> str | None:
    mapping = {
        "critical": "Critical", "high": "High", "medium": "Medium", "low": "Low",
    }
    return mapping.get((value or "").strip().lower())


def _normalize_status(value: str) -> str | None:
    v = (value or "").strip().lower()
    mapping = {
        "under investigation": "Under Investigation",
        "under_investigation": "Under Investigation",
        "investigating": "Under Investigation",
        "investigation": "Under Investigation",
        "open": "Under Investigation",
        "in review": "In Review",
        "in_review": "In Review",
        "review": "In Review",
        "escalated": "Escalated",
        "closed": "Closed",
        "resolved": "Closed",
        "done": "Closed",
    }
    return mapping.get(v)


async def update_incident_status(
    db: AsyncSession,
    user_id: int,
    org_id: int,
    incident_id: int,
    status: str | None = None,
    severity: str | None = None,
    primary_assignee: str | None = None,
    is_admin: bool = False,
    email: str | None = None,
) -> dict:
    """Update an incident's status / severity / primary assignee in MySQL.

    Reads the incident_value JSON blob from universal_incident, mutates the
    nested classification / assignment fields, and writes the blob back via
    parameterized SQL. Admins update any incident by ID (many incidents are
    owned by orphan emp_ids with no employee_details row, so org JOIN scoping
    would drop them); members can only update incidents they own.

    Returns a dict with a human-readable confirmation string.
    """
    from app.services.java_bridge import bridge

    # 1. Validate inputs
    if not isinstance(incident_id, int):
        return {"error": f"incident_id must be an integer, got '{incident_id}'"}

    if status is not None:
        status = _normalize_status(status)
        if status is None:
            return {"error": f"Invalid incident status '{status}'. Must be one of: Under Investigation, In Review, Escalated, Closed"}
    if severity is not None:
        severity = _normalize_severity(severity)
        if severity is None:
            return {"error": f"Invalid incident severity '{severity}'. Must be one of: Critical, High, Medium, Low"}

    if status is None and severity is None and primary_assignee is None:
        return {"error": "Provide at least one of: status, severity, primary_assignee."}

    # 2. Fetch the incident.
    # Admins update by ID directly (unscoped) — incidents 1-12 are owned by
    # orphan emp_ids with no employee_details row, so a JOIN-based org scope
    # would silently drop them. This mirrors the bridge's existing unscoped
    # PUT for /universalIncidentList/{id}.
    if is_admin:
        rows = await bridge._mysql(
            "SELECT ID, incident_value, owner FROM universal_incident WHERE ID = %s",
            (incident_id,),
        )
    else:
        # 2a. Members must own the incident: resolve their MySQL identity.
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

        rows = await bridge._mysql(
            "SELECT ID, incident_value, owner FROM universal_incident "
            "WHERE ID = %s AND owner = %s",
            (incident_id, mysql_user["emp_id"]),
        )

    if not rows:
        if is_admin:
            return {"error": f"Incident {incident_id} not found."}
        return {"error": f"This incident is not yours. Incident {incident_id} is not assigned to you."}

    incident = rows[0]
    iv = bridge._parse_json_col(incident, "incident_value")
    if not iv:
        return {"error": f"Incident {incident_id} has no readable data."}

    # 4. Apply field changes to nested JSON
    changes = []
    if status is not None:
        old = (iv.get("classification") or {}).get("initialStatus", "")
        if old != status:
            iv.setdefault("classification", {})["initialStatus"] = status
            changes.append(f"status from '{old}' to '{status}'")
    if severity is not None:
        old = (iv.get("classification") or {}).get("severity", "")
        if old != severity:
            iv.setdefault("classification", {})["severity"] = severity
            changes.append(f"severity from '{old}' to '{severity}'")
    if primary_assignee is not None:
        old = (iv.get("assignment") or {}).get("primaryAssignee", "")
        if old != primary_assignee:
            iv.setdefault("assignment", {})["primaryAssignee"] = primary_assignee
            changes.append(f"primary assignee from '{old}' to '{primary_assignee}'")

    if not changes:
        return {
            "incident_id": incident_id,
            "action": "no_change",
            "confirmation": f"Incident #{incident_id} already reflects the requested values; no change made.",
        }

    # 5. Write the updated blob back — admin updates by ID, members by ID+owner
    if is_admin:
        await bridge._mysql_write(
            "UPDATE universal_incident SET incident_value=%s, updated_time=NOW() WHERE ID=%s",
            (json.dumps(iv), incident_id),
        )
    else:
        await bridge._mysql_write(
            "UPDATE universal_incident SET incident_value=%s, updated_time=NOW() WHERE ID=%s AND owner=%s",
            (json.dumps(iv), incident_id, mysql_user["emp_id"]),
        )

    confirmation = (
        f"Successfully updated incident #{incident_id}: "
        + "; ".join(changes)
        + " in the database."
    )

    logger.info("Incident updated via agent: id=%d changes=%s", incident_id, changes)
    return {
        "incident_id": incident_id,
        "changes": changes,
        "action": "updated",
        "confirmation": confirmation,
    }
