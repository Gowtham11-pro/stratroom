from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import require_role

router = APIRouter(prefix="/incidents", tags=["incidents"])


@router.get("")
async def list_incidents(
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("member")),
):
    org_id = ctx["org_id"]
    result = await db.execute(
        text(
            "SELECT id, code, title, severity, status, region, mttr_hours, sla_hours "
            "FROM incidents WHERE org_id = :oid ORDER BY created_at DESC"
        ),
        {"oid": org_id},
    )
    rows = result.mappings().all()
    return {"incidents": [dict(r) for r in rows]}
