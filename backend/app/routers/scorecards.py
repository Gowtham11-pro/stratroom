import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import require_role

logger = logging.getLogger("stratroom.scorecards")

router = APIRouter(tags=["scorecards"])

VALID_STATUSES = {"on-track", "at-risk", "critical"}


class ScorecardCreate(BaseModel):
    perspective: str
    kpi_name: str
    target: Optional[float] = None
    actual: Optional[float] = None
    owner: Optional[str] = None
    status: str = "on-track"
    assigned_user_id: Optional[int] = None

    @field_validator("perspective")
    @classmethod
    def validate_perspective(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Perspective is required")
        if len(v) > 200:
            raise ValueError("Perspective exceeds maximum length of 200")
        return v

    @field_validator("kpi_name")
    @classmethod
    def validate_kpi_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("KPI name is required")
        if len(v) > 500:
            raise ValueError("KPI name exceeds maximum length of 500")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {v}. Must be one of: {', '.join(sorted(VALID_STATUSES))}")
        return v


class ScorecardUpdate(BaseModel):
    perspective: Optional[str] = None
    kpi_name: Optional[str] = None
    target: Optional[float] = None
    actual: Optional[float] = None
    owner: Optional[str] = None
    status: Optional[str] = None
    assigned_user_id: Optional[int] = None

    @field_validator("perspective")
    @classmethod
    def validate_perspective(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("Perspective cannot be empty")
            if len(v) > 200:
                raise ValueError("Perspective exceeds maximum length of 200")
        return v

    @field_validator("kpi_name")
    @classmethod
    def validate_kpi_name(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("KPI name cannot be empty")
            if len(v) > 500:
                raise ValueError("KPI name exceeds maximum length of 500")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {v}. Must be one of: {', '.join(sorted(VALID_STATUSES))}")
        return v


@router.get("/scorecards")
async def list_scorecards(
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
                "SELECT id, perspective, kpi_name, target, actual, owner, status, assigned_user_id "
                "FROM scorecards WHERE org_id = :oid "
                "ORDER BY id"
            ),
            {"oid": org_id},
        )
    else:
        result = await db.execute(
            text(
                "SELECT id, perspective, kpi_name, target, actual, owner, status, assigned_user_id "
                "FROM scorecards WHERE org_id = :oid AND assigned_user_id = :uid "
                "ORDER BY id"
            ),
            {"oid": org_id, "uid": user_id},
        )
    rows = result.mappings().all()
    return {"scorecards": [dict(r) for r in rows]}


@router.get("/scorecards/summary")
async def scorecard_summary(
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
                "SELECT perspective, "
                "ROUND(AVG(actual)) as avg_score, "
                "COUNT(*) as kpi_count, "
                "SUM(CASE WHEN status = 'on-track' THEN 1 ELSE 0 END) as on_track, "
                "SUM(CASE WHEN status = 'at-risk' THEN 1 ELSE 0 END) as at_risk, "
                "SUM(CASE WHEN status = 'critical' THEN 1 ELSE 0 END) as critical "
                "FROM scorecards WHERE org_id = :oid "
                "GROUP BY perspective ORDER BY MIN(id)"
            ),
            {"oid": org_id},
        )
    else:
        result = await db.execute(
            text(
                "SELECT perspective, "
                "ROUND(AVG(actual)) as avg_score, "
                "COUNT(*) as kpi_count, "
                "SUM(CASE WHEN status = 'on-track' THEN 1 ELSE 0 END) as on_track, "
                "SUM(CASE WHEN status = 'at-risk' THEN 1 ELSE 0 END) as at_risk, "
                "SUM(CASE WHEN status = 'critical' THEN 1 ELSE 0 END) as critical "
                "FROM scorecards WHERE org_id = :oid AND assigned_user_id = :uid "
                "GROUP BY perspective ORDER BY MIN(id)"
            ),
            {"oid": org_id, "uid": user_id},
        )
    rows = result.mappings().all()
    return {"perspectives": [dict(r) for r in rows]}


@router.get("/scorecards/{scorecard_id}")
async def get_scorecard(
    scorecard_id: int,
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
                "SELECT id, perspective, kpi_name, target, actual, owner, status, assigned_user_id "
                "FROM scorecards WHERE id = :sid AND org_id = :oid"
            ),
            {"sid": scorecard_id, "oid": org_id},
        )
    else:
        result = await db.execute(
            text(
                "SELECT id, perspective, kpi_name, target, actual, owner, status, assigned_user_id "
                "FROM scorecards WHERE id = :sid AND org_id = :oid AND assigned_user_id = :uid"
            ),
            {"sid": scorecard_id, "oid": org_id, "uid": user_id},
        )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Scorecard not found or not assigned to you")
    return dict(row)


@router.post("/scorecards", status_code=201)
async def create_scorecard(
    payload: ScorecardCreate,
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
            "INSERT INTO scorecards (org_id, perspective, kpi_name, target, actual, owner, status, assigned_user_id) "
            "VALUES (:oid, :perspective, :kpi_name, :target, :actual, :owner, :status, :assigned_user_id) "
            "RETURNING id"
        ),
        {
            "oid": org_id,
            "perspective": payload.perspective,
            "kpi_name": payload.kpi_name,
            "target": payload.target,
            "actual": payload.actual,
            "owner": payload.owner,
            "status": payload.status,
            "assigned_user_id": payload.assigned_user_id,
        },
    )
    scorecard_id = result.scalar()
    await db.commit()

    logger.info("Scorecard created: id=%d org=%s by user=%s", scorecard_id, org_id, ctx["user_id"])
    return {"id": scorecard_id, "ok": True}


@router.put("/scorecards/{scorecard_id}")
async def update_scorecard(
    scorecard_id: int,
    payload: ScorecardUpdate,
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
                "SELECT id, assigned_user_id FROM scorecards WHERE id = :sid AND org_id = :oid"
            ),
            {"sid": scorecard_id, "oid": org_id},
        )
    else:
        result = await db.execute(
            text(
                "SELECT id, assigned_user_id FROM scorecards WHERE id = :sid AND org_id = :oid AND assigned_user_id = :uid"
            ),
            {"sid": scorecard_id, "oid": org_id, "uid": user_id},
        )
    existing = result.mappings().first()
    if not existing:
        raise HTTPException(status_code=404, detail="This scorecard is not yours.")

    updates = {}
    if payload.perspective is not None:
        updates["perspective"] = payload.perspective
    if payload.kpi_name is not None:
        updates["kpi_name"] = payload.kpi_name
    if payload.target is not None:
        updates["target"] = payload.target
    if payload.actual is not None:
        updates["actual"] = payload.actual
    if payload.owner is not None:
        updates["owner"] = payload.owner
    if payload.status is not None:
        updates["status"] = payload.status
    if payload.assigned_user_id is not None:
        if not is_admin:
            raise HTTPException(status_code=403, detail="Only admins can reassign scorecards")
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
    updates["sid"] = scorecard_id
    updates["oid"] = org_id

    await db.execute(
        text(f"UPDATE scorecards SET {set_clause} WHERE id = :sid AND org_id = :oid"),
        updates,
    )
    await db.commit()

    logger.info("Scorecard updated: id=%d org=%s by user=%s", scorecard_id, org_id, user_id)
    return {"ok": True}


@router.delete("/scorecards/{scorecard_id}")
async def delete_scorecard(
    scorecard_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("admin")),
):
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    result = await db.execute(
        text("SELECT id FROM scorecards WHERE id = :sid AND org_id = :oid"),
        {"sid": scorecard_id, "oid": org_id},
    )
    if not result.first():
        raise HTTPException(status_code=404, detail="Scorecard not found")

    await db.execute(
        text("DELETE FROM scorecards WHERE id = :sid AND org_id = :oid"),
        {"sid": scorecard_id, "oid": org_id},
    )
    await db.commit()

    logger.info("Scorecard deleted: id=%d org=%s by user=%s", scorecard_id, org_id, user_id)
    return {"ok": True}
