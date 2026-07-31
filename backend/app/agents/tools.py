import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.java_bridge import bridge

logger = logging.getLogger("stratroom.agent_tools")

BRIDGE_MODULE_PATHS = {
    "risks": "/riskListView",
    "incidents": "/universalIncidentList",
    "scorecards": "/scoreCardList",
    "budgets": "/budgetsListview",
    "tasks": "/retrieveTaskList/",
    "meetings": "/meetingManagementList/",
    "audit": "/auditManagementList",
    "compliance": "/compliance",
    "initiatives": "/initiativesList/",
    "projects": "/projectsList",
    "swot": "/swotList",
    "pestel": "/pestelList",
    "bcp": "/bcpList",
}


async def _fetch_bridge(module: str) -> list[dict] | None:
    path = BRIDGE_MODULE_PATHS.get(module)
    if not path:
        return None
    try:
        data = await bridge.get(bridge.db_service, path)
        rows = data if isinstance(data, list) else data.get(module, data.get("list", []))
        return rows
    except Exception as exc:
        logger.warning("Bridge query failed for module %s: %s", module, exc)
        return None


async def fetch_module_data(db: AsyncSession, module: str, org_id: int | None = None) -> str:
    # Try MySQL bridge first for supported modules
    bridge_rows = await _fetch_bridge(module)
    if bridge_rows is not None:
        if not bridge_rows:
            return f"[No data in {module}]"
        lines = []
        for d in bridge_rows:
            parts = [f"{k}={v}" for k, v in d.items() if v is not None]
            lines.append(" | ".join(parts))
        return "\n".join(lines)

    queries = {}

    sql = queries.get(module)
    if not sql:
        return f"[No data source for module: {module}]"

    if org_id is None:
        return f"[No org context — cannot load {module}]"
    params = {"org_id": org_id}
    result = await db.execute(text(sql), params)
    rows = result.mappings().all()
    if not rows:
        return f"[No data in {module}]"

    lines = []
    for r in rows:
        d = dict(r)
        if module == "tasks":
            parts = [
                f"[TASK {d.get('id','?')}]",
                f"{d.get('title','')}",
                f"({d.get('priority','')}, {d.get('status','')})",
            ]
        else:
            parts = [f"{k}={v}" for k, v in d.items() if v is not None]
        lines.append(" | ".join(parts))
    return "\n".join(lines)


AGENT_MODULE_MAP = {
    "strategy": ["scorecards", "initiatives", "projects", "swot", "pestel"],
    "risk": ["risks", "audit", "compliance"],
    "scorecard": ["scorecards", "initiatives", "projects"],
    "finance": ["budgets", "scorecards", "initiatives"],
    "compliance": ["compliance", "audit", "risks"],
    "audit": ["audit", "compliance", "risks"],
    "task": ["tasks"],
    "meetings": ["meetings", "tasks", "initiatives"],
    "projects": ["initiatives", "projects", "budgets"],
    "incident": ["incidents", "risks", "compliance"],
    "executive": [
        "scorecards", "initiatives", "projects", "risks", "incidents",
        "budgets", "compliance", "audit", "swot", "pestel",
    ],
}


async def fetch_agent_context(db: AsyncSession, agent_name: str, org_id: int | None = None) -> str:
    modules = AGENT_MODULE_MAP.get(agent_name, [])
    if not modules:
        return "[No module data configured for this agent]"

    parts = [f"=== {agent_name.upper()} AGENT DATA ==="]
    for mod in modules:
        data = await fetch_module_data(db, mod, org_id)
        parts.append(f"\n--- {mod.upper()} ---\n{data}")
    return "\n".join(parts)
