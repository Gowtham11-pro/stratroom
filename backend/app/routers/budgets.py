from fastapi import APIRouter, Depends
from app.core.deps import require_role
from app.services.java_bridge import bridge

router = APIRouter(tags=["budgets"])


@router.get("/budgets")
async def list_budget_lines(ctx: dict = Depends(require_role("member"))):
    emp_id = ctx["user_id"]
    is_admin = ctx["is_admin"]
    is_manager = ctx["is_manager"]

    if is_admin or is_manager:
        data = await bridge.get(bridge.db_service, "/budgetsListview")
    else:
        data = await bridge.get(bridge.db_service, f"/budgets/{emp_id}")

    rows = data if isinstance(data, list) else data.get("budgets", data.get("list", []))
    return {"budgets": rows}


@router.get("/budgets/summary")
async def budget_summary(ctx: dict = Depends(require_role("member"))):
    emp_id = ctx["user_id"]
    is_admin = ctx["is_admin"]
    is_manager = ctx["is_manager"]

    if is_admin or is_manager:
        data = await bridge.get(bridge.db_service, "/budgetsListview")
    else:
        data = await bridge.get(bridge.db_service, f"/budgets/{emp_id}")

    rows = data if isinstance(data, list) else data.get("budgets", data.get("list", []))
    total = sum(float(r.get("total", 0) or 0) for r in rows)
    projects = set(r.get("project") for r in rows if r.get("project"))
    gl_accounts = set(r.get("glAccount") or r.get("gl_account") for r in rows if r.get("glAccount") or r.get("gl_account"))

    return {
        "line_count": len(rows),
        "total_amount": total,
        "project_count": len(projects),
        "gl_count": len(gl_accounts),
    }
