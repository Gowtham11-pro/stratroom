import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import require_role
from app.core.config import settings

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

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Title is required")
        if len(v) > 500:
            raise ValueError(f"Title exceeds maximum length of 500")
        return v

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v: str) -> str:
        if v not in VALID_PRIORITIES:
            raise ValueError(f"Invalid priority: {v}. Must be one of: {', '.join(sorted(VALID_PRIORITIES))}")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {v}. Must be one of: {', '.join(sorted(VALID_STATUSES))}")
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
            if len(v) > 500:
                raise ValueError(f"Title exceeds maximum length of 500")
        return v

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_PRIORITIES:
            raise ValueError(f"Invalid priority: {v}. Must be one of: {', '.join(sorted(VALID_PRIORITIES))}")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {v}. Must be one of: {', '.join(sorted(VALID_STATUSES))}")
        return v


@router.get("/tasks")
async def list_tasks(
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("member")),
):
    user_id = ctx["user_id"]
    org_id = ctx["org_id"]
    is_admin = ctx["is_admin"]
    is_manager = ctx["is_manager"]

    if is_admin or is_manager:
        result = await db.execute(
            text(
                "SELECT id, title, agent, priority, owner, due_date, status, assigned_user_id "
                "FROM tasks WHERE org_id = :oid "
                "ORDER BY CASE priority "
                "WHEN 'Critical' THEN 1 WHEN 'High' THEN 2 WHEN 'Medium' THEN 3 "
                "ELSE 4 END, id"
            ),
            {"oid": org_id},
        )
    else:
        result = await db.execute(
            text(
                "SELECT id, title, agent, priority, owner, due_date, status, assigned_user_id "
                "FROM tasks WHERE org_id = :oid AND assigned_user_id = :uid "
                "ORDER BY CASE priority "
                "WHEN 'Critical' THEN 1 WHEN 'High' THEN 2 WHEN 'Medium' THEN 3 "
                "ELSE 4 END, id"
            ),
            {"oid": org_id, "uid": user_id},
        )
    rows = result.mappings().all()
    return {"tasks": [dict(r) for r in rows]}


@router.get("/tasks/{task_id}")
async def get_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("member")),
):
    user_id = ctx["user_id"]
    org_id = ctx["org_id"]
    is_admin = ctx["is_admin"]
    is_manager = ctx["is_manager"]

    if is_admin or is_manager:
        result = await db.execute(
            text(
                "SELECT id, title, agent, priority, owner, due_date, status, assigned_user_id "
                "FROM tasks WHERE id = :tid AND org_id = :oid"
            ),
            {"tid": task_id, "oid": org_id},
        )
    else:
        result = await db.execute(
            text(
                "SELECT id, title, agent, priority, owner, due_date, status, assigned_user_id "
                "FROM tasks WHERE id = :tid AND org_id = :oid AND assigned_user_id = :uid"
            ),
            {"tid": task_id, "oid": org_id, "uid": user_id},
        )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Task not found or not assigned to you")
    return dict(row)


@router.post("/tasks", status_code=201)
async def create_task(
    payload: TaskCreate,
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("manager")),
):
    org_id = ctx["org_id"]

    if payload.assigned_user_id:
        user_check = await db.execute(
            text("SELECT id FROM users WHERE id = :uid AND org_id = :oid"),
            {"uid": payload.assigned_user_id, "oid": org_id},
        )
        if not user_check.first():
            raise HTTPException(status_code=400, detail="Assigned user not found in this organization")

    result = await db.execute(
        text(
            "INSERT INTO tasks (org_id, title, agent, priority, owner, due_date, status, assigned_user_id) "
            "VALUES (:oid, :title, :agent, :priority, :owner, :due_date, :status, :assigned_user_id) "
            "RETURNING id"
        ),
        {
            "oid": org_id,
            "title": payload.title,
            "agent": payload.agent,
            "priority": payload.priority,
            "owner": payload.owner,
            "due_date": payload.due_date,
            "status": payload.status,
            "assigned_user_id": payload.assigned_user_id,
        },
    )
    task_id = result.scalar()
    await db.commit()

    logger.info("Task created: id=%d org=%s by user=%s", task_id, org_id, ctx["user_id"])
    return {"id": task_id, "ok": True}


@router.put("/tasks/{task_id}")
async def update_task(
    task_id: int,
    payload: TaskUpdate,
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("member")),
):
    user_id = ctx["user_id"]
    org_id = ctx["org_id"]
    is_admin = ctx["is_admin"]
    is_manager = ctx["is_manager"]

    if is_admin:
        result = await db.execute(
            text(
                "SELECT id, assigned_user_id FROM tasks WHERE id = :tid AND org_id = :oid"
            ),
            {"tid": task_id, "oid": org_id},
        )
    else:
        result = await db.execute(
            text(
                "SELECT id, assigned_user_id FROM tasks WHERE id = :tid AND org_id = :oid AND assigned_user_id = :uid"
            ),
            {"tid": task_id, "oid": org_id, "uid": user_id},
        )
    existing = result.mappings().first()
    if not existing:
        raise HTTPException(status_code=404, detail="This task is not yours.")

    updates = {}
    if payload.title is not None:
        updates["title"] = payload.title
    if payload.agent is not None:
        updates["agent"] = payload.agent
    if payload.priority is not None:
        updates["priority"] = payload.priority
    if payload.owner is not None:
        updates["owner"] = payload.owner
    if payload.due_date is not None:
        updates["due_date"] = payload.due_date
    if payload.status is not None:
        updates["status"] = payload.status
    if payload.assigned_user_id is not None:
        if not is_admin:
            raise HTTPException(status_code=403, detail="Only admins can reassign tasks")
        user_check = await db.execute(
            text("SELECT id FROM users WHERE id = :uid AND org_id = :oid"),
            {"uid": payload.assigned_user_id, "oid": org_id},
        )
        if not user_check.first():
            raise HTTPException(status_code=400, detail="Assigned user not found in this organization")
        updates["assigned_user_id"] = payload.assigned_user_id

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    set_clause = ", ".join(f"{k} = :{k}" for k in updates)
    updates["tid"] = task_id
    updates["oid"] = org_id

    await db.execute(
        text(f"UPDATE tasks SET {set_clause} WHERE id = :tid AND org_id = :oid"),
        updates,
    )
    await db.commit()

    logger.info("Task updated: id=%d org=%s by user=%s", task_id, org_id, user_id)
    return {"ok": True}


@router.delete("/tasks/{task_id}")
async def delete_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("admin")),
):
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    result = await db.execute(
        text("SELECT id FROM tasks WHERE id = :tid AND org_id = :oid"),
        {"tid": task_id, "oid": org_id},
    )
    if not result.first():
        raise HTTPException(status_code=404, detail="Task not found")

    await db.execute(
        text("DELETE FROM tasks WHERE id = :tid AND org_id = :oid"),
        {"tid": task_id, "oid": org_id},
    )
    await db.commit()

    logger.info("Task deleted: id=%d org=%s by user=%s", task_id, org_id, user_id)
    return {"ok": True}
