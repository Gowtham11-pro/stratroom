from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.db import get_db
from app.core.deps import require_role
from app.core.config import settings

router = APIRouter(tags=["swot"])

VALID_QUADRANTS = {"strength", "weakness", "opportunity", "threat"}


class SwotItemCreate(BaseModel):
    quadrant: str
    content: str

    @field_validator("quadrant")
    @classmethod
    def validate_quadrant(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in VALID_QUADRANTS:
            raise ValueError(f"Invalid quadrant: {v}. Must be one of: {', '.join(sorted(VALID_QUADRANTS))}")
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


@router.get("/swot")
async def list_swot_items(
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("member")),
):
    org_id = ctx["org_id"]
    result = await db.execute(
        text("SELECT id, quadrant, content, sort_order FROM swot_items WHERE org_id = :oid ORDER BY CASE quadrant WHEN 'strength' THEN 1 WHEN 'weakness' THEN 2 WHEN 'opportunity' THEN 3 WHEN 'threat' THEN 4 END, sort_order"),
        {"oid": org_id},
    )
    rows = result.mappings().all()
    return {"items": [dict(r) for r in rows]}


@router.post("/swot")
async def add_swot_item(
    payload: SwotItemCreate,
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("manager")),
):
    org_id = ctx["org_id"]
    result = await db.execute(
        text("SELECT COALESCE(MAX(sort_order), 0) + 1 FROM swot_items WHERE org_id = :oid AND quadrant = :q"),
        {"oid": org_id, "q": payload.quadrant},
    )
    next_order = result.scalar()
    await db.execute(
        text("INSERT INTO swot_items (org_id, quadrant, content, sort_order) VALUES (:oid, :q, :c, :o)"),
        {"oid": org_id, "q": payload.quadrant, "c": payload.content, "o": next_order},
    )
    await db.commit()
    return {"ok": True}


@router.delete("/swot/{item_id}")
async def delete_swot_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("admin")),
):
    org_id = ctx["org_id"]
    result = await db.execute(
        text("DELETE FROM swot_items WHERE id = :id AND org_id = :oid"),
        {"id": item_id, "oid": org_id},
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="SWOT item not found")
    await db.commit()
    return {"ok": True}
