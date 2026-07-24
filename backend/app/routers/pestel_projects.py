from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.db import get_db
from app.core.deps import require_role
from app.core.config import settings

router = APIRouter(tags=["pestel", "projects"])

VALID_PESTEL_CATEGORIES = {"political", "economic", "social", "technology", "environmental", "legal"}
VALID_IMPACT_LEVELS = {"high", "medium", "low"}
VALID_PROJECT_STATUSES = {"on_track", "at_risk", "ahead", "completed", "on-hold"}


class PestelItemCreate(BaseModel):
    category: str
    impact: str
    content: str

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in VALID_PESTEL_CATEGORIES:
            raise ValueError(f"Invalid category: {v}. Must be one of: {', '.join(sorted(VALID_PESTEL_CATEGORIES))}")
        return v

    @field_validator("impact")
    @classmethod
    def validate_impact(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in VALID_IMPACT_LEVELS:
            raise ValueError(f"Invalid impact: {v}. Must be one of: {', '.join(sorted(VALID_IMPACT_LEVELS))}")
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
            raise ValueError(f"Invalid status: {v}. Must be one of: {', '.join(sorted(VALID_PROJECT_STATUSES))}")
        return v


@router.get("/pestel")
async def list_pestel_items(
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("member")),
):
    org_id = ctx["org_id"]
    result = await db.execute(
        text("SELECT id, category, impact, content, sort_order FROM pestel_items WHERE org_id = :oid ORDER BY CASE category WHEN 'political' THEN 1 WHEN 'economic' THEN 2 WHEN 'social' THEN 3 WHEN 'technology' THEN 4 WHEN 'environmental' THEN 5 WHEN 'legal' THEN 6 END, sort_order"),
        {"oid": org_id},
    )
    rows = result.mappings().all()
    return {"items": [dict(r) for r in rows]}


@router.post("/pestel")
async def add_pestel_item(
    payload: PestelItemCreate,
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("manager")),
):
    org_id = ctx["org_id"]
    result = await db.execute(
        text("SELECT COALESCE(MAX(sort_order), 0) + 1 FROM pestel_items WHERE org_id = :oid AND category = :c"),
        {"oid": org_id, "c": payload.category},
    )
    next_order = result.scalar()
    await db.execute(
        text("INSERT INTO pestel_items (org_id, category, impact, content, sort_order) VALUES (:oid, :c, :i, :co, :o)"),
        {"oid": org_id, "c": payload.category, "i": payload.impact, "co": payload.content, "o": next_order},
    )
    await db.commit()
    return {"ok": True}


@router.delete("/pestel/{item_id}")
async def delete_pestel_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("admin")),
):
    org_id = ctx["org_id"]
    result = await db.execute(
        text("DELETE FROM pestel_items WHERE id = :id AND org_id = :oid"),
        {"id": item_id, "oid": org_id},
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="PESTEL item not found")
    await db.commit()
    return {"ok": True}


@router.get("/projects")
async def list_projects(
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("member")),
):
    org_id = ctx["org_id"]
    result = await db.execute(
        text("SELECT id, name, owner, budget, progress, due_date, status, sort_order FROM projects WHERE org_id = :oid ORDER BY sort_order"),
        {"oid": org_id},
    )
    rows = result.mappings().all()
    return {"projects": [dict(r) for r in rows]}


@router.post("/projects")
async def add_project(
    payload: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("manager")),
):
    org_id = ctx["org_id"]
    result = await db.execute(
        text("SELECT COALESCE(MAX(sort_order), 0) + 1 FROM projects WHERE org_id = :oid"),
        {"oid": org_id},
    )
    next_order = result.scalar()
    await db.execute(
        text("INSERT INTO projects (org_id, name, owner, budget, progress, due_date, status, sort_order) VALUES (:oid, :n, :o, :b, :p, :d, :s, :so)"),
        {"oid": org_id, "n": payload.name, "o": payload.owner, "b": payload.budget, "p": payload.progress, "d": payload.due_date, "s": payload.status, "so": next_order},
    )
    await db.commit()
    return {"ok": True}


@router.put("/projects/{project_id}")
async def update_project(
    project_id: int,
    payload: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("manager")),
):
    org_id = ctx["org_id"]
    await db.execute(
        text("UPDATE projects SET name=:n, owner=:o, budget=:b, progress=:p, due_date=:d, status=:s WHERE id=:id AND org_id=:oid"),
        {"n": payload.name, "o": payload.owner, "b": payload.budget, "p": payload.progress, "d": payload.due_date, "s": payload.status, "id": project_id, "oid": org_id},
    )
    await db.commit()
    return {"ok": True}


@router.delete("/projects/{project_id}")
async def delete_project(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("admin")),
):
    org_id = ctx["org_id"]
    result = await db.execute(
        text("DELETE FROM projects WHERE id = :id AND org_id = :oid"),
        {"id": project_id, "oid": org_id},
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Project not found")
    await db.commit()
    return {"ok": True}
