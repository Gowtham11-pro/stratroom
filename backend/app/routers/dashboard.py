import logging

from fastapi import APIRouter, Depends

from app.core.deps import require_role
from app.services.java_bridge import bridge

logger = logging.getLogger("stratroom.dashboard")

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _parse_heat(risk_value: dict) -> int:
    """Extract heat score from a risk_value dict."""
    try:
        return int(risk_value.get("score", 0))
    except (ValueError, TypeError):
        return 0


def _get_json_val(d: dict, *keys, default=0):
    """Safely traverse a dict for a value, converting to float."""
    for k in keys:
        if isinstance(d, dict):
            d = d.get(k)
        else:
            return default
    try:
        return float(d) if d is not None else default
    except (ValueError, TypeError):
        return default


@router.get("/stats")
async def get_stats(ctx: dict = Depends(require_role("member"))):
    emp_id = ctx["user_id"]
    email = ctx.get("email")
    is_admin = ctx["is_admin"]
    role = ctx["rbac_role"]

    # Resolve MySQL org context
    mysql_user = None
    if email:
        rows = await bridge._mysql(
            "SELECT emp_id, org_id FROM employee_details WHERE LOWER(email_address) = LOWER(%s) LIMIT 1",
            (email,),
        )
        mysql_user = rows[0] if rows else None
    mysql_org_id = mysql_user["org_id"] if mysql_user else 0

    # ── 1. RISKS → Card 3 ──
    risk_rows = await bridge._mysql(
        "SELECT ID, risk_value, owner, status FROM risk_details WHERE active = 1"
    )
    total_risks = len(risk_rows)
    critical_risks = high_risks = medium_risks = low_risks = 0
    heat_scores = []
    for r in risk_rows:
        rv = bridge._parse_json_col(r, "risk_value")
        heat = _parse_heat(rv)
        heat_scores.append(heat)
        if heat >= 15:
            critical_risks += 1
        elif heat >= 10:
            high_risks += 1
        elif heat >= 5:
            medium_risks += 1
        else:
            low_risks += 1
    avg_inherent = round(sum(heat_scores) / len(heat_scores), 1) if heat_scores else 0

    # ── 2. SCORECARDS / KPI HEALTH → Card 1 ──
    scorecard_rows = await bridge._mysql(
        "SELECT id, org_id, perspective, kpi_name, target, actual, status "
        "FROM scorecard_kpis WHERE org_id = %s",
        (mysql_org_id or 1,),
    )
    total_scorecards = len(scorecard_rows)
    # Group by perspective
    perspective_data = {}
    for s in scorecard_rows:
        p = s.get("perspective", "General")
        if p not in perspective_data:
            perspective_data[p] = {"total": 0, "on_track": 0, "at_risk": 0, "critical": 0}
        perspective_data[p]["total"] += 1
        st = (s.get("status") or "").lower().strip()
        if st in ("on-track", "on track", "completed", "on_target"):
            perspective_data[p]["on_track"] += 1
        elif st in ("at-risk", "at risk", "overdue", "warning"):
            perspective_data[p]["at_risk"] += 1
        elif st in ("critical", "off-track", "off_track", "missed"):
            perspective_data[p]["critical"] += 1

    # ── 3. INCIDENTS → Card 7 ──
    incident_rows = await bridge.get(bridge.db_service, "/universalIncidentList") or []
    inc_list = incident_rows if isinstance(incident_rows, list) else []
    total_incidents = len(inc_list)
    open_incidents = sum(1 for i in inc_list if (i.get("status") or "").lower() != "resolved")
    p1_open = sum(
        1 for i in inc_list
        if str(i.get("severity", "")).upper() == "P1"
        and (i.get("status") or "").lower() != "resolved"
    )
    severity_map = {}
    for i in inc_list:
        sev = i.get("severity") or "Unknown"
        severity_map[sev] = severity_map.get(sev, 0) + 1

    # ── 4. AUDIT → Card 4 (FIXED: was showing incidents) ──
    audit_rows = await bridge.get(bridge.db_service, "/auditManagementList") or []
    audit_list = audit_rows if isinstance(audit_rows, list) else []
    total_audit = len(audit_list)
    open_audit = sum(1 for a in audit_list if (a.get("status") or "").lower() in ("open", "in_progress"))
    audit_with_rating = [a for a in audit_list if a.get("rating")]
    low_medium_audits = sum(
        1 for a in audit_with_rating
        if str(a.get("rating", "")).strip().lower() in ("low", "medium")
    )
    audit_completion_pct = round(low_medium_audits / total_audit * 100, 1) if total_audit else 0

    # ── 5. COMPLIANCE → Card 5 ──
    comp_rows = await bridge.get(bridge.db_service, "/compliance") or []
    comp_list = comp_rows if isinstance(comp_rows, list) else []
    total_compliance = len(comp_list)
    low_risk_comp = sum(
        1 for c in comp_list
        if str(c.get("risklevel", "")).lower() in ("low", "very low", "negligible")
    )
    # Estimate framework-level scores (SOC2, GDPR, ISO) from data
    comp_frameworks = {}
    for c in comp_list:
        name = c.get("name") or c.get("framework", "") or "General"
        if name not in comp_frameworks:
            comp_frameworks[name] = {"total": 0, "passing": 0}
        comp_frameworks[name]["total"] += 1
        rl = str(c.get("risklevel", "")).lower()
        if rl in ("low", "very low", "negligible"):
            comp_frameworks[name]["passing"] += 1
    comp_scores = {}
    for fname, fdata in comp_frameworks.items():
        comp_scores[fname] = round(fdata["passing"] / fdata["total"] * 100, 1) if fdata["total"] else 0
    compliance_pct = round(
        sum(comp_scores.values()) / len(comp_scores), 1
    ) if comp_scores else 0

    # ── 6. TASKS → Card 6 ──
    task_rows = await bridge.get(bridge.db_service, f"/retrieveTaskList/{emp_id}") or []
    task_list = task_rows if isinstance(task_rows, list) else []
    total_tasks = len(task_list)
    completed_tasks = sum(
        1 for t in task_list
        if (t.get("status") or "").lower() in ("completed", "done", "closed", "resolved")
    )
    overdue_tasks = sum(
        1 for t in task_list
        if (t.get("status") or "").lower() == "overdue"
    )
    completion_pct = round(completed_tasks / total_tasks * 100, 1) if total_tasks else 0

    # ── 7. BUDGETS → Card 8 ──
    budget_rows = await bridge.get(bridge.db_service, "/budgetsListview") or []
    budget_list = budget_rows if isinstance(budget_rows, list) else []
    total_budget_planned = sum(_get_json_val(b, "budgetAmount", default=0) for b in budget_list)
    total_budget_actual = sum(_get_json_val(b, "actualAmount", default=0) for b in budget_list)
    budget_variance = total_budget_actual - total_budget_planned
    budget_utilisation = round(
        total_budget_actual / total_budget_planned * 100, 1
    ) if total_budget_planned else 0

    # ── 8. MEETINGS → Card 9 (FIXED: was showing scorecards) ──
    meeting_rows = await bridge.get(bridge.db_service, "/meetingManagementList/") or []
    meeting_list = meeting_rows if isinstance(meeting_rows, list) else []
    total_meetings = len(meeting_list)

    # ── 9. INITIATIVES / PROJECTS → Card 2 ──
    init_rows = await bridge.get(bridge.db_service, "/initiativesList/") or []
    init_list = init_rows if isinstance(init_rows, list) else []
    total_initiatives = len(init_list)
    progress_vals = []
    budget_planned = 0.0
    budget_actual = 0.0
    for init in init_list:
        raw = init.get("progress") or init.get("progressval") or "0"
        try:
            progress_vals.append(float(str(raw).replace("%", "")))
        except (ValueError, TypeError):
            pass
        try:
            budget_planned += float(init.get("totalBudget") or init.get("budgetAmount") or 0)
        except (ValueError, TypeError):
            pass
        try:
            budget_actual += float(init.get("totalActual") or init.get("actualAmount") or 0)
        except (ValueError, TypeError):
            pass
    avg_progress = round(sum(progress_vals) / len(progress_vals), 1) if progress_vals else 0
    on_track_init = sum(
        1 for i in init_list
        if (i.get("status") or "").lower() in ("on track", "on-track", "in progress", "active")
    )
    off_track_init = sum(
        1 for i in init_list
        if (i.get("status") or "").lower() in ("off track", "off-track", "delayed", "at risk")
    )
    portfolio_budget = total_budget_planned + total_budget_actual

    # ── 10. EMPLOYEES → org members ──
    emp_count_row = await bridge._mysql(
        "SELECT COUNT(*) as cnt FROM employee_details WHERE status = 'Active'",
        one=True,
    )
    active_org_members = emp_count_row["cnt"] if emp_count_row else 0

    # ── STRATEGIC HEALTH → Card 10 (computed aggregate) ──
    # Weighted score: 40% compliance, 30% risk resilience, 30% avg progress
    risk_resilience = max(
        0, 100 - (critical_risks * 15 + high_risks * 8 + medium_risks * 3)
    ) if total_risks else 100
    strategic_health = round(
        compliance_pct * 0.4 + risk_resilience * 0.3 + avg_progress * 0.3
    )

    return {
        # Card 1 — KPI Health (from scorecards)
        "kpi_health_perspectives": perspective_data,
        "kpi_health_on_track": sum(p["on_track"] for p in perspective_data.values()),
        "kpi_health_at_risk": sum(p["at_risk"] for p in perspective_data.values()),
        "kpi_health_critical": sum(p["critical"] for p in perspective_data.values()),
        # Card 2 — Projects / Initiatives
        "total_initiatives": total_initiatives,
        "avg_progress": avg_progress,
        "projects_ontrack": on_track_init,
        "projects_offtrack": off_track_init,
        "portfolio_budget": round(portfolio_budget, 2),
        # Card 3 — Risk Register
        "total_risks": total_risks,
        "avg_inherent_heat": avg_inherent,
        "critical_risks": critical_risks,
        "high_risks": high_risks,
        "medium_risks": medium_risks,
        "low_risks": low_risks,
        # Card 4 — Audit (FIXED: now real audit data)
        "audit_total": total_audit,
        "audit_open": open_audit,
        "audit_completion_pct": audit_completion_pct,
        "audit_compliant_audits": low_medium_audits,
        # Card 5 — Compliance
        "compliance_pct": compliance_pct,
        "compliance_total": total_compliance,
        "compliance_gaps": total_compliance - low_risk_comp,
        # Card 6 — Tasks
        "total_tasks": total_tasks,
        "completed_tasks": completed_tasks,
        "overdue_tasks": overdue_tasks,
        "task_completion_pct": completion_pct,
        # Card 7 — Incidents
        "total_incidents": total_incidents,
        "open_incidents": open_incidents,
        "p1_open": p1_open,
        "severity_breakdown": severity_map,
        # Card 8 — Budgets
        "budget_variance": round(budget_variance, 2),
        "budget_planned": round(total_budget_planned, 2),
        "budget_actual": round(total_budget_actual, 2),
        "budget_utilisation": budget_utilisation,
        # Card 9 — Meetings (FIXED: now real meetings data)
        "total_meetings": total_meetings,
        # Card 10 — Strategic Health
        "strategic_health": strategic_health,
        "active_org_members": active_org_members,
        "risk_resilience": round(risk_resilience, 1),
        # Backward compat fields
        "total_scorecards": total_scorecards,
        "rbac_role": role,
    }
