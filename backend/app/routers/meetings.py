from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.db import get_db
from app.core.deps import require_role

router = APIRouter(tags=["meetings"])


@router.get("/meetings")
async def list_meetings(
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("member")),
):
    user_id = ctx["user_id"]
    org_id = ctx["org_id"]
    is_admin = ctx["is_admin"]
    is_manager = ctx["is_manager"]

    if is_admin or is_manager:
        result = await db.execute(
            text("SELECT id, title, meeting_date, meeting_time, location, duration, attendees, priority FROM meetings WHERE org_id = :oid ORDER BY id"),
            {"oid": org_id},
        )
    else:
        email = ctx["email"]
        result = await db.execute(
            text("SELECT id, title, meeting_date, meeting_time, location, duration, attendees, priority FROM meetings WHERE org_id = :oid AND attendees ILIKE :email ORDER BY id"),
            {"oid": org_id, "email": f"%{email}%"},
        )
    rows = result.mappings().all()
    return {"meetings": [dict(r) for r in rows]}
