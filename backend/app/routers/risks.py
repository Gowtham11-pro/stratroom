from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.core.db import get_db
from app.core.deps import require_role

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
async def list_risks(
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
                "SELECT id, name, owner, inherent_likelihood, inherent_impact, "
                "residual_likelihood, residual_impact, description, mitigation "
                "FROM risks WHERE org_id = :oid ORDER BY created_at DESC"
            ),
            {"oid": org_id},
        )
    else:
        result = await db.execute(
            text(
                "SELECT id, name, owner, inherent_likelihood, inherent_impact, "
                "residual_likelihood, residual_impact, description, mitigation "
                "FROM risks WHERE org_id = :oid AND owner = :owner ORDER BY created_at DESC"
            ),
            {"oid": org_id, "owner": ctx["email"]},
        )
    rows = result.mappings().all()
    return {"risks": [dict(r) for r in rows]}


@router.post("", status_code=201)
async def create_risk(
    payload: RiskCreate,
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("manager")),
):
    org_id = ctx["org_id"]
    result = await db.execute(
        text(
            "INSERT INTO risks (org_id, name, owner, description, mitigation, "
            "inherent_likelihood, inherent_impact, residual_likelihood, residual_impact) "
            "VALUES (:oid, :name, :owner, :desc, :mit, :il, :ii, :rl, :ri) RETURNING id"
        ),
        {
            "oid": org_id,
            "name": payload.name,
            "owner": payload.owner,
            "desc": payload.description,
            "mit": payload.mitigation,
            "il": payload.inherent_likelihood,
            "ii": payload.inherent_impact,
            "rl": payload.residual_likelihood,
            "ri": payload.residual_impact,
        },
    )
    row = result.mappings().first()
    await db.commit()
    return {"id": row["id"], "ok": True}


@router.put("/{risk_id}")
async def update_risk(
    risk_id: int,
    payload: RiskUpdate,
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("member")),
):
    org_id = ctx["org_id"]
    is_admin = ctx["is_admin"]

    ownership = await db.execute(
        text("SELECT id, owner FROM risks WHERE id = :rid AND org_id = :oid"),
        {"rid": risk_id, "oid": org_id},
    )
    risk = ownership.mappings().first()
    if not risk:
        raise HTTPException(status_code=404, detail="Risk not found")

    if not is_admin and risk["owner"] != ctx["email"]:
        raise HTTPException(status_code=403, detail="You can only update your own risks")

    updates = {}
    if payload.name is not None:
        updates["name"] = payload.name
    if payload.owner is not None:
        updates["owner"] = payload.owner
    if payload.description is not None:
        updates["description"] = payload.description
    if payload.mitigation is not None:
        updates["mitigation"] = payload.mitigation
    if payload.inherent_likelihood is not None:
        updates["inherent_likelihood"] = payload.inherent_likelihood
    if payload.inherent_impact is not None:
        updates["inherent_impact"] = payload.inherent_impact
    if payload.residual_likelihood is not None:
        updates["residual_likelihood"] = payload.residual_likelihood
    if payload.residual_impact is not None:
        updates["residual_impact"] = payload.residual_impact

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    set_clause = ", ".join(f"{k} = :{k}" for k in updates)
    updates["rid"] = risk_id
    updates["oid"] = org_id

    await db.execute(
        text(f"UPDATE risks SET {set_clause} WHERE id = :rid AND org_id = :oid"),
        updates,
    )
    await db.commit()
    return {"ok": True}


@router.delete("/{risk_id}")
async def delete_risk(
    risk_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("admin")),
):
    org_id = ctx["org_id"]

    ownership = await db.execute(
        text("SELECT id FROM risks WHERE id = :rid AND org_id = :oid"),
        {"rid": risk_id, "oid": org_id},
    )
    risk = ownership.mappings().first()
    if not risk:
        raise HTTPException(status_code=404, detail="Risk not found")

    await db.execute(
        text("DELETE FROM risks WHERE id = :rid AND org_id = :oid"),
        {"rid": risk_id, "oid": org_id},
    )
    await db.commit()
    return {"ok": True}
