from fastapi import APIRouter, Depends
from app.core.deps import require_role
from app.services.java_bridge import bridge

router = APIRouter(prefix="/incidents", tags=["incidents"])


@router.get("")
async def list_incidents(ctx: dict = Depends(require_role("member"))):
    data = await bridge.get(bridge.db_service, "/universalIncidentList")
    rows = data if isinstance(data, list) else data.get("incidents", data.get("list", []))
    return {"incidents": rows}
