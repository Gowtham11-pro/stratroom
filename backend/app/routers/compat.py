import logging

from fastapi import APIRouter, Depends, Query

from app.core.deps import require_role
from app.services.java_bridge import bridge

logger = logging.getLogger("stratroom.compat")

router = APIRouter(prefix="/stratroom", tags=["compat"])


@router.get("/masterValue")
async def compat_master_value(
    value_type: str = Query(default="", alias="type"),
    ctx: dict = Depends(require_role("member")),
):
    if value_type == "GL_ACCOUNT":
        data = await bridge.get(bridge.db_service, "/retrieveMasterValue")
        rows = data if isinstance(data, list) else data.get("values", data.get("masterValues", []))
        gl_values = [r for r in rows if r.get("glAccount") or r.get("gl_account")]
        return {"values": gl_values}
    return {"values": []}


@router.get("/scoreCardList")
async def compat_scorecard_list(
    limit: int = Query(default=0),
    pageId: int = Query(default=0),
    ctx: dict = Depends(require_role("member")),
):
    emp_id = ctx["user_id"]
    is_admin = ctx["is_admin"]
    is_manager = ctx["is_manager"]

    if is_admin or is_manager:
        data = await bridge.get(bridge.db_service, "/scoreCardList")
    else:
        data = await bridge.get(bridge.db_service, f"/scoreCardDetailList/{emp_id}")

    rows = data if isinstance(data, list) else data.get("scorecards", data.get("list", []))
    if limit > 0:
        rows = rows[:limit]
    return {"scorecards": rows}


@router.get("/riskList")
async def compat_risk_list_bare(
    pageId: int = Query(default=0),
    ctx: dict = Depends(require_role("member")),
):
    emp_id = ctx["user_id"]
    is_admin = ctx["is_admin"]
    is_manager = ctx["is_manager"]

    if is_admin or is_manager:
        data = await bridge.get(bridge.db_service, "/riskListView")
    else:
        data = await bridge.get(bridge.db_service, f"/riskList/{emp_id}")

    rows = data if isinstance(data, list) else data.get("risks", data.get("list", []))
    return {"risks": rows}


@router.get("/riskList/{emp_id}")
async def compat_risk_list(
    emp_id: int,
    pageId: int = Query(default=0),
    ctx: dict = Depends(require_role("member")),
):
    is_admin = ctx["is_admin"]
    is_manager = ctx["is_manager"]

    if is_admin or is_manager:
        data = await bridge.get(bridge.db_service, "/riskListView")
    else:
        data = await bridge.get(bridge.db_service, f"/riskList/{emp_id}")

    rows = data if isinstance(data, list) else data.get("risks", data.get("list", []))
    return {"risks": rows}


@router.get("/kpiList")
async def compat_kpi_list_bare(
    ctx: dict = Depends(require_role("member")),
):
    emp_id = ctx["user_id"]
    is_admin = ctx["is_admin"]
    is_manager = ctx["is_manager"]

    if is_admin or is_manager:
        data = await bridge.get(bridge.db_service, "/scoreCardList")
    else:
        data = await bridge.get(bridge.db_service, f"/scoreCardDetailList/{emp_id}")

    rows = data if isinstance(data, list) else data.get("scorecards", data.get("list", []))
    perspectives = {}
    for r in rows:
        p = r.get("perspective")
        if not p:
            continue
        if p not in perspectives:
            perspectives[p] = {"perspective": p, "avg_score": 0, "kpi_count": 0, "on_track": 0, "at_risk": 0, "critical": 0}
        perspectives[p]["kpi_count"] += 1
        status = (r.get("status") or "").lower()
        if status in perspectives[p]:
            perspectives[p][status] += 1
    return {"kpis": list(perspectives.values())}


@router.get("/kpiList/{emp_id}")
async def compat_kpi_list(
    emp_id: int,
    ctx: dict = Depends(require_role("member")),
):
    is_admin = ctx["is_admin"]
    is_manager = ctx["is_manager"]

    if is_admin or is_manager:
        data = await bridge.get(bridge.db_service, "/scoreCardList")
    else:
        data = await bridge.get(bridge.db_service, f"/scoreCardDetailList/{emp_id}")

    rows = data if isinstance(data, list) else data.get("scorecards", data.get("list", []))
    perspectives = {}
    for r in rows:
        p = r.get("perspective")
        if not p:
            continue
        if p not in perspectives:
            perspectives[p] = {"perspective": p, "avg_score": 0, "kpi_count": 0, "on_track": 0, "at_risk": 0, "critical": 0}
        perspectives[p]["kpi_count"] += 1
        status = (r.get("status") or "").lower()
        if status in perspectives[p]:
            perspectives[p][status] += 1
    return {"kpis": list(perspectives.values())}


@router.get("/initiativesList")
async def compat_initiatives_list(
    pageId: int = Query(default=0),
    loadFlag: str = Query(default=""),
    ctx: dict = Depends(require_role("member")),
):
    emp_id = ctx["user_id"]
    data = await bridge.get(bridge.db_service, f"/initiativesList/{emp_id}")
    rows = data if isinstance(data, list) else data.get("initiatives", data.get("list", []))
    return {"initiatives": rows}


@router.get("/budgetsList")
async def compat_budgets_list_bare(
    ctx: dict = Depends(require_role("member")),
):
    emp_id = ctx["user_id"]
    is_admin = ctx["is_admin"]
    is_manager = ctx["is_manager"]

    if is_admin or is_manager:
        data = await bridge.get(bridge.db_service, "/budgetsListview")
    else:
        data = await bridge.get(bridge.db_service, f"/budgets/{emp_id}")

    rows = data if isinstance(data, list) else data.get("budgets", data.get("list", []))
    return {"budgets": rows}


@router.get("/budgetsList/{page_id}")
async def compat_budgets_list(
    page_id: int,
    ctx: dict = Depends(require_role("member")),
):
    emp_id = ctx["user_id"]
    is_admin = ctx["is_admin"]
    is_manager = ctx["is_manager"]

    if is_admin or is_manager:
        data = await bridge.get(bridge.db_service, "/budgetsListview")
    else:
        data = await bridge.get(bridge.db_service, f"/budgets/{emp_id}")

    rows = data if isinstance(data, list) else data.get("budgets", data.get("list", []))
    return {"budgets": rows}


@router.get("/auditManagementList")
async def compat_audit_list(ctx: dict = Depends(require_role("member"))):
    data = await bridge.get(bridge.db_service, "/auditManagementList")
    rows = data if isinstance(data, list) else data.get("findings", data.get("auditManagement", data.get("list", [])))
    return {"findings": rows}


@router.get("/riskeventlist")
async def compat_risk_event_list(ctx: dict = Depends(require_role("member"))):
    data = await bridge.get(bridge.db_service, "/riskeventlist")
    rows = data if isinstance(data, list) else data.get("incidents", data.get("list", []))
    return {"incidents": rows}


@router.get("/retrieveTaskList")
async def compat_task_list_bare(
    ctx: dict = Depends(require_role("member")),
):
    emp_id = ctx["user_id"]
    data = await bridge.get(bridge.db_service, f"/retrieveTaskList/{emp_id}")
    rows = data if isinstance(data, list) else data.get("tasks", data.get("list", []))
    return {"tasks": rows}


@router.get("/retrieveTaskList/{emp_id}")
async def compat_task_list(
    emp_id: int,
    dateRange: str = Query(default="current"),
    task_type: str = Query(default="all", alias="type"),
    ctx: dict = Depends(require_role("member")),
):
    data = await bridge.get(bridge.db_service, f"/retrieveTaskList/{emp_id}")
    rows = data if isinstance(data, list) else data.get("tasks", data.get("list", []))
    return {"tasks": rows}


@router.get("/meetingManagementList")
async def compat_meeting_list_bare(
    ctx: dict = Depends(require_role("member")),
):
    emp_id = ctx["user_id"]
    data = await bridge.get(bridge.db_service, f"/meetingManagementList/{emp_id}")
    rows = data if isinstance(data, list) else data.get("meetings", data.get("list", []))
    return {"meetings": rows}


@router.get("/meetingManagementList/{emp_id}")
async def compat_meeting_list(
    emp_id: int,
    ctx: dict = Depends(require_role("member")),
):
    data = await bridge.get(bridge.db_service, f"/meetingManagementList/{emp_id}")
    rows = data if isinstance(data, list) else data.get("meetings", data.get("list", []))
    return {"meetings": rows}


@router.get("/retrieveComplinValue")
async def compat_compliance_list(
    dateRange: str = Query(default="current"),
    ctx: dict = Depends(require_role("member")),
):
    data = await bridge.get(bridge.db_service, "/compliance")
    rows = data if isinstance(data, list) else data.get("compliance", data.get("list", []))
    return {"compliance": rows}


@router.get("/retrieveOrgChart")
async def compat_org_chart(
    ctx: dict = Depends(require_role("member")),
):
    data = await bridge.get(bridge.db_service, "/orgStructureList")
    rows = data if isinstance(data, list) else data.get("org", data.get("list", []))
    return {"org_chart": rows}


@router.get("/retrieveSwot")
async def compat_swot_list(
    ctx: dict = Depends(require_role("member")),
):
    data = await bridge.get(bridge.db_service, "/swotList")
    rows = data if isinstance(data, list) else data.get("items", data.get("list", []))
    quadrant_order = {"strength": 1, "weakness": 2, "opportunity": 3, "threat": 4}
    items = []
    for r in rows:
        q = (r.get("quadrant") or "").lower()
        items.append({
            "id": r.get("id"),
            "quadrant": q,
            "content": r.get("content") or "",
            "sort_order": quadrant_order.get(q, 5),
        })
    items.sort(key=lambda x: (quadrant_order.get(x["quadrant"], 5), x["sort_order"]))
    return {"items": items}


@router.get("/retrievePestel")
async def compat_pestel_list(
    ctx: dict = Depends(require_role("member")),
):
    data = await bridge.get(bridge.db_service, "/pestelList")
    rows = data if isinstance(data, list) else data.get("items", data.get("list", []))
    category_order = {"political": 1, "economic": 2, "social": 3, "technology": 4, "environmental": 5, "legal": 6}
    items = []
    for r in rows:
        c = (r.get("category") or "").lower()
        items.append({
            "id": r.get("id"),
            "category": c,
            "impact": (r.get("impact") or "medium").lower(),
            "content": r.get("content") or "",
            "sort_order": category_order.get(c, 7),
        })
    items.sort(key=lambda x: (category_order.get(x["category"], 7), x["sort_order"]))
    return {"items": items}
