from fastapi import APIRouter, Depends
from app.core.deps import require_role
from app.services.java_bridge import bridge

router = APIRouter(tags=["meetings"])


@router.get("/meetings")
async def list_meetings(ctx: dict = Depends(require_role("member"))):
    emp_id = ctx["user_id"]
    is_admin = ctx["is_admin"]
    is_manager = ctx["is_manager"]

    if is_admin or is_manager:
        data = await bridge.get(bridge.db_service, f"/meetingManagementList/{emp_id}")
    else:
        email = ctx["email"]
        data = await bridge.get(bridge.db_service, f"/meetingManagementList/{emp_id}")

    rows = data if isinstance(data, list) else data.get("meetings", data.get("list", []))
    return {"meetings": rows}
