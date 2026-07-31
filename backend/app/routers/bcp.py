import logging

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import require_role
from app.services.java_bridge import bridge

logger = logging.getLogger("stratroom.bcp")

router = APIRouter(tags=["bcp"])


@router.get("/bcp")
async def list_bcp_processes(
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("member")),
):
    org_id = ctx["org_id"]
    try:
        data = await bridge.get(bridge.db_service, "/bcpList")
        rows = data if isinstance(data, list) else data.get("processes", data.get("list", []))
    except Exception as exc:
        logger.warning("Failed to query BCP via bridge: %s", exc)
        rows = []
    by_id = {}
    for r in rows:
        r['children'] = []
        r['parent_id'] = None
        by_id[r.get('id')] = r
    roots = [r for r in rows if not r.get('parent_id')]
    return {"processes": roots}


@router.get("/bcp/flat")
async def list_bcp_flat(
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("member")),
):
    org_id = ctx["org_id"]
    try:
        data = await bridge.get(bridge.db_service, "/bcpList")
        rows = data if isinstance(data, list) else data.get("processes", data.get("list", []))
    except Exception as exc:
        logger.warning("Failed to query BCP via bridge: %s", exc)
        rows = []
    return {"processes": rows}
