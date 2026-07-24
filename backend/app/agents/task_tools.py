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
) -> dict:
    """Query tasks for the current user.

    Admin users see all tasks in the org. Members see only assigned tasks.
    Returns a dict with 'tasks' list and 'summary' stats.
    Optional filters: status ('pending', 'in_progress', 'completed'), priority.
    """
    where_clauses = ["org_id = :oid"]
    params: dict = {"oid": org_id}

    if not is_admin:
        where_clauses.append("assigned_user_id = :uid")
        params["uid"] = user_id

    if status_filter:
        where_clauses.append("status = :status")
        params["status"] = status_filter
    if priority_filter:
        where_clauses.append("priority = :priority")
        params["priority"] = priority_filter

    where_sql = " AND ".join(where_clauses)

    result = await db.execute(
        text(
            f"SELECT id, title, agent, priority, owner, due_date, status, assigned_user_id "
            f"FROM tasks WHERE {where_sql} "
            f"ORDER BY CASE priority "
            f"WHEN 'Critical' THEN 1 WHEN 'High' THEN 2 WHEN 'Medium' THEN 3 "
            f"ELSE 4 END, id"
        ),
        params,
    )
    tasks = [dict(r) for r in result.mappings().all()]

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
) -> dict:
    """Update a task's status.

    Members can only update tasks assigned to them.
    Admins can update any task in their org.

    Valid statuses: 'pending', 'in_progress', 'completed'.
    Returns the updated task or an error dict.
    """
    valid_statuses = {"pending", "in_progress", "completed"}
    if status and status not in valid_statuses:
        return {"error": f"Invalid status '{status}'. Must be one of: {', '.join(sorted(valid_statuses))}"}

    if is_admin:
        result = await db.execute(
            text(
                "SELECT id, title, status, priority, owner, due_date, assigned_user_id "
                "FROM tasks WHERE id = :tid AND org_id = :oid"
            ),
            {"tid": task_id, "oid": org_id},
        )
    else:
        result = await db.execute(
            text(
                "SELECT id, title, status, priority, owner, due_date, assigned_user_id "
                "FROM tasks WHERE id = :tid AND org_id = :oid AND assigned_user_id = :uid"
            ),
            {"tid": task_id, "oid": org_id, "uid": user_id},
        )
    task = result.mappings().first()
    if not task:
        if is_admin:
            return {"error": f"Task {task_id} not found in your organization."}
        return {"error": f"This task is not yours. Task {task_id} is not assigned to you."}

    task = dict(task)
    old_status = task["status"]

    if status and status != old_status:
        if is_admin:
            await db.execute(
                text("UPDATE tasks SET status = :status WHERE id = :tid AND org_id = :oid"),
                {"status": status, "tid": task_id, "oid": org_id},
            )
        else:
            await db.execute(
                text("UPDATE tasks SET status = :status WHERE id = :tid AND org_id = :oid AND assigned_user_id = :uid"),
                {"status": status, "tid": task_id, "oid": org_id, "uid": user_id},
            )
        await db.commit()
        task["status"] = status

    action = "updated" if status and status != old_status else "no_change"
    return {
        "task": task,
        "action": action,
        "old_status": old_status,
        "new_status": task["status"],
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
) -> dict:
    """Create a new task record in the database.

    Priority must be one of: Critical, High, Medium, Low.
    Status must be one of: pending, in_progress, completed.
    Requires manager+ role (enforced at router level).
    Returns the created task record.
    """
    valid_priorities = {"Critical", "High", "Medium", "Low"}
    valid_statuses = {"pending", "in_progress", "completed"}

    if not title or not title.strip():
        return {"error": "Task title is required"}
    if priority not in valid_priorities:
        return {"error": f"Invalid priority '{priority}'. Must be one of: {', '.join(sorted(valid_priorities))}"}
    if status not in valid_statuses:
        return {"error": f"Invalid status '{status}'. Must be one of: {', '.join(sorted(valid_statuses))}"}

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
            "INSERT INTO tasks (org_id, title, agent, priority, owner, due_date, status, assigned_user_id) "
            "VALUES (:oid, :title, :agent, :priority, :owner, :due_date, :status, :assigned_user_id) "
            "RETURNING id"
        ),
        {
            "oid": org_id,
            "title": title.strip(),
            "agent": agent,
            "priority": priority,
            "owner": owner,
            "due_date": due_date,
            "status": status,
            "assigned_user_id": assigned_user_id,
        },
    )
    task_id = result.scalar()
    await db.commit()

    logger.info("Task created via agent: id=%d org=%s", task_id, org_id)
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
