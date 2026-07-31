import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from app.core.deps import require_role
from app.services.java_bridge import bridge

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
            raise ValueError(f"Invalid status: {v}")
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
        return v

    @field_validator("kpi_name")
    @classmethod
    def validate_kpi_name(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("KPI name cannot be empty")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {v}")
        return v


@router.get("/scorecards")
async def list_scorecards(
    ctx: dict = Depends(require_role("member")),
):
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]
    is_admin = ctx["is_admin"]
    is_manager = ctx["is_manager"]

    if is_admin or is_manager:
        rows = await bridge._mysql(
            "SELECT id, perspective, kpi_name, target, actual, owner, status, assigned_user_id "
            "FROM scorecard_kpis WHERE org_id = %s ORDER BY perspective, id",
            (org_id,),
        )
    else:
        rows = await bridge._mysql(
            "SELECT id, perspective, kpi_name, target, actual, owner, status, assigned_user_id "
            "FROM scorecard_kpis WHERE org_id = %s AND assigned_user_id = %s ORDER BY perspective, id",
            (org_id, user_id),
        )

    for r in rows:
        t = r.get("target")
        a = r.get("actual")
        r["target"] = float(t) if t is not None else None
        r["actual"] = float(a) if a is not None else None
    return {"scorecards": rows}


@router.get("/scorecards/summary")
async def scorecard_summary(
    ctx: dict = Depends(require_role("member")),
):
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]
    is_admin = ctx["is_admin"]
    is_manager = ctx["is_manager"]

    if is_admin or is_manager:
        rows = await bridge._mysql(
            "SELECT perspective, "
            "ROUND(AVG(actual)) as avg_score, "
            "COUNT(*) as kpi_count, "
            "SUM(CASE WHEN status = 'on-track' THEN 1 ELSE 0 END) as on_track, "
            "SUM(CASE WHEN status = 'at-risk' THEN 1 ELSE 0 END) as at_risk, "
            "SUM(CASE WHEN status = 'critical' THEN 1 ELSE 0 END) as critical "
            "FROM scorecard_kpis WHERE org_id = %s "
            "GROUP BY perspective ORDER BY MIN(id)",
            (org_id,),
        )
    else:
        rows = await bridge._mysql(
            "SELECT perspective, "
            "ROUND(AVG(actual)) as avg_score, "
            "COUNT(*) as kpi_count, "
            "SUM(CASE WHEN status = 'on-track' THEN 1 ELSE 0 END) as on_track, "
            "SUM(CASE WHEN status = 'at-risk' THEN 1 ELSE 0 END) as at_risk, "
            "SUM(CASE WHEN status = 'critical' THEN 1 ELSE 0 END) as critical "
            "FROM scorecard_kpis WHERE org_id = %s AND assigned_user_id = %s "
            "GROUP BY perspective ORDER BY MIN(id)",
            (org_id, user_id),
        )

    for r in rows:
        r["avg_score"] = int(r["avg_score"]) if r["avg_score"] is not None else 0
        r["kpi_count"] = int(r["kpi_count"])
        r["on_track"] = int(r["on_track"])
        r["at_risk"] = int(r["at_risk"])
        r["critical"] = int(r["critical"])
    return {"perspectives": rows}


@router.get("/scorecards/{scorecard_id}")
async def get_scorecard(
    scorecard_id: int,
    ctx: dict = Depends(require_role("member")),
):
    data = await bridge.get(bridge.db_service, f"/scorecard/{scorecard_id}")
    if not data:
        raise HTTPException(status_code=404, detail="Scorecard not found")
    return data if isinstance(data, dict) else {"scorecard": data}


@router.post("/scorecards", status_code=201)
async def create_scorecard(
    payload: ScorecardCreate,
    ctx: dict = Depends(require_role("manager")),
):
    body = {
        "perspective": payload.perspective,
        "kpiName": payload.kpi_name,
        "target": payload.target,
        "actual": payload.actual,
        "owner": payload.owner or ctx["email"],
        "status": payload.status,
        "assignedUserId": payload.assigned_user_id or ctx["user_id"],
        "empId": ctx["user_id"],
        "orgId": ctx["org_id"],
    }
    result = await bridge.post(bridge.db_service, "/scorecard", json=body)
    scorecard_id = result.get("id")
    logger.info("Scorecard created: id=%s org=%s by user=%s", scorecard_id, ctx["org_id"], ctx["user_id"])
    return {"id": scorecard_id, "ok": True}


@router.put("/scorecards/{scorecard_id}")
async def update_scorecard(
    scorecard_id: int,
    payload: ScorecardUpdate,
    ctx: dict = Depends(require_role("member")),
):
    data = await bridge.get(bridge.db_service, f"/scorecard/{scorecard_id}")
    if not data:
        raise HTTPException(status_code=404, detail="Scorecard not found")

    body = {"id": scorecard_id}
    if payload.perspective is not None:
        body["perspective"] = payload.perspective
    if payload.kpi_name is not None:
        body["kpiName"] = payload.kpi_name
    if payload.target is not None:
        body["target"] = payload.target
    if payload.actual is not None:
        body["actual"] = payload.actual
    if payload.owner is not None:
        body["owner"] = payload.owner
    if payload.status is not None:
        body["status"] = payload.status
    if payload.assigned_user_id is not None:
        body["assignedUserId"] = payload.assigned_user_id

    await bridge.put(bridge.db_service, "/scorecardDetails", json=body)
    logger.info("Scorecard updated: id=%d org=%s", scorecard_id, ctx["org_id"])
    return {"ok": True}


@router.delete("/scorecards/{scorecard_id}")
async def delete_scorecard(
    scorecard_id: int,
    ctx: dict = Depends(require_role("admin")),
):
    data = await bridge.get(bridge.db_service, f"/scorecard/{scorecard_id}")
    if not data:
        raise HTTPException(status_code=404, detail="Scorecard not found")

    await bridge.delete(bridge.db_service, f"/scorecard/{scorecard_id}")
    logger.info("Scorecard deleted: id=%d org=%s", scorecard_id, ctx["org_id"])
    return {"ok": True}
