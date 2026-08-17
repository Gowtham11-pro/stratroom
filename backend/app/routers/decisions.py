import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from app.core.deps import require_role
from app.services.java_bridge import bridge

router = APIRouter(prefix="/decisions", tags=["decisions"])


class DecisionCreate(BaseModel):
    title: str
    description: str = ""
    status: str = "Pending"
    owner: Optional[str] = None
    priority: str = "Medium"
    due_date: Optional[str] = None


class DecisionUpdate(BaseModel):
    status: Optional[str] = None
    priority: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    owner: Optional[str] = None
    due_date: Optional[str] = None
    active: Optional[int] = None


@router.get("")
async def list_decisions(ctx: dict = Depends(require_role("member"))):
    data = await bridge.get(bridge.db_service, "/decisions")
    rows = data if isinstance(data, list) else data.get("decisions", data.get("list", []))
    return {"decisions": rows}


@router.post("", status_code=201)
async def create_decision(
    req: DecisionCreate,
    ctx: dict = Depends(require_role("member")),
):
    email = ctx.get("email")
    rows = await bridge._mysql(
        "SELECT emp_id, org_id FROM employee_details "
        "WHERE LOWER(email_address) = LOWER(%s) LIMIT 1",
        (email,),
    )
    if not rows:
        raise HTTPException(status_code=404, detail="User not found in employee directory.")
    mysql_org_id = rows[0]["org_id"]
    creator_emp_id = rows[0]["emp_id"]

    result = await bridge.post(
        bridge.db_service,
        "/decisions",
        json={
            "title": req.title,
            "description": req.description,
            "owner": req.owner or email,
            "priority": req.priority,
            "dueDate": req.due_date or "",
            "org_id": mysql_org_id,
            "owner_emp_id": creator_emp_id,
            "status": req.status,
            "priority_col": req.priority,
        },
    )
    return {"id": result.get("id"), "status": "created"}


@router.put("/{decision_id}")
async def update_decision(
    decision_id: int,
    req: DecisionUpdate,
    ctx: dict = Depends(require_role("member")),
):
    rows = await bridge._mysql(
        "SELECT id, decision_value, status, priority FROM decisions WHERE id = %s",
        (decision_id,),
    )
    if not rows:
        raise HTTPException(status_code=404, detail=f"Decision {decision_id} not found")

    row = rows[0]
    blob = bridge._parse_json_col(row, "decision_value")

    status = req.status if req.status is not None else (row.get("status") or "Pending")
    priority = req.priority if req.priority is not None else (row.get("priority") or "Medium")

    if req.title is not None:
        blob["title"] = req.title
    if req.description is not None:
        blob["description"] = req.description
    if req.owner is not None:
        blob["owner"] = req.owner
    if req.due_date is not None:
        blob["dueDate"] = req.due_date
    blob["priority"] = priority

    await bridge.put(
        bridge.db_service,
        f"/decisions/{decision_id}",
        json={"decision_value": blob, "status": status, "priority": priority},
    )
    return {"decision_id": decision_id, "status": "updated"}


@router.delete("/{decision_id}")
async def delete_decision(
    decision_id: int,
    ctx: dict = Depends(require_role("member")),
):
    rows = await bridge._mysql(
        "SELECT id FROM decisions WHERE id = %s",
        (decision_id,),
    )
    if not rows:
        raise HTTPException(status_code=404, detail=f"Decision {decision_id} not found")
    await bridge.delete(bridge.db_service, f"/decisions/{decision_id}")
    return {"decision_id": decision_id, "status": "deleted"}
