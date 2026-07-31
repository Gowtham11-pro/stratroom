import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from app.core.deps import require_role
from app.services.java_bridge import bridge

logger = logging.getLogger("stratroom.complaints")

router = APIRouter(tags=["complaints"])

VALID_SEVERITIES = {"Critical", "High", "Medium", "Low"}
VALID_STATUSES = {"open", "in_progress", "resolved", "closed"}
VALID_CATEGORIES = {"general", "hr", "finance", "operations", "safety", "ethics", "it", "other"}


class ComplaintCreate(BaseModel):
    title: str
    description: Optional[str] = None
    category: str = "general"
    severity: str = "Medium"
    status: str = "open"
    assigned_user_id: Optional[int] = None
    submitted_by: Optional[str] = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Title is required")
        if len(v) > 500:
            raise ValueError("Title exceeds maximum length of 500")
        return v

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        if v not in VALID_CATEGORIES:
            raise ValueError(f"Invalid category: {v}")
        return v

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, v: str) -> str:
        if v not in VALID_SEVERITIES:
            raise ValueError(f"Invalid severity: {v}")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {v}")
        return v


class ComplaintUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    severity: Optional[str] = None
    status: Optional[str] = None
    assigned_user_id: Optional[int] = None
    submitted_by: Optional[str] = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("Title cannot be empty")
        return v

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_CATEGORIES:
            raise ValueError(f"Invalid category: {v}")
        return v

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_SEVERITIES:
            raise ValueError(f"Invalid severity: {v}")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {v}")
        return v


@router.get("/complaints")
async def list_complaints(ctx: dict = Depends(require_role("member"))):
    result = await bridge.get(
        bridge.db_service, "/complaints",
        params={
            "org_id": ctx["org_id"],
            "user_id": ctx["user_id"],
            "is_admin": ctx["is_admin"],
            "is_manager": ctx["is_manager"],
        },
    )
    return {"complaints": result if result else []}


@router.get("/complaints/{complaint_id}")
async def get_complaint(
    complaint_id: int,
    ctx: dict = Depends(require_role("member")),
):
    result = await bridge.get(
        bridge.db_service, f"/complaints/{complaint_id}",
        params={"org_id": ctx["org_id"]},
    )
    if not result:
        raise HTTPException(status_code=404, detail="Complaint not found")
    return result[0]


@router.post("/complaints", status_code=201)
async def create_complaint(
    payload: ComplaintCreate,
    ctx: dict = Depends(require_role("manager")),
):
    record = {
        "org_id": ctx["org_id"],
        "title": payload.title,
        "description": payload.description,
        "category": payload.category,
        "severity": payload.severity,
        "status": payload.status,
        "assigned_user_id": payload.assigned_user_id,
        "submitted_by": payload.submitted_by,
    }
    await bridge.post(bridge.db_service, "/complaints", json=record)
    logger.info("Complaint created org=%s by user=%s", ctx["org_id"], ctx["user_id"])
    return {"ok": True}


@router.put("/complaints/{complaint_id}")
async def update_complaint(
    complaint_id: int,
    payload: ComplaintUpdate,
    ctx: dict = Depends(require_role("member")),
):
    user_id = ctx["user_id"]
    org_id = ctx["org_id"]
    is_admin = ctx["is_admin"]
    is_manager = ctx["is_manager"]

    existing = await bridge.get(
        bridge.db_service, f"/complaints/{complaint_id}",
        params={"org_id": org_id},
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Complaint not found")
    if not is_admin and not is_manager:
        if existing[0].get("assigned_user_id") != user_id:
            raise HTTPException(status_code=403, detail="You can only edit your own complaints")

    current = existing[0]
    record = {
        "title": payload.title if payload.title is not None else current.get("title"),
        "description": payload.description if payload.description is not None else current.get("description"),
        "category": payload.category if payload.category is not None else current.get("category"),
        "severity": payload.severity if payload.severity is not None else current.get("severity"),
        "status": payload.status if payload.status is not None else current.get("status"),
        "assigned_user_id": payload.assigned_user_id if payload.assigned_user_id is not None else current.get("assigned_user_id"),
        "submitted_by": payload.submitted_by if payload.submitted_by is not None else current.get("submitted_by"),
    }
    await bridge.put(bridge.db_service, f"/complaints/{complaint_id}", json=record)
    logger.info("Complaint updated: id=%d org=%s by user=%s", complaint_id, org_id, user_id)
    return {"ok": True}


@router.delete("/complaints/{complaint_id}")
async def delete_complaint(
    complaint_id: int,
    ctx: dict = Depends(require_role("admin")),
):
    org_id = ctx["org_id"]
    existing = await bridge.get(
        bridge.db_service, f"/complaints/{complaint_id}",
        params={"org_id": org_id},
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Complaint not found")
    await bridge.delete(bridge.db_service, f"/complaints/{complaint_id}")
    logger.info("Complaint deleted: id=%d org=%s", complaint_id, org_id)
    return {"ok": True}
