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


async def query_user_tasks(
    db: AsyncSession,
    user_id: int,
    org_id: int,
    status_filter: str | None = None,
    priority_filter: str | None = None,
    is_admin: bool = False,
    email: str | None = None,
) -> dict:
    """Query tasks from MySQL via the bridge.

    Resolves the user's MySQL identity (emp_id, org_id) from their email.
    Admin users see all tasks in their MySQL org.
    Members see only tasks they own (t.owner = emp_id).

    If the user has no MySQL employee record (e.g. PG-only admin),
    returns empty results — safe fallback.
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

    # 2. Fail-safe: no MySQL identity → empty results
    if not mysql_user:
        return {"tasks": [], "summary": {
            "total": 0, "pending": 0, "in_progress": 0,
            "completed": 0, "critical": 0, "high": 0,
        }}

    mysql_org_id = mysql_user["org_id"]
    emp_id = mysql_user["emp_id"]

    # 3. Build query — org scoped via JOIN, always applied
    where_clauses = ["e.org_id = %s"]
    params = [mysql_org_id]

    if not is_admin:
        where_clauses.append("t.owner = %s")
        params.append(emp_id)

    if status_filter:
        where_clauses.append("t.status = %s")
        params.append(status_filter)
    if priority_filter:
        where_clauses.append("t.priority = %s")
        params.append(priority_filter)

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
        tasks.append({
            "id": row.get("ID"),
            "title": tv.get("Name", tv.get("title", "")),
            "agent": tv.get("agent"),
            "priority": row.get("priority"),
            "owner": row.get("owner"),
            "due_date": tv.get("dueDate"),
            "status": row.get("status"),
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


async def update_task_progress(
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

    Valid statuses: 'pending', 'in_progress', 'completed'.
    Returns the updated task or an error dict.
    """
    from app.services.java_bridge import bridge

    valid_statuses = {"pending", "in_progress", "completed"}
    if status and status not in valid_statuses:
        return {"error": f"Invalid status '{status}'. Must be one of: {', '.join(sorted(valid_statuses))}"}

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
        return {"error": "User not found in employee directory."}

    mysql_org_id = mysql_user["org_id"]
    emp_id = mysql_user["emp_id"]

    # 2. Fetch task with org + ownership verification via JOIN
    if is_admin:
        rows = await bridge._mysql(
            "SELECT t.ID, t.task_value, t.status, t.priority, t.owner "
            "FROM task_details t "
            "JOIN employee_details e ON e.emp_id = t.owner "
            "WHERE t.ID = %s AND e.org_id = %s",
            (task_id, mysql_org_id),
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
            return {"error": f"Task {task_id} not found in your organization."}
        return {"error": f"This task is not yours. Task {task_id} is not assigned to you."}

    task = rows[0]
    old_status = task.get("status") or ""

    # 3. Update if status changed
    action = "no_change"
    new_status = status if status else old_status

    if status and status != old_status:
        # 3a. Update the status column — TOCTOU-safe: same org/owner scoping
        if is_admin:
            await bridge._mysql_write(
                "UPDATE task_details t "
                "JOIN employee_details e ON e.emp_id = t.owner "
                "SET t.status = %s, t.updated_time = NOW() "
                "WHERE t.ID = %s AND e.org_id = %s",
                (status, task_id, mysql_org_id),
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
                    "JOIN employee_details e ON e.emp_id = t.owner "
                    "SET t.task_value = %s "
                    "WHERE t.ID = %s AND e.org_id = %s",
                    (json.dumps(tv), task_id, mysql_org_id),
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

    return {
        "task": task_resp,
        "action": action,
        "old_status": old_status,
        "new_status": new_status,
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
            return {"error": "Cannot assign tasks to users outside your organization."}
    else:
        owner_emp_id = creator_emp_id

    # 3. Build task_value JSON matching existing MySQL shape
    task_value = {
        "Name": title.strip(),
        "status": status,
        "priority": priority,
    }
    if agent:
        task_value["agent"] = agent
    if due_date:
        task_value["dueDate"] = due_date
    if assigned_user_id is not None:
        task_value["assignedUserId"] = assigned_user_id

    # 4. INSERT into MySQL
    task_id = await bridge._mysql_write(
        "INSERT INTO task_details (task_value, active, owner, created_time, updated_time, priority, status) "
        "VALUES (%s, %s, %s, NOW(), NOW(), %s, %s)",
        (json.dumps(task_value), 1, owner_emp_id, priority, status),
    )

    logger.info("Task created via agent: id=%d org=%s owner_emp=%d", task_id, creator_org_id, owner_emp_id)
    return {
        "id": task_id,
        "title": title.strip(),
        "priority": priority,
        "status": status,
        "action": "created",
    }


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
