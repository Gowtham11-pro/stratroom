import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from app.core.deps import require_role
from app.core.config import settings
from app.core.rbac import _record_owner_emp_id, enforce_record_access, filter_visible_rows
from app.services.java_bridge import bridge

logger = logging.getLogger("stratroom.pestel_projects")

router = APIRouter(tags=["pestel", "projects"])

VALID_PESTEL_CATEGORIES = {"political", "economic", "social", "technology", "environmental", "legal"}
VALID_IMPACT_LEVELS = {"high", "medium", "low"}
VALID_PROJECT_STATUSES = {"on_track", "at_risk", "ahead", "completed", "on-hold"}
PG_TO_MYSQL_CATEGORY = {
    "political": "Political",
    "economic": "Economical",
    "social": "Social",
    "technology": "Technological",
    "environmental": "Environmental",
    "legal": "Legal",
}
PG_IMPACT_TO_MYSQL_FLAG = {
    "high": "danger",
    "medium": "warning",
    "low": "success",
}
PG_STATUS_TO_MYSQL_STATUS = {
    "on_track": "In Progress",
    "at_risk": "Delayed",
    "ahead": "In Progress",
    "completed": "Completed",
    "on-hold": "On Hold",
}


class PestelItemCreate(BaseModel):
    category: str
    impact: str
    content: str

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in VALID_PESTEL_CATEGORIES:
            raise ValueError(f"Invalid category: {v}")
        return v

    @field_validator("impact")
    @classmethod
    def validate_impact(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in VALID_IMPACT_LEVELS:
            raise ValueError(f"Invalid impact: {v}")
        return v

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Content cannot be empty")
        if len(v) > settings.MAX_STRING_LENGTH:
            raise ValueError(f"Content exceeds maximum length of {settings.MAX_STRING_LENGTH}")
        return v


class ProjectCreate(BaseModel):
    name: str
    owner: str
    budget: str = ""
    progress: int = 0
    due_date: str = ""
    status: str = "on_track"

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Project name cannot be empty")
        if len(v) > 500:
            raise ValueError("Project name too long")
        return v

    @field_validator("owner")
    @classmethod
    def validate_owner(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Owner cannot be empty")
        if len(v) > 200:
            raise ValueError("Owner name too long")
        return v

    @field_validator("progress")
    @classmethod
    def validate_progress(cls, v: int) -> int:
        if v < 0 or v > 100:
            raise ValueError("Progress must be between 0 and 100")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        v = v.strip()
        if v not in VALID_PROJECT_STATUSES:
            raise ValueError(f"Invalid status: {v}")
        return v


@router.get("/pestel")
async def list_pestel_items(
    ctx: dict = Depends(require_role("member")),
):
    org_id = ctx["org_id"]
    try:
        data = await bridge.get(bridge.db_service, "/pestelList")
        rows = data if isinstance(data, list) else data.get("items", data.get("list", []))
        rows = await filter_visible_rows(ctx, rows)
        category_order = {"political": 1, "economic": 2, "social": 3, "technology": 4, "environmental": 5, "legal": 6}
        items = []
        for r in rows:
            c = (r.get("category") or "").lower()
            items.append({
                "id": r.get("id"),
                "category": c,
                "impact": (r.get("impact") or "medium").lower(),
                "content": r.get("content") or "",
                "sort_order": category_order.get(c, 7),
            })
        items.sort(key=lambda x: (category_order.get(x["category"], 7), x["sort_order"]))
    except Exception as exc:
        logger.warning("Failed to query PESTEL via bridge: %s", exc)
        items = []
    return {"items": items}


@router.post("/pestel")
async def add_pestel_item(
    payload: PestelItemCreate,
    ctx: dict = Depends(require_role("manager")),
):
    emp_id = ctx.get("user_id")
    mysql_category = PG_TO_MYSQL_CATEGORY.get(payload.category, payload.category.capitalize())
    mysql_impact = PG_IMPACT_TO_MYSQL_FLAG.get(payload.impact, "warning")
    await bridge.post(bridge.db_service, "/pestelList", json={
        "name": payload.content,
        "status_flag": mysql_impact,
        "active": 1,
        "owner": emp_id,
        "page_id": 0,
        "flagType": mysql_category,
    })
    return {"ok": True}


@router.delete("/pestel/{item_id}")
async def delete_pestel_item(
    item_id: int,
    ctx: dict = Depends(require_role("admin")),
):
    try:
        await bridge.delete(bridge.db_service, f"/pestelList/{item_id}")
    except Exception:
        raise HTTPException(status_code=404, detail="PESTEL item not found")
    return {"ok": True}


@router.get("/projects")
async def list_projects(
    ctx: dict = Depends(require_role("member")),
):
    org_id = ctx["org_id"]
    try:
        data = await bridge.get(bridge.db_service, "/projectsList")
        rows = data if isinstance(data, list) else data.get("projects", data.get("list", []))
        rows = await filter_visible_rows(ctx, rows)
        projects = []
        for i, r in enumerate(rows):
            projects.append({
                "id": r.get("id"),
                "name": r.get("name") or "",
                "owner": r.get("owner") or "",
                "budget": str(r.get("budget") or 0),
                "progress": r.get("progress", 0),
                "due_date": r.get("due_date") or "",
                "status": r.get("status") or "on_track",
                "sort_order": i + 1,
            })
    except Exception as exc:
        logger.warning("Failed to query projects via bridge: %s", exc)
        projects = []
    return {"projects": projects}


@router.post("/projects")
async def add_project(
    payload: ProjectCreate,
    ctx: dict = Depends(require_role("manager")),
):
    emp_id = ctx.get("user_id")
    mysql_status = PG_STATUS_TO_MYSQL_STATUS.get(payload.status, "Not Started")
    await bridge.post(bridge.db_service, "/projectsList", json={
        "projectName": payload.name,
        "projectOwner": payload.owner,
        "budget": str(payload.budget),
        "status": mysql_status,
        "enddate": payload.due_date,
        "fromdate": payload.due_date,
        "active": 1,
        "owner": emp_id,
        "page_id": 0,
        "start_date": payload.due_date if payload.due_date else None,
        "end_date": payload.due_date if payload.due_date else None,
        "department_id": 0,
    })
    return {"ok": True}


@router.put("/projects/{project_id}")
async def update_project(
    project_id: int,
    payload: ProjectCreate,
    ctx: dict = Depends(require_role("manager")),
):
    existing = await bridge.get(bridge.db_service, f"/projectsList/{project_id}")
    if existing:
        rec = existing[0] if isinstance(existing, list) else existing
        await enforce_record_access(ctx, _record_owner_emp_id(rec))

    mysql_status = PG_STATUS_TO_MYSQL_STATUS.get(payload.status, "Not Started")
    await bridge.put(bridge.db_service, f"/projectsList/{project_id}", json={
        "projectName": payload.name,
        "projectOwner": payload.owner,
        "budget": str(payload.budget),
        "status": mysql_status,
        "enddate": payload.due_date,
        "fromdate": payload.due_date,
    })
    return {"ok": True}


@router.delete("/projects/{project_id}")
async def delete_project(
    project_id: int,
    ctx: dict = Depends(require_role("admin")),
):
    existing = await bridge.get(bridge.db_service, f"/projectsList/{project_id}")
    if not existing:
        raise HTTPException(status_code=404, detail="Project not found")
    rec = existing[0] if isinstance(existing, list) else existing
    await enforce_record_access(ctx, _record_owner_emp_id(rec))

    try:
        await bridge.delete(bridge.db_service, f"/projectsList/{project_id}")
    except Exception:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"ok": True}

