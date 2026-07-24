from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.db import get_db
from app.core.deps import require_role

router = APIRouter(tags=["compliance"])


@router.get("/compliance")
async def list_compliance_frameworks(
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("member")),
):
    org_id = ctx["org_id"]
    result = await db.execute(
        text("SELECT id, name, description, score, status FROM compliance_frameworks WHERE org_id = :oid ORDER BY id"),
        {"oid": org_id},
    )
    rows = result.mappings().all()
    return {"frameworks": [dict(r) for r in rows]}
