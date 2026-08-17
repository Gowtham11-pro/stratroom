"""Task management tools for the AI Chat Engine.

Provides query and update functions that agents can invoke via tool calls.
All functions are async and accept a DB session + user context.
Supports RBAC: admin users see all org tasks, members see only assigned.
"""
import json
import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("stratroom.agents.task_tools")

_PRIORITY_MAP = {"critical": "Critical", "high": "High", "medium": "Medium", "low": "Low"}


def _parse_priorities(value: str | None) -> list[str]:
    """Split a priority filter like 'Critical+High' or 'Critical,High' into a list."""
    if not value:
        return []
    parts = [p.strip() for p in str(value).replace(",", "+").replace(";", "+").split("+")]
    return [_PRIORITY_MAP.get(p.lower(), p) for p in parts if p]


def _append_priority_clause(clauses: list, params: list, priority_filter: str | None) -> None:
    priorities = _parse_priorities(priority_filter)
    if not priorities:
        return
    if len(priorities) == 1:
        clauses.append("t.priority = %s")
        params.append(priorities[0])
    else:
        clauses.append("t.priority IN (" + ", ".join(["%s"] * len(priorities)) + ")")
        params.extend(priorities)


DEFAULT_OWNER_EMAIL = "dominic@demo.com"


async def resolve_owner_emp_id(bridge, owner_value: str) -> dict | None:
    """Resolve an owner string (email, full name, or first name) to an employee record.

    Returns a dict with emp_id, org_id, first_name, last_name, email_address,
    or None if nothing matched.
    """
    owner_value = (owner_value or "").strip()
    if not owner_value:
        return None
    queries = [
        ("SELECT emp_id, org_id, first_name, last_name, email_address FROM employee_details "
         "WHERE LOWER(email_address) = LOWER(%s) LIMIT 1", (owner_value,)),
        ("SELECT emp_id, org_id, first_name, last_name, email_address FROM employee_details "
         "WHERE LOWER(CONCAT_WS(' ', first_name, last_name)) = LOWER(%s) LIMIT 1", (owner_value,)),
        ("SELECT emp_id, org_id, first_name, last_name, email_address FROM employee_details "
         "WHERE LOWER(first_name) = LOWER(%s) LIMIT 1", (owner_value,)),
    ]
    for sql, args in queries:
        try:
            rows = await bridge._mysql(sql, args)
        except Exception:
            logger.exception("resolve_owner_emp_id query failed")
            continue
        if rows:
            return rows[0]
    return None


async def find_similar_employees(bridge, owner_value: str, limit: int = 3) -> list[str]:
    """Return human-readable suggestions for a near-miss owner lookup."""
    like = f"%{owner_value}%"
    try:
        rows = await bridge._mysql(
            "SELECT first_name, last_name, email_address FROM employee_details "
            "WHERE LOWER(first_name) LIKE LOWER(%s) OR LOWER(last_name) LIKE LOWER(%s) "
            "OR LOWER(email_address) LIKE LOWER(%s) LIMIT %s",
            (like, like, like, limit),
        )
    except Exception:
        logger.exception("find_similar_employees query failed")
        return []
    return [
        f"{r.get('first_name') or ''} {r.get('last_name') or ''} <{r.get('email_address')}>".strip()
        for r in rows
    ]


async def query_user_tasks(
    db: AsyncSession,
    user_id: int,
    org_id: int,
    status_filter: str | None = None,
    priority_filter: str | None = None,
    owner_email: str | None = None,
    source_module_filter: str | None = None,
    is_admin: bool = False,
    email: str | None = None,
    self_only: bool = False,
) -> dict:
    """Query tasks from MySQL via the bridge.

    Resolves the user's MySQL identity (emp_id, org_id) from their email.
    Admin users see all tasks in their MySQL org (optionally filtered by
    owner_email/name or source_module). Members see only tasks they own.

    When self_only is True (strict per-user isolation, e.g. for the chat
    task agent), even admins are scoped to the caller's own tasks.
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

    # 2. Build query
    if is_admin:
        clauses = []
        params = []
        if self_only:
            if not mysql_user:
                return {"tasks": [], "summary": {
                    "total": 0, "pending": 0, "in_progress": 0,
                    "completed": 0, "critical": 0, "high": 0,
                }}
            clauses.append("t.owner = %s")
            params.append(mysql_user["emp_id"])
        elif owner_email:
            owner_row = await resolve_owner_emp_id(bridge, owner_email)
            if not owner_row:
                return {"tasks": [], "summary": {
                    "total": 0, "pending": 0, "in_progress": 0,
                    "completed": 0, "critical": 0, "high": 0,
                }}
            clauses.append("t.owner = %s")
            params.append(owner_row["emp_id"])
        if status_filter:
            clauses.append("t.status = %s")
            params.append(status_filter)
        if source_module_filter:
            clauses.append("t.task_value LIKE %s")
            params.append(f'%"{source_module_filter.lower()}"%')
        _append_priority_clause(clauses, params, priority_filter)
        where_sql = (" WHERE " + " AND ".join(clauses)) if clauses else ""

        rows = await bridge._mysql(
            "SELECT t.ID, t.task_value, t.owner, t.priority, t.status "
            "FROM task_details t" + where_sql + " "
            "ORDER BY FIELD(t.priority, 'Critical', 'High', 'Medium', 'Low'), t.ID",
            tuple(params),
        )
    else:
        if not mysql_user:
            return {"tasks": [], "summary": {
                "total": 0, "pending": 0, "in_progress": 0,
                "completed": 0, "critical": 0, "high": 0,
            }}

        mysql_org_id = mysql_user["org_id"]
        emp_id = mysql_user["emp_id"]

        where_clauses = ["e.org_id = %s", "t.owner = %s"]
        params = [mysql_org_id, emp_id]

        if status_filter:
            where_clauses.append("t.status = %s")
            params.append(status_filter)
        if source_module_filter:
            where_clauses.append("t.task_value LIKE %s")
            params.append(f'%"{source_module_filter.lower()}"%')
        _append_priority_clause(where_clauses, params, priority_filter)

        where_sql = " AND ".join(where_clauses)

        rows = await bridge._mysql(
            "SELECT t.ID, t.task_value, t.owner, t.priority, t.status "
            "FROM task_details t "
            "JOIN employee_details e ON e.emp_id = t.owner "
            f"WHERE {where_sql} "
            "ORDER BY FIELD(t.priority, 'Critical', 'High', 'Medium', 'Low'), t.ID",
            tuple(params),
        )

    # 4. Parse task_value JSON into output shape
    tasks = []
    for row in rows:
        tv = bridge._parse_json_col(row, "task_value")
        src_mod = row.get("source_module") or tv.get("sourceModule") or tv.get("agent") or "general"
        raw_status = row.get("status")
        status = _normalize_status(raw_status) or str(raw_status or "").strip() or "pending"
        try:
            progress = tv.get("progress")
            progress = int(progress) if progress not in (None, "") else None
        except (TypeError, ValueError):
            progress = None
        tasks.append({
            "id": row.get("ID"),
            "title": tv.get("Name", tv.get("title", "")),
            "agent": tv.get("agent"),
            "source_module": src_mod,
            "priority": row.get("priority"),
            "owner": row.get("owner"),
            "due_date": tv.get("dueDate"),
            "status": status,
            "progress": progress,
            "assigned_user_id": tv.get("assignedUserId"),
        })

    summary = {
        "total": len(tasks),
        "pending": sum(1 for t in tasks if t["status"] == "pending"),
        "in_progress": sum(1 for t in tasks if t["status"] == "in_progress"),
        "completed": sum(1 for t in tasks if t["status"] == "completed"),
        "critical": sum(1 for t in tasks if t["priority"] == "Critical"),
        "high": sum(1 for t in tasks if t["priority"] == "High"),
    }

    return {"tasks": tasks, "summary": summary}


async def query_stagnant_tasks(days: int = 14) -> dict:
    """Find stagnant tasks (status != 'completed' and not updated in X days)."""
    from app.services.java_bridge import bridge
    try:
        rows = await bridge._mysql(
            "SELECT t.ID, t.task_value, t.owner, t.priority, t.status, t.updated_time, t.created_time "
            "FROM task_details t "
            "WHERE t.status != 'completed' AND t.updated_time < NOW() - INTERVAL %s DAY "
            "ORDER BY t.updated_time ASC",
            (days,),
        )
        stagnant = []
        for r in rows or []:
            tv = bridge._parse_json_col(r, "task_value")
            stagnant.append({
                "id": r.get("ID"),
                "title": tv.get("Name", tv.get("title", "")),
                "status": r.get("status"),
                "priority": r.get("priority"),
                "owner": r.get("owner"),
                "last_updated": str(r.get("updated_time") or r.get("created_time") or ""),
            })
        return {"stagnant_tasks": stagnant, "count": len(stagnant), "threshold_days": days}
    except Exception as exc:
        logger.warning("query_stagnant_tasks failed: %s", exc)
        return {"stagnant_tasks": [], "count": 0, "threshold_days": days}



def _normalize_status(status: str) -> str | None:
    """Map human-readable task statuses to the stored lowercase values."""
    mapping = {
        "pending": "pending",
        "open": "pending",
        "": "pending",
        "new": "pending",
        "not started": "pending",
        "in progress": "in_progress",
        "in-progress": "in_progress",
        "in_progress": "in_progress",
        "working": "in_progress",
        "started": "in_progress",
        "completed": "completed",
        "complete": "completed",
        "done": "completed",
        "finished": "completed",
        "closed": "completed",
    }
    return mapping.get((status or "").strip().lower())


async def update_task_status(
    db: AsyncSession,
    user_id: int,
    org_id: int,
    task_id: int,
    status: str | None = None,
    is_admin: bool = False,
    email: str | None = None,
) -> dict:
    """Update a task's status in MySQL via the bridge.

    Resolves the user's MySQL identity (emp_id, org_id) from their email.
    Uses JOIN with employee_details to verify the task belongs to the user's org.
    Non-admin members can only update tasks they own (t.owner = emp_id).
    Updates both the status column and the nested status inside task_value JSON.

    Valid statuses: 'pending', 'in_progress', 'completed'
    (human-readable variants like 'In Progress', 'Completed' are accepted).
    Returns the updated task or an error dict.
    """
    from app.services.java_bridge import bridge

    if status:
        normalized = _normalize_status(status)
        if normalized is None:
            return {"error": f"Invalid status '{status}'. Must be one of: pending, in_progress, completed"}
        status = normalized

    # 1. Resolve MySQL identity from email
    mysql_user = None
    if email:
        rows = await bridge._mysql(
            "SELECT emp_id, org_id FROM employee_details "
            "WHERE LOWER(email_address) = LOWER(%s) LIMIT 1",
            (email,),
        )
        mysql_user = rows[0] if rows else None

    if mysql_user:
        mysql_org_id = mysql_user["org_id"]
        emp_id = mysql_user["emp_id"]
    elif is_admin:
        # Admins without an employee_details row operate unscoped by ID —
        # org scoping is meaningless here (business data spans orgs 3-8
        # while admin users sit in org 1).
        mysql_org_id = None
        emp_id = None
    else:
        return {"error": "User not found in employee directory."}

    # 2. Fetch task with org + ownership verification
    if is_admin:
        rows = await bridge._mysql(
            "SELECT t.ID, t.task_value, t.status, t.priority, t.owner "
            "FROM task_details t "
            "WHERE t.ID = %s",
            (task_id,),
        )
    else:
        rows = await bridge._mysql(
            "SELECT t.ID, t.task_value, t.status, t.priority, t.owner "
            "FROM task_details t "
            "JOIN employee_details e ON e.emp_id = t.owner "
            "WHERE t.ID = %s AND e.org_id = %s AND t.owner = %s",
            (task_id, mysql_org_id, emp_id),
        )

    if not rows:
        if is_admin:
            return {"error": f"Task {task_id} not found."}
        return {"error": f"This task is not yours. Task {task_id} is not assigned to you."}

    task = rows[0]
    old_status = task.get("status") or ""

    # 3. Update if status changed
    action = "no_change"
    new_status = status if status else old_status

    if status and status != old_status:
        # 3a. Update the status column
        if is_admin:
            await bridge._mysql_write(
                "UPDATE task_details t "
                "SET t.status = %s, t.updated_time = NOW() "
                "WHERE t.ID = %s",
                (status, task_id),
            )
        else:
            await bridge._mysql_write(
                "UPDATE task_details t "
                "JOIN employee_details e ON e.emp_id = t.owner "
                "SET t.status = %s, t.updated_time = NOW() "
                "WHERE t.ID = %s AND e.org_id = %s AND t.owner = %s",
                (status, task_id, mysql_org_id, emp_id),
            )

        # 3b. Also update nested status inside task_value JSON for consistency
        tv = bridge._parse_json_col(task, "task_value")
        if tv:
            tv["status"] = status
            if is_admin:
                await bridge._mysql_write(
                    "UPDATE task_details t "
                    "SET t.task_value = %s "
                    "WHERE t.ID = %s",
                    (json.dumps(tv), task_id),
                )
            else:
                await bridge._mysql_write(
                    "UPDATE task_details t "
                    "JOIN employee_details e ON e.emp_id = t.owner "
                    "SET t.task_value = %s "
                    "WHERE t.ID = %s AND e.org_id = %s AND t.owner = %s",
                    (json.dumps(tv), task_id, mysql_org_id, emp_id),
                )

        action = "updated"
        new_status = status

    # 4. Build response
    tv = bridge._parse_json_col(task, "task_value")
    task_resp = {
        "id": task.get("ID"),
        "title": tv.get("Name", tv.get("title", "")),
        "status": new_status,
        "priority": task.get("priority"),
        "owner": task.get("owner"),
        "due_date": tv.get("dueDate"),
        "assigned_user_id": tv.get("assignedUserId"),
    }

    confirmation = (
        f"Successfully updated status for Task #{task_id} "
        f"from '{old_status}' to '{new_status}' in the database."
        if action == "updated"
        else f"Task #{task_id} status is already '{new_status}'; no change made."
    )

    return {
        "task": task_resp,
        "action": action,
        "old_status": old_status,
        "new_status": new_status,
        "confirmation": confirmation,
    }


async def update_task_progress(
    db: AsyncSession,
    user_id: int,
    org_id: int,
    task_id: int,
    progress: int | str | None = None,
    is_admin: bool = False,
    email: str | None = None,
) -> dict:
    """Update a task's progress percentage in MySQL via the bridge.

    Accepts progress 0-100 (clamped). Writes the `progress` key inside the
    `task_value` JSON blob. If progress reaches 100, the task status column
    is auto-set to 'completed' and the nested status is updated too.

    Returns a dict with a human-readable confirmation string.
    """
    from app.services.java_bridge import bridge

    # 1. Validate + clamp progress to 0-100
    if progress is None:
        return {"error": "progress is required. Usage: [TOOL_CALL:update_task_progress:task_id=102,progress=80]"}
    try:
        raw = int(progress)
    except (TypeError, ValueError):
        return {"error": f"progress must be an integer between 0 and 100, got '{progress}'"}
    new_progress = max(0, min(100, raw))
    clamped = raw != new_progress

    # 2. Resolve MySQL identity from email
    mysql_user = None
    if email:
        rows = await bridge._mysql(
            "SELECT emp_id, org_id FROM employee_details "
            "WHERE LOWER(email_address) = LOWER(%s) LIMIT 1",
            (email,),
        )
        mysql_user = rows[0] if rows else None

    if mysql_user:
        mysql_org_id = mysql_user["org_id"]
        emp_id = mysql_user["emp_id"]
    elif is_admin:
        # Admins without an employee_details row operate unscoped by ID —
        # org scoping is meaningless here (business data spans orgs 3-8
        # while admin users sit in org 1).
        mysql_org_id = None
        emp_id = None
    else:
        return {"error": "User not found in employee directory."}

    # 3. Fetch task with org + ownership verification
    if is_admin:
        rows = await bridge._mysql(
            "SELECT t.ID, t.task_value, t.status, t.priority, t.owner "
            "FROM task_details t "
            "WHERE t.ID = %s",
            (task_id,),
        )
    else:
        rows = await bridge._mysql(
            "SELECT t.ID, t.task_value, t.status, t.priority, t.owner "
            "FROM task_details t "
            "JOIN employee_details e ON e.emp_id = t.owner "
            "WHERE t.ID = %s AND e.org_id = %s AND t.owner = %s",
            (task_id, mysql_org_id, emp_id),
        )

    if not rows:
        if is_admin:
            return {"error": f"Task {task_id} not found."}
        return {"error": f"This task is not yours. Task {task_id} is not assigned to you."}

    task = rows[0]
    tv = bridge._parse_json_col(task, "task_value")
    try:
        old_progress = int(tv.get("progress", 0) or 0)
    except (TypeError, ValueError):
        old_progress = 0

    # 4. Write the progress key into task_value JSON
    tv["progress"] = new_progress

    auto_complete = new_progress >= 100
    auto_start = 0 < new_progress < 100
    if auto_complete:
        tv["status"] = "completed"
    elif auto_start:
        tv["status"] = "in_progress"
    new_status = "completed" if auto_complete else ("in_progress" if auto_start else "pending")

    if is_admin:
        await bridge._mysql_write(
            "UPDATE task_details t "
            "SET t.task_value = %s, t.updated_time = NOW() "
            "WHERE t.ID = %s",
            (json.dumps(tv), task_id),
        )
    else:
        await bridge._mysql_write(
            "UPDATE task_details t "
            "JOIN employee_details e ON e.emp_id = t.owner "
            "SET t.task_value = %s, t.updated_time = NOW() "
            "WHERE t.ID = %s AND e.org_id = %s AND t.owner = %s",
            (json.dumps(tv), task_id, mysql_org_id, emp_id),
        )

    # 4b. Auto-update the status column to reflect progress (pending/in_progress/completed)
    if is_admin:
        await bridge._mysql_write(
            "UPDATE task_details t "
            "SET t.status = %s "
            "WHERE t.ID = %s",
            (new_status, task_id),
        )
    else:
        await bridge._mysql_write(
            "UPDATE task_details t "
            "JOIN employee_details e ON e.emp_id = t.owner "
            "SET t.status = %s "
            "WHERE t.ID = %s AND e.org_id = %s AND t.owner = %s",
            (new_status, task_id, mysql_org_id, emp_id),
        )

    # 5. Build response with confirmation string
    confirmation = (
        f"Successfully updated progress for Task #{task_id} "
        f"from {old_progress}% to {new_progress}% in the database."
    )
    if clamped:
        confirmation += (
            f" Note: the requested value {raw} was out of range and has "
            f"been clamped to {new_progress}% (progress must be 0-100)."
        )
    if auto_complete:
        confirmation += " Task auto-marked as Completed."
    elif auto_start:
        confirmation += " Task marked as In Progress."
    else:
        confirmation += " Task remains Pending."

    return {
        "task_id": task_id,
        "old_progress": old_progress,
        "new_progress": new_progress,
        "auto_completed": auto_complete,
        "confirmation": confirmation,
    }


async def create_task_tool(
    db: AsyncSession,
    org_id: int,
    title: str,
    agent: str | None = None,
    priority: str = "Medium",
    owner: str | None = None,
    due_date: str | None = None,
    status: str = "pending",
    assigned_user_id: int | None = None,
    description: str | None = None,
    linked_risk_id: int | None = None,
    source_module: str | None = None,
    email: str | None = None,
    is_admin: bool = False,
) -> dict:
    """Create a new task in MySQL via the bridge.

    Resolves the creator's MySQL identity from email. Owner can be
    specified as an email string (resolved to emp_id). If no owner is
    provided, defaults to the creator's emp_id.

    Cross-org assignment is explicitly blocked — owner must belong to
    the same org as the creator.

    Priority: Critical, High, Medium, Low.
    Status: pending, in_progress, completed.
    source_module specifies module origin (pestel, swot, risk, compliance, etc.).
    Returns the created task record or an error dict.
    """
    from app.services.java_bridge import bridge

    valid_priorities = {"Critical", "High", "Medium", "Low"}
    valid_statuses = {"pending", "in_progress", "completed"}

    if not title or not title.strip():
        return {"error": "Task title is required"}
    if priority not in valid_priorities:
        return {"error": f"Invalid priority '{priority}'. Must be one of: {', '.join(sorted(valid_priorities))}"}
    if status not in valid_statuses:
        return {"error": f"Invalid status '{status}'. Must be one of: {', '.join(sorted(valid_statuses))}"}

    # 1. Resolve creator's MySQL identity
    mysql_user = None
    if email:
        rows = await bridge._mysql(
            "SELECT emp_id, org_id FROM employee_details "
            "WHERE LOWER(email_address) = LOWER(%s) LIMIT 1",
            (email,),
        )
        mysql_user = rows[0] if rows else None

    if mysql_user:
        creator_org_id = mysql_user["org_id"]
        creator_emp_id = mysql_user["emp_id"]
    elif is_admin:
        creator_org_id = org_id
        creator_emp_id = None
    else:
        return {"error": "User not found in employee directory."}

    # 2. Resolve task owner
    if owner and owner.strip():
        owner_row = await resolve_owner_emp_id(bridge, owner)
        if not owner_row:
            suggestion = ""
            matches = await find_similar_employees(bridge, owner)
            if matches:
                suggestion = " Did you mean: " + ", ".join(matches) + "?"
            return {"error": f"Owner '{owner}' not found in the employee directory.{suggestion}"}

        owner_emp_id = owner_row["emp_id"]
        owner_org_id = owner_row["org_id"]

        if creator_emp_id is not None and owner_org_id != creator_org_id:
            return {"error": "Cannot assign tasks to users outside your organization."}
    else:
        if creator_emp_id is None:
            default_row = await resolve_owner_emp_id(bridge, DEFAULT_OWNER_EMAIL)
            if default_row:
                owner_emp_id = default_row["emp_id"]
            else:
                return {"error": "You are not in the employee directory. Please specify an owner=email@x.com to assign this task to."}
        else:
            owner_emp_id = creator_emp_id

    # 3. Build task_value JSON matching existing MySQL shape
    effective_source_mod = source_module or agent or ("risk" if linked_risk_id else "general")
    task_value = {
        "Name": title.strip(),
        "status": status,
        "priority": priority,
        "sourceModule": effective_source_mod,
    }
    if agent:
        task_value["agent"] = agent
    if due_date:
        task_value["dueDate"] = due_date
    if assigned_user_id is not None:
        task_value["assignedUserId"] = assigned_user_id
    if description:
        task_value["description"] = description
    if linked_risk_id is not None:
        task_value["linkedRiskId"] = linked_risk_id
        task_value["sourceModule"] = "risk"

    # 4. INSERT into MySQL
    task_id = await bridge._mysql_write(
        "INSERT INTO task_details (task_value, active, owner, created_time, updated_time, priority, status) "
        "VALUES (%s, %s, %s, NOW(), NOW(), %s, %s)",
        (json.dumps(task_value), 1, owner_emp_id, priority, status),
    )

    logger.info("Task created via agent: id=%d org=%s owner_emp=%d source_module=%s", task_id, creator_org_id, owner_emp_id, effective_source_mod)
    return {
        "id": task_id,
        "title": title.strip(),
        "priority": priority,
        "status": status,
        "source_module": effective_source_mod,
        "action": "created",
    }


async def create_risk_mitigation_task(
    db: AsyncSession,
    org_id: int,
    risk_id: int,
    mitigation: str = "",
    owner: str | None = None,
    priority: str = "High",
    due_date: str | None = None,
    email: str | None = None,
    is_admin: bool = False,
) -> dict:
    """Create a task linked to a risk that tracks its mitigation plan.

    Looks up the risk in risk_details to derive the task title, then
    creates a linked task in task_details (via create_task_tool) with
    linkedRiskId + sourceModule='risk' stored in the task_value JSON.

    Returns the created task and a human-readable confirmation string.
    """
    from app.services.java_bridge import bridge

    # 1. Validate risk_id and look up the risk name
    if not isinstance(risk_id, int):
        return {"error": f"risk_id must be an integer, got '{risk_id}'"}

    rows = await bridge._mysql(
        "SELECT ID, risk_value FROM risk_details WHERE ID = %s",
        (risk_id,),
    )
    if not rows:
        return {"error": f"Risk #{risk_id} not found in the risk register."}

    rv = bridge._parse_json_col(rows[0], "risk_value")
    risk_name = rv.get("name") or f"Risk #{risk_id}"
    risk_heat = rv.get("score") or ""
    heat = ""
    try:
        heat = f" (heat {risk_heat}/25)" if risk_heat else ""
    except (TypeError, ValueError):
        heat = ""

    title = f"Mitigation task for Risk #{risk_id}: {risk_name}{heat}"
    if mitigation and mitigation.strip():
        description = mitigation.strip()
    else:
        description = f"Implement mitigation for risk '{risk_name}' (Risk #{risk_id})."

    # 2. Create the linked task
    result = await create_task_tool(
        db,
        org_id,
        title=title,
        agent="risk",
        priority=priority,
        owner=owner,
        due_date=due_date,
        status="pending",
        description=description,
        linked_risk_id=risk_id,
        email=email,
        is_admin=is_admin,
    )

    if "error" in result:
        return result

    confirmation = (
        f"Successfully created a linked mitigation task #{result['id']} for Risk #{risk_id} "
        f"('{risk_name}') in the database."
    )
    result["confirmation"] = confirmation
    result["risk_id"] = risk_id
    return result


def format_task_list(tasks: list[dict]) -> str:
    """Format a task list as readable text for LLM context injection."""
    if not tasks:
        return "No tasks found."
    lines = []
    for t in tasks:
        status_icon = {"pending": "⏳", "in_progress": "🔄", "completed": "✅"}.get(t["status"], "❓")
        priority_icon = {"Critical": "🔴", "High": "🟠", "Medium": "🟡", "Low": "🟢"}.get(t["priority"], "⚪")
        lines.append(
            f"{status_icon} [{priority_icon} {t['priority']}] Task #{t['id']}: {t['title']} "
            f"| Status: {t['status']} | Owner: {t.get('owner', '—')} | Due: {t.get('due_date', '—')}"
        )
    return "\n".join(lines)
