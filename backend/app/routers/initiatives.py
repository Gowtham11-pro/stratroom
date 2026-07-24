from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import require_role

router = APIRouter(prefix="/initiatives", tags=["initiatives"])


@router.get("")
async def list_initiatives(
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("member")),
):
    org_id = ctx["org_id"]

    result = await db.execute(
        text(
            "SELECT id, name, percent_complete, budget_planned, budget_actual, status "
            "FROM initiatives WHERE org_id = :oid ORDER BY id"
        ),
        {"oid": org_id},
    )
    rows = result.mappings().all()
    return {"initiatives": [dict(r) for r in rows]}
