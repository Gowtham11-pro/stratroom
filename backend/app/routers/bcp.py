from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.db import get_db
from app.core.deps import require_role

router = APIRouter(tags=["bcp"])


@router.get("/bcp")
async def list_bcp_processes(
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("member")),
):
    org_id = ctx["org_id"]
    result = await db.execute(
        text("SELECT id, parent_id, name, owner, rto, rpo, mtd, impact, status, category FROM bcp_processes WHERE org_id = :oid ORDER BY sort_order"),
        {"oid": org_id},
    )
    rows = [dict(r) for r in result.mappings().all()]
    by_id = {r['id']: r for r in rows}
    for r in rows:
        r['children'] = []
    roots = []
    for r in rows:
        pid = r['parent_id']
        if pid and pid in by_id:
            by_id[pid]['children'].append(r)
        else:
            roots.append(r)
    return {"processes": roots}


@router.get("/bcp/flat")
async def list_bcp_flat(
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("member")),
):
    org_id = ctx["org_id"]
    result = await db.execute(
        text("SELECT id, parent_id, name, owner, rto, rpo, mtd, impact, status, category FROM bcp_processes WHERE org_id = :oid ORDER BY sort_order"),
        {"oid": org_id},
    )
    return {"processes": [dict(r) for r in result.mappings().all()]}
