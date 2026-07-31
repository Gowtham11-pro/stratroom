from fastapi import APIRouter, Depends
from app.core.deps import require_role
from app.services.java_bridge import bridge

router = APIRouter(prefix="/initiatives", tags=["initiatives"])


@router.get("")
async def list_initiatives(ctx: dict = Depends(require_role("member"))):
    emp_id = ctx["user_id"]
    data = await bridge.get(bridge.db_service, f"/initiativesList/{emp_id}")
    rows = data if isinstance(data, list) else data.get("initiatives", data.get("list", []))
    return {"initiatives": rows}
