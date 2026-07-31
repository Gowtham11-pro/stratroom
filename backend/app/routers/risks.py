from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional

from app.core.deps import require_role
from app.services.java_bridge import bridge

router = APIRouter(prefix="/risks", tags=["risks"])


class RiskCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=500)
    owner: str = Field(default="")
    description: str = Field(default="")
    mitigation: str = Field(default="")
    inherent_likelihood: int = Field(default=1, ge=1, le=5)
    inherent_impact: int = Field(default=1, ge=1, le=5)
    residual_likelihood: int = Field(default=1, ge=1, le=5)
    residual_impact: int = Field(default=1, ge=1, le=5)


class RiskUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=500)
    owner: Optional[str] = None
    description: Optional[str] = None
    mitigation: Optional[str] = None
    inherent_likelihood: Optional[int] = Field(default=None, ge=1, le=5)
    inherent_impact: Optional[int] = Field(default=None, ge=1, le=5)
    residual_likelihood: Optional[int] = Field(default=None, ge=1, le=5)
    residual_impact: Optional[int] = Field(default=None, ge=1, le=5)


@router.get("")
async def list_risks(ctx: dict = Depends(require_role("member"))):
    emp_id = ctx["user_id"]
    is_admin = ctx["is_admin"]
    is_manager = ctx["is_manager"]

    if is_admin or is_manager:
        data = await bridge.get(bridge.db_service, "/riskListView")
    else:
        data = await bridge.get(bridge.db_service, f"/riskList/{emp_id}")

    rows = data if isinstance(data, list) else data.get("risk", data.get("risks", []))
    return {"risks": rows}


@router.post("", status_code=201)
async def create_risk(
    payload: RiskCreate,
    ctx: dict = Depends(require_role("manager")),
):
    body = {
        "riskName": payload.name,
        "owner": payload.owner or ctx["email"],
        "description": payload.description,
        "mitigation": payload.mitigation,
        "inherentLikelihood": payload.inherent_likelihood,
        "inherentImpact": payload.inherent_impact,
        "residualLikelihood": payload.residual_likelihood,
        "residualImpact": payload.residual_impact,
        "empId": ctx["user_id"],
        "orgId": ctx["org_id"],
    }
    result = await bridge.post(bridge.db_service, "/risk", json=body)
    return {"id": result.get("id"), "ok": True}


@router.put("/{risk_id}")
async def update_risk(
    risk_id: int,
    payload: RiskUpdate,
    ctx: dict = Depends(require_role("member")),
):
    existing = await bridge.get(bridge.db_service, f"/risk/{risk_id}")
    if not existing:
        raise HTTPException(status_code=404, detail="Risk not found")

    body = {"id": risk_id, "empId": ctx["user_id"], "orgId": ctx["org_id"]}
    if payload.name is not None:
        body["riskName"] = payload.name
    if payload.owner is not None:
        body["owner"] = payload.owner
    if payload.description is not None:
        body["description"] = payload.description
    if payload.mitigation is not None:
        body["mitigation"] = payload.mitigation
    if payload.inherent_likelihood is not None:
        body["inherentLikelihood"] = payload.inherent_likelihood
    if payload.inherent_impact is not None:
        body["inherentImpact"] = payload.inherent_impact
    if payload.residual_likelihood is not None:
        body["residualLikelihood"] = payload.residual_likelihood
    if payload.residual_impact is not None:
        body["residualImpact"] = payload.residual_impact

    await bridge.put(bridge.db_service, "/risk", json=body)
    return {"ok": True}


@router.delete("/{risk_id}")
async def delete_risk(
    risk_id: int,
    ctx: dict = Depends(require_role("admin")),
):
    existing = await bridge.get(bridge.db_service, f"/risk/{risk_id}")
    if not existing:
        raise HTTPException(status_code=404, detail="Risk not found")

    await bridge.delete(bridge.db_service, f"/risk/{risk_id}")
    return {"ok": True}
