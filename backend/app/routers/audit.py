import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from app.core.deps import require_role
from app.core.rbac import _record_owner_emp_id, enforce_record_access, filter_visible_rows
from app.services.java_bridge import bridge

logger = logging.getLogger("stratroom.audit")

router = APIRouter(tags=["audit"])

VALID_SEVERITIES = {"Critical", "High", "Medium", "Low"}
VALID_STATUSES = {"open", "in_progress", "resolved", "closed"}


class AuditFindingCreate(BaseModel):
    title: str
    severity: str = "Medium"
    owner: Optional[str] = None
    due_date: Optional[str] = None
    status: str = "open"
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


class AuditFindingUpdate(BaseModel):
    title: Optional[str] = None
    severity: Optional[str] = None
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


@router.get("/audit")
async def list_audit_findings(ctx: dict = Depends(require_role("member"))):
    data = await bridge.get(bridge.db_service, "/auditManagementList")
    rows = data if isinstance(data, list) else data.get("findings", data.get("auditManagement", data.get("list", [])))
    visible = await filter_visible_rows(ctx, rows)
    return {"findings": visible}


@router.get("/audit/{finding_id}")
async def get_audit_finding(
    finding_id: int,
    ctx: dict = Depends(require_role("member")),
):
    data = await bridge.get(bridge.db_service, f"/auditManagement/{finding_id}")
    if not data:
        raise HTTPException(status_code=404, detail="Finding not found")
    record = data[0] if isinstance(data, list) and data else (data if isinstance(data, dict) else {"finding": data})
    await enforce_record_access(ctx, _record_owner_emp_id(record))
    return record


@router.post("/audit", status_code=201)
async def create_audit_finding(
    payload: AuditFindingCreate,
    ctx: dict = Depends(require_role("manager")),
):
    body = {
        "title": payload.title,
        "severity": payload.severity,
        "owner": payload.owner or ctx["email"],
        "dueDate": payload.due_date,
        "status": payload.status,
        "assignedUserId": payload.assigned_user_id or ctx["user_id"],
        "empId": ctx["user_id"],
        "orgId": ctx["org_id"],
    }
    result = await bridge.post(bridge.db_service, "/auditManagement", json=body)
    finding_id = result.get("id")
    logger.info("Audit finding created: id=%s by user=%s", finding_id, ctx["user_id"])
    return {"id": finding_id, "ok": True}


@router.put("/audit/{finding_id}")
async def update_audit_finding(
    finding_id: int,
    payload: AuditFindingUpdate,
    ctx: dict = Depends(require_role("member")),
):
    existing = await bridge.get(bridge.db_service, f"/auditManagement/{finding_id}")
    if not existing:
        raise HTTPException(status_code=404, detail="Finding not found")
    record = existing[0] if isinstance(existing, list) and existing else (existing if isinstance(existing, dict) else {})
    await enforce_record_access(ctx, _record_owner_emp_id(record))

    body = {"id": finding_id}
    if payload.title is not None:
        body["title"] = payload.title
    if payload.severity is not None:
        body["severity"] = payload.severity
    if payload.owner is not None:
        body["owner"] = payload.owner
    if payload.due_date is not None:
        body["dueDate"] = payload.due_date
    if payload.status is not None:
        body["status"] = payload.status
    if payload.assigned_user_id is not None:
        body["assignedUserId"] = payload.assigned_user_id

    await bridge.put(bridge.db_service, "/auditManagement", json=body)
    logger.info("Audit finding updated: id=%d", finding_id)
    return {"ok": True}


@router.delete("/audit/{finding_id}")
async def delete_audit_finding(
    finding_id: int,
    ctx: dict = Depends(require_role("admin")),
):
    existing = await bridge.get(bridge.db_service, f"/auditManagement/{finding_id}")
    if not existing:
        raise HTTPException(status_code=404, detail="Finding not found")
    record = existing[0] if isinstance(existing, list) and existing else (existing if isinstance(existing, dict) else {})
    await enforce_record_access(ctx, _record_owner_emp_id(record))

    await bridge.delete(bridge.db_service, f"/auditManagement/{finding_id}")
    logger.info("Audit finding deleted: id=%d", finding_id)
    return {"ok": True}

