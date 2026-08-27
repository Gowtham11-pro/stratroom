from fastapi import APIRouter, Depends
from app.core.deps import require_role
from app.core.rbac import filter_visible_rows
from app.services.java_bridge import bridge

router = APIRouter(tags=["compliance"])


@router.get("/compliance")
async def list_compliance_frameworks(ctx: dict = Depends(require_role("member"))):
    data = await bridge.get(bridge.db_service, "/compliance")
    rows = data if isinstance(data, list) else data.get("compliance", data.get("frameworks", data.get("list", [])))
    visible = await filter_visible_rows(ctx, rows)
    return {"compliance": visible}



@router.post("/compliance/simulate")
async def simulate_regulatory_impact(payload: dict, ctx: dict = Depends(require_role("member"))):
    regulation = payload.get("regulation", "gdpr")
    user_role = ctx["rbac_role"]
    user_email = ctx.get("email", "")
    user_name = ctx.get("first_name", "") or ctx.get("name", "") or user_email.split("@")[0].title()
    
    simulations = {
        "gdpr": {
            "title": "GDPR Article 30 Data Processing Inventory Update",
            "severity": "HIGH",
            "impact_score": "-4%",
            "affected_modules": ["Doc Intel", "Compliance", "Audit"],
            "required_actions": [
                "Map processing activities across 12 product databases",
                "Update DPO register for cross-border transfer logs",
                "Audit vendor data retention policies (3 vendors flagged)"
            ],
            "role_guidance": f"Logged in as {user_name} ({user_role.upper()}): " + (
                "Full compliance write access granted." if user_role in ("admin", "manager")
                else "Read-only simulation preview. Escalation ticket created for DPO."
            )
        },
        "ai-act": {
            "title": "EU AI Act - Risk Classification & Transparency",
            "severity": "CRITICAL",
            "impact_score": "-8%",
            "affected_modules": ["AI Predictive", "Risk Register", "Org"],
            "required_actions": [
                "Classify internal predictive models (Credit Scoring, Risk Forecast)",
                "Establish human-in-the-loop audit logs for AI recommendations",
                "File technical documentation with EU Database within 60 days"
            ],
            "role_guidance": f"Logged in as {user_name} ({user_role.upper()}): " + (
                "AI Governance lead access enabled." if user_role in ("admin", "manager")
                else "View-only access for internal AI risk classification."
            )
        },
        "dora": {
            "title": "DORA - Digital Operational Resilience Act (ICT Risk)",
            "severity": "HIGH",
            "impact_score": "-6%",
            "affected_modules": ["Incidents", "Continuity BCP", "Tasks"],
            "required_actions": [
                "Implement 4-hour major ICT incident notification threshold",
                "Conduct mandatory threat-led penetration testing (TLPT)",
                "Review critical third-party ICT service provider contracts"
            ],
            "role_guidance": f"Logged in as {user_name} ({user_role.upper()}): " + (
                "Resilience coordinator controls active." if user_role in ("admin", "manager")
                else "Incident reporting guidelines applied."
            )
        },
        "csrd": {
            "title": "CSRD - Corporate Sustainability Reporting Directive",
            "severity": "MEDIUM",
            "impact_score": "-3%",
            "affected_modules": ["Scorecard", "Zero-Based Budget", "Org"],
            "required_actions": [
                "Integrate Scope 1, 2, 3 carbon metrics into Scorecard KPIs",
                "Allocate Q4 budget for ESG third-party audit verification",
                "Publish double-materiality assessment report"
            ],
            "role_guidance": f"Logged in as {user_name} ({user_role.upper()}): " + (
                "Executive ESG dashboard access active." if user_role in ("admin", "manager")
                else "Departmental ESG target tracking mode."
            )
        }
    }

    result = simulations.get(regulation, simulations["gdpr"])
    result["user_context"] = {
        "email": user_email,
        "role": user_role,
        "is_admin": ctx["is_admin"],
        "is_manager": ctx["is_manager"]
    }
    return result

