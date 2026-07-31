import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from app.core.deps import require_role
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


@router.get("/tasks")
async def list_tasks(ctx: dict = Depends(require_role("member"))):
    emp_id = ctx["user_id"]
    is_admin = ctx["is_admin"]
    is_manager = ctx["is_manager"]

    if is_admin or is_manager:
        data = await bridge.get(bridge.db_service, f"/retrieveTaskList/{emp_id}")
    else:
        data = await bridge.get(bridge.db_service, f"/retrieveTaskList/{emp_id}")

    rows = data if isinstance(data, list) else data.get("tasks", data.get("list", []))
    return {"tasks": rows}


@router.get("/tasks/{task_id}")
async def get_task(
    task_id: int,
    ctx: dict = Depends(require_role("member")),
):
    data = await bridge.get(bridge.db_service, f"/task/{task_id}")
    if not data:
        raise HTTPException(status_code=404, detail="Task not found")
    return data if isinstance(data, dict) else {"task": data}


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

    await bridge.delete(bridge.db_service, f"/task/{task_id}")
    logger.info("Task deleted: id=%d", task_id)
    return {"ok": True}
