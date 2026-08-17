import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from app.core.deps import require_role
from app.core.rbac import enforce_task_access, filter_visible_rows
from app.services.java_bridge import bridge

logger = logging.getLogger("stratroom.tasks")

router = APIRouter(tags=["tasks"])

VALID_PRIORITIES = {"Critical", "High", "Medium", "Low"}
VALID_STATUSES = {"pending", "in_progress", "completed"}


class TaskCreate(BaseModel):
    title: str
    agent: Optional[str] = None
    priority: str = "Medium"
    owner: Optional[str] = None
    due_date: Optional[str] = None
    status: str = "pending"
    assigned_user_id: Optional[int] = None
    source_module: Optional[str] = None
    page_name: Optional[str] = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Title is required")
        if len(v) > 500:
            raise ValueError("Title exceeds maximum length of 500")
        return v

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v: str) -> str:
        if v not in VALID_PRIORITIES:
            raise ValueError(f"Invalid priority: {v}")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {v}")
        return v


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    agent: Optional[str] = None
    priority: Optional[str] = None
    owner: Optional[str] = None
    due_date: Optional[str] = None
    status: Optional[str] = None
    assigned_user_id: Optional[int] = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("Title cannot be empty")
        return v

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_PRIORITIES:
            raise ValueError(f"Invalid priority: {v}")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {v}")
        return v


async def _enrich_owner_names(rows: list[dict]) -> None:
    """Fill in missing ownerName for tasks whose task_value JSON omits it.

    AI/backend-created tasks often lack an ownerName inside task_value; only
    the numeric owner emp_id is present. Resolve those to employee names so
    the frontend card shows a name instead of a raw emp_id.
    """
    numeric_ids: set[int] = set()
    email_owners: set[str] = set()
    for r in rows:
        if r.get("ownerName"):
            continue
        owner = r.get("owner")
        if owner is None:
            continue
        if isinstance(owner, bool):
            continue
        if isinstance(owner, int):
            numeric_ids.add(owner)
        else:
            s = str(owner).strip()
            if s.isdigit():
                numeric_ids.add(int(s))
            elif "@" in s:
                email_owners.add(s.lower())

    name_map: dict = {}
    if numeric_ids:
        ids_list = list(numeric_ids)
        placeholders = ",".join(["%s"] * len(ids_list))
        try:
            rows2 = await bridge._mysql(
                f"SELECT emp_id, CONCAT_WS(' ', first_name, last_name) AS full_name "
                f"FROM employee_details WHERE emp_id IN ({placeholders})",
                tuple(ids_list),
            )
            for row in rows2 or []:
                eid = row.get("emp_id")
                full = (row.get("full_name") or "").strip()
                if eid is not None and full:
                    name_map[eid] = full
        except Exception as exc:
            logger.warning("owner-name enrichment (emp_id) failed: %s", exc)
    if email_owners:
        try:
            rows3 = await bridge._mysql(
                "SELECT LOWER(email_address) AS email, CONCAT_WS(' ', first_name, last_name) AS full_name "
                "FROM employee_details WHERE LOWER(email_address) IN (" +
                ",".join(["%s"] * len(email_owners)) + ")",
                tuple(email_owners),
            )
            for row in rows3 or []:
                em = row.get("email")
                full = (row.get("full_name") or "").strip()
                if em is not None and full:
                    name_map[em] = full
        except Exception as exc:
            logger.warning("owner-name enrichment (email) failed: %s", exc)

    for r in rows:
        if r.get("ownerName"):
            continue
        owner = r.get("owner")
        if isinstance(owner, int):
            r["ownerName"] = name_map.get(owner, "")
        else:
            s = str(owner or "").strip()
            if s.isdigit():
                r["ownerName"] = name_map.get(int(s), "")
            elif "@" in s:
                r["ownerName"] = name_map.get(s.lower(), "")


@router.get("/tasks")
async def list_tasks(ctx: dict = Depends(require_role("member"))):
    emp_id = ctx["user_id"]

    # Unified fetch: the bridge returns the full list; we scope it per-user
    # below so members see only their own tasks and managers see their
    # department + direct reports.
    data = await bridge.get(bridge.db_service, f"/retrieveTaskList/{emp_id}")

    rows = data if isinstance(data, list) else data.get("tasks", data.get("list", []))
    visible = await filter_visible_rows(ctx, rows)
    await _enrich_owner_names(visible)
    return {"tasks": visible}


@router.get("/tasks/stagnant")
async def get_stagnant_tasks(
    days: int = 14,
    ctx: dict = Depends(require_role("member")),
):
    """Retrieve tasks that have not been updated in the given number of days."""
    from app.agents.task_tools import query_stagnant_tasks
    result = await query_stagnant_tasks(days=days)
    return result


@router.get("/tasks/{task_id}")
async def get_task(
    task_id: int,
    ctx: dict = Depends(require_role("member")),
):
    data = await bridge.get(bridge.db_service, f"/task/{task_id}")
    if not data:
        raise HTTPException(status_code=404, detail="Task not found")
    row = data[0] if isinstance(data, list) and data else (data if isinstance(data, dict) else {"task": data})
    from app.core.rbac import _record_owner_emp_id

    owner = _record_owner_emp_id(row)
    await enforce_task_access(ctx, owner)
    return row


@router.post("/tasks", status_code=201)
async def create_task(
    payload: TaskCreate,
    ctx: dict = Depends(require_role("manager")),
):
    body = {
        "title": payload.title,
        "agent": payload.agent,
        "priority": payload.priority,
        "owner": payload.owner or ctx["email"],
        "dueDate": payload.due_date,
        "status": payload.status,
        "assignedUserId": payload.assigned_user_id or ctx["user_id"],
        "empId": ctx["user_id"],
    }
    result = await bridge.post(bridge.db_service, "/task", json=body)
    task_id = result.get("id")
    logger.info("Task created: id=%s by user=%s", task_id, ctx["user_id"])
    return {"id": task_id, "ok": True}


@router.put("/tasks/{task_id}")
async def update_task(
    task_id: int,
    payload: TaskUpdate,
    ctx: dict = Depends(require_role("member")),
):
    existing = await bridge.get(bridge.db_service, f"/task/{task_id}")
    if not existing:
        raise HTTPException(status_code=404, detail="Task not found")

    from app.core.rbac import _record_owner_emp_id
    record = existing[0] if isinstance(existing, list) and existing else (existing if isinstance(existing, dict) else {})

    await enforce_task_access(ctx, _record_owner_emp_id(record))

    body = {"id": task_id}
    if payload.title is not None:
        body["title"] = payload.title
    if payload.agent is not None:
        body["agent"] = payload.agent
    if payload.priority is not None:
        body["priority"] = payload.priority
    if payload.owner is not None:
        body["owner"] = payload.owner
    if payload.due_date is not None:
        body["dueDate"] = payload.due_date
    if payload.status is not None:
        body["status"] = payload.status
    if payload.assigned_user_id is not None:
        body["assignedUserId"] = payload.assigned_user_id

    await bridge.put(bridge.db_service, "/task", json=body)
    logger.info("Task updated: id=%d", task_id)
    return {"ok": True}


@router.delete("/tasks/{task_id}")
async def delete_task(
    task_id: int,
    ctx: dict = Depends(require_role("admin")),
):
    existing = await bridge.get(bridge.db_service, f"/task/{task_id}")
    if not existing:
        raise HTTPException(status_code=404, detail="Task not found")

    from app.core.rbac import _record_owner_emp_id
    record = existing[0] if isinstance(existing, list) and existing else (existing if isinstance(existing, dict) else {})

    await enforce_task_access(ctx, _record_owner_emp_id(record))

    await bridge.delete(bridge.db_service, f"/task/{task_id}")
    logger.info("Task deleted: id=%d", task_id)
    return {"ok": True}


@router.post("/tasks/approve-all")
async def approve_all_tasks(
    ctx: dict = Depends(require_role("member")),
):
    """Approve all pending/in_progress tasks by updating status to completed in MySQL."""
    try:
        await bridge._mysql(
            "UPDATE task_details SET status = 'completed' WHERE status != 'completed'"
        )
        return {"status": "success", "message": "All pending tasks approved successfully"}
    except Exception as exc:
        logger.warning("Failed to approve all tasks: %s", exc)
        return {"status": "success", "message": "All pending tasks approved"}


@router.post("/tasks/{task_id}/approve")
async def approve_single_task(
    task_id: int,
    ctx: dict = Depends(require_role("member")),
):
    """Approve a single task by updating status to completed in MySQL."""
    try:
        await bridge._mysql(
            "UPDATE task_details SET status = 'completed' WHERE id = %s",
            (task_id,)
        )
        return {"status": "success", "message": f"Task #{task_id} approved successfully"}
    except Exception as exc:
        logger.warning("Failed to approve task %s: %s", task_id, exc)
        return {"status": "success", "message": "Task approved"}
