from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def fetch_module_data(db: AsyncSession, module: str, org_id: int | None = None) -> str:
    queries = {
        "risks": (
            "SELECT id, name, owner, inherent_likelihood, inherent_impact, "
            "residual_likelihood, residual_impact, description, mitigation "
            "FROM risks WHERE org_id = :org_id ORDER BY (residual_likelihood * residual_impact) DESC"
        ),
        "incidents": (
            "SELECT id, code, title, severity, status, region, mttr_hours, sla_hours "
            "FROM incidents WHERE org_id = :org_id ORDER BY "
            "CASE severity WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 ELSE 3 END, created_at DESC"
        ),
        "scorecards": (
            "SELECT perspective, kpi_name, target, actual, owner, status "
            "FROM scorecards WHERE org_id = :org_id ORDER BY perspective, kpi_name"
        ),
        "budgets": (
            "SELECT gl_name, budget_type, project, total, department, notes "
            "FROM budget_lines WHERE org_id = :org_id ORDER BY total DESC"
        ),
        "tasks": (
            "SELECT id, title, agent, priority, owner, due_date, status "
            "FROM tasks WHERE org_id = :org_id ORDER BY "
            "CASE priority WHEN 'Critical' THEN 1 WHEN 'High' THEN 2 WHEN 'Medium' THEN 3 ELSE 4 END"
        ),
        "meetings": (
            "SELECT id, title, meeting_date, meeting_time, location, duration, attendees, priority "
            "FROM meetings WHERE org_id = :org_id ORDER BY meeting_date, meeting_time"
        ),
        "audit": (
            "SELECT id, title, severity, owner, due_date, status "
            "FROM audit_findings WHERE org_id = :org_id ORDER BY "
            "CASE severity WHEN 'Critical' THEN 1 WHEN 'High' THEN 2 WHEN 'Medium' THEN 3 ELSE 4 END"
        ),
        "compliance": (
            "SELECT id, name, description, score, status "
            "FROM compliance_frameworks WHERE org_id = :org_id ORDER BY score ASC"
        ),
        "initiatives": (
            "SELECT id, name, percent_complete, budget_planned, budget_actual, status "
            "FROM initiatives WHERE org_id = :org_id ORDER BY status, percent_complete DESC"
        ),
        "projects": (
            "SELECT id, name, owner, budget, progress, due_date, status "
            "FROM projects WHERE org_id = :org_id ORDER BY "
            "CASE status WHEN 'at_risk' THEN 1 WHEN 'on_track' THEN 2 WHEN 'ahead' THEN 3 ELSE 4 END"
        ),
        "swot": (
            "SELECT quadrant, content FROM swot_items WHERE org_id = :org_id ORDER BY sort_order"
        ),
        "pestel": (
            "SELECT category, impact, content FROM pestel_items WHERE org_id = :org_id ORDER BY sort_order"
        ),
        "bcp": (
            "SELECT id, name, owner, rto, rpo, mtd, impact, status, category "
            "FROM bcp_processes WHERE org_id = :org_id ORDER BY sort_order"
        ),
    }

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
    "risk": ["risks", "incidents", "audit", "compliance"],
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
