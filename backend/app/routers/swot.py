import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from app.core.deps import require_role
from app.core.config import settings
from app.services.java_bridge import bridge

logger = logging.getLogger("stratroom.swot")

router = APIRouter(tags=["swot"])

VALID_QUADRANTS = {"strength", "weakness", "opportunity", "threat"}
PG_TO_MYSQL_QUADRANT = {
    "strength": "Strengths",
    "weakness": "Weaknesses",
    "opportunity": "Oppurtunities",
    "threat": "Threats",
}


class SwotItemCreate(BaseModel):
    quadrant: str
    content: str

    @field_validator("quadrant")
    @classmethod
    def validate_quadrant(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in VALID_QUADRANTS:
            raise ValueError(f"Invalid quadrant: {v}")
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
    ctx: dict = Depends(require_role("member")),
):
    org_id = ctx["org_id"]
    try:
        data = await bridge.get(bridge.db_service, "/swotList")
        rows = data if isinstance(data, list) else data.get("items", data.get("list", []))
        quadrant_order = {"strength": 1, "weakness": 2, "opportunity": 3, "threat": 4}
        items = []
        for r in rows:
            q = (r.get("quadrant") or "").lower()
            items.append({
                "id": r.get("id"),
                "quadrant": q,
                "content": r.get("content") or "",
                "sort_order": quadrant_order.get(q, 5),
            })
        items.sort(key=lambda x: (quadrant_order.get(x["quadrant"], 5), x["sort_order"]))
    except Exception as exc:
        logger.warning("Failed to query SWOT via bridge: %s", exc)
        items = []
    return {"items": items}


@router.post("/swot")
async def add_swot_item(
    payload: SwotItemCreate,
    ctx: dict = Depends(require_role("manager")),
):
    emp_id = ctx.get("user_id")
    mysql_quadrant = PG_TO_MYSQL_QUADRANT.get(payload.quadrant, payload.quadrant.capitalize())
    await bridge.post(bridge.db_service, "/swotList", json={
        "name": payload.content,
        "active": 1,
        "owner": emp_id,
        "page_id": 0,
        "flag_type": mysql_quadrant,
    })
    return {"ok": True}


@router.delete("/swot/{item_id}")
async def delete_swot_item(
    item_id: int,
    ctx: dict = Depends(require_role("admin")),
):
    try:
        await bridge.delete(bridge.db_service, f"/swotList/{item_id}")
    except Exception:
        raise HTTPException(status_code=404, detail="SWOT item not found")
    return {"ok": True}
