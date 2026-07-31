from fastapi import APIRouter, Depends
from app.core.deps import require_role
from app.services.java_bridge import bridge

router = APIRouter(tags=["compliance"])


@router.get("/compliance")
async def list_compliance_frameworks(ctx: dict = Depends(require_role("member"))):
    data = await bridge.get(bridge.db_service, "/compliance")
    rows = data if isinstance(data, list) else data.get("compliance", data.get("frameworks", data.get("list", [])))
    return {"compliance": rows}
