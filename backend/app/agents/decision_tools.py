"""Decision management tools for the AI Chat Engine.

Provides query, create, and update functions that agents can invoke via
tool calls. Backed by the MySQL `decisions` table. Org-scoping uses the
org_id column directly (decisions are org-level records owned by an emp_id).

All functions are async and accept a DB session + user context.
"""
import json
import logging
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("stratroom.agents.decision_tools")

from app.agents.task_tools import DEFAULT_OWNER_EMAIL, find_similar_employees, resolve_owner_emp_id  # noqa: E402

VALID_STATUSES = {"Pending", "In Review", "Approved", "Rejected", "Deferred", "Completed"}
VALID_PRIORITIES = {"Critical", "High", "Medium", "Low"}


def _normalize_status(value: str) -> str | None:
    v = (value or "").strip().lower()
    mapping = {
        "pending": "Pending",
        "in review": "In Review",
        "in_review": "In Review",
        "review": "In Review",
        "approved": "Approved",
        "approve": "Approved",
        "rejected": "Rejected",
        "reject": "Rejected",
        "deferred": "Deferred",
        "completed": "Completed",
        "complete": "Completed",
        "done": "Completed",
        "closed": "Completed",
    }
    return mapping.get(v)


def _normalize_priority(value: str) -> str | None:
    v = (value or "").strip().lower()
    mapping = {
        "critical": "Critical", "high": "High", "medium": "Medium", "low": "Low",
    }
    return mapping.get(v)


async def _resolve_mysql_user(bridge, email: str | None) -> dict | None:
    if not email:
        return None
    rows = await bridge._mysql(
        "SELECT emp_id, org_id FROM employee_details "
        "WHERE LOWER(email_address) = LOWER(%s) LIMIT 1",
        (email,),
    )
    return rows[0] if rows else None


async def query_decisions(
    db: AsyncSession,
    user_id: int,
    org_id: int,
    status_filter: str | None = None,
    is_admin: bool = False,
    email: str | None = None,
) -> dict:
    """Query decisions from MySQL via the bridge.

    Admins see all decisions unscoped (business data spans orgs 3-8 while
    admin users sit in org 1). Members see decisions in their own org.
    """
    from app.services.java_bridge import bridge

    if is_admin:
        where = []
        params: list = []
    else:
        mysql_user = await _resolve_mysql_user(bridge, email)
        if not mysql_user:
            return {"decisions": [], "summary": {"total": 0}}

        where = ["org_id = %s"]
        params = [mysql_user["org_id"]]

    if status_filter:
        norm = _normalize_status(status_filter)
        if norm is None:
            return {"error": f"Invalid status filter '{status_filter}'"}
        where.append("status = %s")
        params.append(norm)

    where_sql = (" WHERE " + " AND ".join(where)) if where else ""

    rows = await bridge._mysql(
        "SELECT id, decision_value, org_id, active, owner, status, priority, created_time, updated_time "
        "FROM decisions" + where_sql + " ORDER BY FIELD(priority, 'Critical', 'High', 'Medium', 'Low'), id",
        tuple(params),
    )

    decisions = []
    for r in rows:
        dv = bridge._parse_json_col(r, "decision_value")
        decisions.append({
            "id": r.get("id"),
            "title": dv.get("title", ""),
            "description": dv.get("description", ""),
            "owner": dv.get("owner", r.get("owner")),
            "status": r.get("status", ""),
            "priority": r.get("priority", "Medium"),
            "due_date": dv.get("dueDate", ""),
            "active": r.get("active"),
        })

    summary = {
        "total": len(decisions),
        "pending": sum(1 for d in decisions if d["status"] == "Pending"),
        "in_review": sum(1 for d in decisions if d["status"] == "In Review"),
        "approved": sum(1 for d in decisions if d["status"] == "Approved"),
    }

    return {"decisions": decisions, "summary": summary}


async def create_decision(
    db: AsyncSession,
    org_id: int,
    title: str,
    description: str = "",
    status: str = "Pending",
    owner: str | None = None,
    priority: str = "Medium",
    due_date: str | None = None,
    email: str | None = None,
    is_admin: bool = False,
) -> dict:
    """Create a new decision in MySQL via the bridge."""
    from app.services.java_bridge import bridge

    if not title or not title.strip():
        return {"error": "Decision title is required"}

    status = _normalize_status(status)
    if status is None:
        return {"error": f"Invalid status '{status}'. Must be one of: {', '.join(sorted(VALID_STATUSES))}"}
    priority = _normalize_priority(priority)
    if priority is None:
        return {"error": f"Invalid priority '{priority}'. Must be one of: {', '.join(sorted(VALID_PRIORITIES))}"}

    mysql_user = await _resolve_mysql_user(bridge, email)
    if mysql_user:
        creator_org_id = mysql_user["org_id"]
        creator_emp_id = mysql_user["emp_id"]
    elif is_admin:
        # Admins not present in employee_details fall back to the JWT org_id
        creator_org_id = org_id
        creator_emp_id = None
    else:
        return {"error": "User not found in employee directory."}

    # Resolve owner (email / full name / first name -> emp_id); defaults to creator
    if owner and owner.strip():
        owner_row = await resolve_owner_emp_id(bridge, owner)
        if not owner_row:
            suggestion = ""
            matches = await find_similar_employees(bridge, owner)
            if matches:
                suggestion = " Did you mean: " + ", ".join(matches) + "?"
            return {"error": f"Owner '{owner}' not found in the employee directory.{suggestion}"}
        # Cross-org guard applies only when the creator has a resolvable
        # employee org; admins outside the directory can assign anywhere.
        if creator_emp_id is not None and owner_row["org_id"] != creator_org_id:
            return {"error": "Cannot assign decisions to users outside your organization."}
        owner_emp_id = owner_row["emp_id"]
    else:
        if creator_emp_id is None:
            # Directory-less admin: default to the fixed demo owner so the
            # created decision is visible to real business users.
            default_row = await resolve_owner_emp_id(bridge, DEFAULT_OWNER_EMAIL)
            if default_row:
                owner_emp_id = default_row["emp_id"]
                owner = DEFAULT_OWNER_EMAIL
            else:
                return {"error": "You are not in the employee directory. Please specify an owner=email@x.com to assign this decision to."}
        else:
            owner_emp_id = creator_emp_id
            owner = email or ""

    decision_value = {
        "title": title.strip(),
        "description": description,
        "owner": owner,
        "priority": priority,
    }
    if due_date:
        decision_value["dueDate"] = due_date

    decision_id = await bridge._mysql_write(
        "INSERT INTO decisions (decision_value, org_id, active, owner, status, priority, created_time, updated_time) "
        "VALUES (%s, %s, %s, %s, %s, %s, NOW(), NOW())",
        (json.dumps(decision_value), creator_org_id, 1, owner_emp_id, status, priority),
    )

    logger.info("Decision created via agent: id=%d org=%s", decision_id, creator_org_id)
    confirmation = (
        f"Successfully created Decision #{decision_id} "
        f"('{title.strip()}') with status '{status}' in the database."
    )
    return {
        "id": decision_id,
        "title": title.strip(),
        "status": status,
        "priority": priority,
        "action": "created",
        "confirmation": confirmation,
    }


async def update_decision_status(
    db: AsyncSession,
    user_id: int,
    org_id: int,
    decision_id: int,
    status: str | None = None,
    owner: str | None = None,
    is_admin: bool = False,
    email: str | None = None,
) -> dict:
    """Update a decision's status or owner in MySQL via the bridge."""
    from app.services.java_bridge import bridge

    if not isinstance(decision_id, int):
        return {"error": f"decision_id must be an integer, got '{decision_id}'"}

    if status is not None:
        status = _normalize_status(status)
        if status is None:
            return {"error": f"Invalid decision status '{status}'. Must be one of: {', '.join(sorted(VALID_STATUSES))}"}
    if owner is not None and not owner.strip():
        owner = None

    if status is None and owner is None:
        return {"error": "Provide at least one of: status, owner."}

    mysql_user = await _resolve_mysql_user(bridge, email)
    if mysql_user:
        mysql_org_id = mysql_user["org_id"]
    elif is_admin:
        # Admins without an employee_details row operate unscoped by ID
        mysql_org_id = None
    else:
        return {"error": "User not found in employee directory."}

    # Fetch decision (org-scoped for members, unscoped by ID for admins)
    if is_admin:
        rows = await bridge._mysql(
            "SELECT id, decision_value, status, priority, owner FROM decisions "
            "WHERE id = %s",
            (decision_id,),
        )
    else:
        rows = await bridge._mysql(
            "SELECT id, decision_value, status, priority, owner FROM decisions "
            "WHERE id = %s AND org_id = %s",
            (decision_id, mysql_org_id),
        )
    if not rows:
        if is_admin:
            return {"error": f"Decision {decision_id} not found."}
        return {"error": f"Decision {decision_id} not found in your organization."}

    decision = rows[0]
    dv = bridge._parse_json_col(decision, "decision_value")

    updates = []
    params: list = []

    if status is not None:
        old = decision.get("status", "")
        if old != status:
            updates.append("status = %s")
            params.append(status)
            changes = f"status from '{old}' to '{status}'"
        else:
            changes = None
    else:
        changes = None

    new_owner_emp_id = decision.get("owner")
    if owner is not None:
        owner_row = await resolve_owner_emp_id(bridge, owner)
        if not owner_row:
            suggestion = ""
            matches = await find_similar_employees(bridge, owner)
            if matches:
                suggestion = " Did you mean: " + ", ".join(matches) + "?"
            return {"error": f"Owner '{owner}' not found in the employee directory.{suggestion}"}
        if mysql_org_id is not None and owner_row["org_id"] != mysql_org_id:
            return {"error": "Cannot reassign decisions to users outside your organization."}
        new_owner_emp_id = owner_row["emp_id"]
        updates.append("owner = %s")
        params.append(new_owner_emp_id)
        dv["owner"] = owner.strip()

    if status is not None and decision.get("status") != status:
        dv["status"] = status

    if not updates and not (status is not None and decision.get("status") != status):
        return {
            "decision_id": decision_id,
            "action": "no_change",
            "confirmation": f"Decision #{decision_id} already reflects the requested values; no change made.",
        }

    # Persist both the column updates and the nested decision_value JSON
    set_items = ", ".join(updates + ["updated_time = NOW()"])
    if is_admin:
        await bridge._mysql_write(
            f"UPDATE decisions SET {set_items} WHERE id = %s",
            tuple(params + [decision_id]),
        )
    else:
        await bridge._mysql_write(
            f"UPDATE decisions SET {set_items} WHERE id = %s AND org_id = %s",
            tuple(params + [decision_id, mysql_org_id]),
        )

    if dv:
        if is_admin:
            await bridge._mysql_write(
                "UPDATE decisions SET decision_value = %s WHERE id = %s",
                (json.dumps(dv), decision_id),
            )
        else:
            await bridge._mysql_write(
                "UPDATE decisions SET decision_value = %s WHERE id = %s AND org_id = %s",
                (json.dumps(dv), decision_id, mysql_org_id),
            )

    confirmation_parts = []
    if status is not None and decision.get("status") != status:
        confirmation_parts.append(f"status to '{status}'")
    if owner is not None:
        confirmation_parts.append(f"owner to '{owner.strip()}'")

    confirmation = (
        f"Successfully updated Decision #{decision_id}: "
        + ", ".join(confirmation_parts)
        + " in the database."
    )

    logger.info("Decision updated via agent: id=%d", decision_id)
    return {
        "decision_id": decision_id,
        "action": "updated",
        "confirmation": confirmation,
    }
