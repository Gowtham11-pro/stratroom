import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from app.core.deps import require_role
from app.core.rbac import _record_owner_emp_id, enforce_record_access, filter_visible_rows
from app.services.java_bridge import bridge

logger = logging.getLogger("stratroom.scorecards")

router = APIRouter(tags=["scorecards"])

# ── SKL Group Scorecard Excel Structure Mapping ──
# Maps objective_id (from kpi table) → perspective + objective info from the Excel
# This is built from SKL_Group_Scorecard_2026.xlsx analysis
SKL_PERSPECTIVES = {
    "SKL-P01": {"name": "Financial Performance and Growth", "type": "Financial", "tab": "financial"},
    "SKL-P02": {"name": "Customer and Market", "type": "Customer and Stakeholder", "tab": "customer"},
    "SKL-P03": {"name": "Manufacturing and Operational Excellence", "type": "Internal Process", "tab": "ops"},
    "SKL-P04": {"name": "Capacity Expansion and Capital Projects", "type": "Capital Projects", "tab": "projects"},
    "SKL-P05": {"name": "Governance Risk and Compliance", "type": "Governance", "tab": "esg"},
    "SKL-P06": {"name": "People and Organisational Capability", "type": "Learning and Growth", "tab": "people"},
}

# Maps KPI ID → perspective ID + objective ID + objective name
# Built from the Excel: each KPI belongs to an objective which belongs to a perspective
SKL_KPI_MAP = {
    # P01: Financial Performance and Growth
    "SKL-K01": {"persp": "SKL-P01", "obj_id": "SKL-O01", "obj_name": "Grow group revenue"},
    "SKL-K02": {"persp": "SKL-P01", "obj_id": "SKL-O01", "obj_name": "Grow group revenue"},
    "SKL-K03": {"persp": "SKL-P01", "obj_id": "SKL-O01", "obj_name": "Grow group revenue"},
    "SKL-K04": {"persp": "SKL-P01", "obj_id": "SKL-O02", "obj_name": "Improve profitability"},
    "SKL-K05": {"persp": "SKL-P01", "obj_id": "SKL-O02", "obj_name": "Improve profitability"},
    "SKL-K06": {"persp": "SKL-P01", "obj_id": "SKL-O02", "obj_name": "Improve profitability"},
    "SKL-K07": {"persp": "SKL-P01", "obj_id": "SKL-O03", "obj_name": "Strengthen shareholder returns"},
    "SKL-K08": {"persp": "SKL-P01", "obj_id": "SKL-O03", "obj_name": "Strengthen shareholder returns"},
    "SKL-K09": {"persp": "SKL-P01", "obj_id": "SKL-O03", "obj_name": "Strengthen shareholder returns"},
    # P02: Customer and Market
    "SKL-K10": {"persp": "SKL-P02", "obj_id": "SKL-O04", "obj_name": "Diversify customer base"},
    "SKL-K11": {"persp": "SKL-P02", "obj_id": "SKL-O04", "obj_name": "Diversify customer base"},
    "SKL-K12": {"persp": "SKL-P02", "obj_id": "SKL-O04", "obj_name": "Diversify customer base"},
    "SKL-K13": {"persp": "SKL-P02", "obj_id": "SKL-O05", "obj_name": "Improve customer satisfaction"},
    "SKL-K14": {"persp": "SKL-P02", "obj_id": "SKL-O05", "obj_name": "Improve customer satisfaction"},
    "SKL-K15": {"persp": "SKL-P02", "obj_id": "SKL-O05", "obj_name": "Improve customer satisfaction"},
    "SKL-K16": {"persp": "SKL-P02", "obj_id": "SKL-O06", "obj_name": "Grow order book"},
    "SKL-K17": {"persp": "SKL-P02", "obj_id": "SKL-O06", "obj_name": "Grow order book"},
    "SKL-K18": {"persp": "SKL-P02", "obj_id": "SKL-O06", "obj_name": "Grow order book"},
    # P03: Manufacturing and Operational Excellence
    "SKL-K19": {"persp": "SKL-P03", "obj_id": "SKL-O07", "obj_name": "Improve production efficiency"},
    "SKL-K20": {"persp": "SKL-P03", "obj_id": "SKL-O07", "obj_name": "Improve production efficiency"},
    "SKL-K21": {"persp": "SKL-P03", "obj_id": "SKL-O07", "obj_name": "Improve production efficiency"},
    "SKL-K22": {"persp": "SKL-P03", "obj_id": "SKL-O08", "obj_name": "Reduce production wastage"},
    "SKL-K23": {"persp": "SKL-P03", "obj_id": "SKL-O08", "obj_name": "Reduce production wastage"},
    "SKL-K24": {"persp": "SKL-P03", "obj_id": "SKL-O08", "obj_name": "Reduce production wastage"},
    "SKL-K25": {"persp": "SKL-P03", "obj_id": "SKL-O09", "obj_name": "Ensure on-time delivery"},
    "SKL-K26": {"persp": "SKL-P03", "obj_id": "SKL-O09", "obj_name": "Ensure on-time delivery"},
    "SKL-K27": {"persp": "SKL-P03", "obj_id": "SKL-O09", "obj_name": "Ensure on-time delivery"},
    # P04: Capacity Expansion and Capital Projects
    "SKL-K28": {"persp": "SKL-P04", "obj_id": "SKL-O10", "obj_name": "Deliver Kisaju plant expansion"},
    "SKL-K29": {"persp": "SKL-P04", "obj_id": "SKL-O10", "obj_name": "Deliver Kisaju plant expansion"},
    "SKL-K30": {"persp": "SKL-P04", "obj_id": "SKL-O10", "obj_name": "Deliver Kisaju plant expansion"},
    "SKL-K31": {"persp": "SKL-P04", "obj_id": "SKL-O11", "obj_name": "Increase production capacity"},
    "SKL-K32": {"persp": "SKL-P04", "obj_id": "SKL-O11", "obj_name": "Increase production capacity"},
    "SKL-K33": {"persp": "SKL-P04", "obj_id": "SKL-O11", "obj_name": "Increase production capacity"},
    "SKL-K34": {"persp": "SKL-P04", "obj_id": "SKL-O12", "obj_name": "Manage capital project budget"},
    "SKL-K35": {"persp": "SKL-P04", "obj_id": "SKL-O12", "obj_name": "Manage capital project budget"},
    "SKL-K36": {"persp": "SKL-P04", "obj_id": "SKL-O12", "obj_name": "Manage capital project budget"},
    # P05: Governance Risk and Compliance
    "SKL-K37": {"persp": "SKL-P05", "obj_id": "SKL-O13", "obj_name": "Strengthen listed company compliance"},
    "SKL-K38": {"persp": "SKL-P05", "obj_id": "SKL-O13", "obj_name": "Strengthen listed company compliance"},
    "SKL-K39": {"persp": "SKL-P05", "obj_id": "SKL-O13", "obj_name": "Strengthen listed company compliance"},
    "SKL-K40": {"persp": "SKL-P05", "obj_id": "SKL-O14", "obj_name": "Manage working capital"},
    "SKL-K41": {"persp": "SKL-P05", "obj_id": "SKL-O14", "obj_name": "Manage working capital"},
    "SKL-K42": {"persp": "SKL-P05", "obj_id": "SKL-O14", "obj_name": "Manage working capital"},
    "SKL-K43": {"persp": "SKL-P05", "obj_id": "SKL-O15", "obj_name": "Reduce financial risk exposure"},
    "SKL-K44": {"persp": "SKL-P05", "obj_id": "SKL-O15", "obj_name": "Reduce financial risk exposure"},
    "SKL-K45": {"persp": "SKL-P05", "obj_id": "SKL-O15", "obj_name": "Reduce financial risk exposure"},
    # P06: People and Organisational Capability
    "SKL-K46": {"persp": "SKL-P06", "obj_id": "SKL-O16", "obj_name": "Improve employee engagement and retention"},
    "SKL-K47": {"persp": "SKL-P06", "obj_id": "SKL-O16", "obj_name": "Improve employee engagement and retention"},
    "SKL-K48": {"persp": "SKL-P06", "obj_id": "SKL-O16", "obj_name": "Improve employee engagement and retention"},
    "SKL-K49": {"persp": "SKL-P06", "obj_id": "SKL-O17", "obj_name": "Strengthen workplace health and safety"},
    "SKL-K50": {"persp": "SKL-P06", "obj_id": "SKL-O17", "obj_name": "Strengthen workplace health and safety"},
    "SKL-K51": {"persp": "SKL-P06", "obj_id": "SKL-O17", "obj_name": "Strengthen workplace health and safety"},
    "SKL-K52": {"persp": "SKL-P06", "obj_id": "SKL-O18", "obj_name": "Build workforce capability"},
    "SKL-K53": {"persp": "SKL-P06", "obj_id": "SKL-O18", "obj_name": "Build workforce capability"},
    "SKL-K54": {"persp": "SKL-P06", "obj_id": "SKL-O18", "obj_name": "Build workforce capability"},
}

SKL_KPI_DEFAULTS = {
    "SKL-K01": {"actual": "12.4", "target": "15", "type": "Percentage", "currency": ""},
    "SKL-K02": {"actual": "1731260000", "target": "2000000000", "type": "Number", "currency": "USD"},
    "SKL-K03": {"actual": "27.4", "target": "30", "type": "Percentage", "currency": ""},
    "SKL-K04": {"actual": "16.5", "target": "18", "type": "Percentage", "currency": ""},
    "SKL-K05": {"actual": "19.1", "target": "20.65", "type": "Percentage", "currency": ""},
    "SKL-K06": {"actual": "21.9", "target": "25", "type": "Percentage", "currency": ""},
    "SKL-K07": {"actual": "24.21", "target": "23.07", "type": "Percentage", "currency": ""},
    "SKL-K08": {"actual": "3.0", "target": "3.0", "type": "Number", "currency": ""},
    "SKL-K09": {"actual": "27.7", "target": "30", "type": "Percentage", "currency": ""},
    "SKL-K10": {"actual": "18.5", "target": "20", "type": "Percentage", "currency": ""},
    "SKL-K11": {"actual": "1420", "target": "1500", "type": "Number", "currency": ""},
    "SKL-K12": {"actual": "14.2", "target": "15", "type": "Percentage", "currency": ""},
    "SKL-K13": {"actual": "88", "target": "90", "type": "Number", "currency": ""},
    "SKL-K14": {"actual": "24", "target": "12", "type": "Number", "currency": ""},
    "SKL-K15": {"actual": "65", "target": "70", "type": "Number", "currency": ""},
    "SKL-K16": {"actual": "450000000", "target": "500000000", "type": "Number", "currency": "USD"},
    "SKL-K17": {"actual": "28.5", "target": "30", "type": "Percentage", "currency": ""},
    "SKL-K18": {"actual": "72.4", "target": "75", "type": "Percentage", "currency": ""},
    "SKL-K19": {"actual": "82.5", "target": "85", "type": "Percentage", "currency": ""},
    "SKL-K20": {"actual": "42", "target": "30", "type": "Number", "currency": ""},
    "SKL-K21": {"actual": "18500", "target": "20000", "type": "Number", "currency": ""},
    "SKL-K22": {"actual": "3.2", "target": "2.5", "type": "Percentage", "currency": ""},
    "SKL-K23": {"actual": "1.8", "target": "1.0", "type": "Percentage", "currency": ""},
    "SKL-K24": {"actual": "4500", "target": "4000", "type": "Number", "currency": "KES"},
    "SKL-K25": {"actual": "94.2", "target": "96", "type": "Percentage", "currency": ""},
    "SKL-K26": {"actual": "4.5", "target": "3.0", "type": "Number", "currency": ""},
    "SKL-K27": {"actual": "98.1", "target": "99", "type": "Percentage", "currency": ""},
    "SKL-K28": {"actual": "75", "target": "80", "type": "Percentage", "currency": ""},
    "SKL-K29": {"actual": "92", "target": "95", "type": "Percentage", "currency": ""},
    "SKL-K30": {"actual": "2", "target": "0", "type": "Number", "currency": ""},
    "SKL-K31": {"actual": "25000", "target": "30000", "type": "Number", "currency": ""},
    "SKL-K32": {"actual": "78.4", "target": "85", "type": "Percentage", "currency": ""},
    "SKL-K33": {"actual": "60", "target": "70", "type": "Percentage", "currency": ""},
    "SKL-K34": {"actual": "4.5", "target": "5.0", "type": "Percentage", "currency": ""},
    "SKL-K35": {"actual": "88", "target": "90", "type": "Percentage", "currency": ""},
    "SKL-K36": {"actual": "12500", "target": "12000", "type": "Number", "currency": "USD"},
    "SKL-K37": {"actual": "100", "target": "100", "type": "Percentage", "currency": ""},
    "SKL-K38": {"actual": "0", "target": "0", "type": "Number", "currency": ""},
    "SKL-K39": {"actual": "95", "target": "100", "type": "Percentage", "currency": ""},
    "SKL-K40": {"actual": "45", "target": "40", "type": "Number", "currency": ""},
    "SKL-K41": {"actual": "52", "target": "45", "type": "Number", "currency": ""},
    "SKL-K42": {"actual": "60", "target": "65", "type": "Number", "currency": ""},
    "SKL-K43": {"actual": "0.45", "target": "0.50", "type": "Number", "currency": ""},
    "SKL-K44": {"actual": "4.8", "target": "5.0", "type": "Number", "currency": ""},
    "SKL-K45": {"actual": "85", "target": "90", "type": "Percentage", "currency": ""},
    "SKL-K46": {"actual": "78", "target": "82", "type": "Number", "currency": ""},
    "SKL-K47": {"actual": "8.5", "target": "7.0", "type": "Percentage", "currency": ""},
    "SKL-K48": {"actual": "2.1", "target": "1.8", "type": "Percentage", "currency": ""},
    "SKL-K49": {"actual": "0.15", "target": "0.00", "type": "Number", "currency": ""},
    "SKL-K50": {"actual": "1", "target": "0", "type": "Number", "currency": ""},
    "SKL-K51": {"actual": "96.5", "target": "98", "type": "Percentage", "currency": ""},
    "SKL-K52": {"actual": "32", "target": "40", "type": "Number", "currency": ""},
    "SKL-K53": {"actual": "85", "target": "90", "type": "Percentage", "currency": ""},
    "SKL-K54": {"actual": "92", "target": "95", "type": "Percentage", "currency": ""},
}

VALID_STATUSES = {"on-track", "at-risk", "critical"}


class ScorecardCreate(BaseModel):
    perspective: str
    kpi_name: str
    target: Optional[float] = None
    actual: Optional[float] = None
    owner: Optional[str] = None
    status: str = "on-track"
    assigned_user_id: Optional[int] = None

    @field_validator("perspective")
    @classmethod
    def validate_perspective(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Perspective is required")
        if len(v) > 200:
            raise ValueError("Perspective exceeds maximum length of 200")
        return v

    @field_validator("kpi_name")
    @classmethod
    def validate_kpi_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("KPI name is required")
        if len(v) > 500:
            raise ValueError("KPI name exceeds maximum length of 500")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {v}")
        return v


class ScorecardUpdate(BaseModel):
    perspective: Optional[str] = None
    kpi_name: Optional[str] = None
    target: Optional[float] = None
    actual: Optional[float] = None
    owner: Optional[str] = None
    status: Optional[str] = None
    assigned_user_id: Optional[int] = None

    @field_validator("perspective")
    @classmethod
    def validate_perspective(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("Perspective cannot be empty")
        return v

    @field_validator("kpi_name")
    @classmethod
    def validate_kpi_name(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("KPI name cannot be empty")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {v}")
        return v


JUNK_KPIS_SQL = (
    "AND LOWER(TRIM(kpi_name)) NOT IN ('baby','news','newws','sirenn','tron','jessi','jess','dracks',"
    "'trans','punitha','narayanan','rose','tset2','kpifere','finnce','score','kpi 2','kpi new','kpi02','kpi01',"
    "'kpi - objective - fin1','fin_obj1_kpi1','customer kpi','kpi','obj1 kpi1','sironn') "
    "AND LOWER(kpi_name) NOT LIKE '%%newws%%' "
    "AND LOWER(kpi_name) NOT LIKE '%%sirenn%%' "
    "AND LOWER(kpi_name) NOT LIKE '%%tset2%%' "
    "AND LOWER(kpi_name) NOT LIKE '%%kpifere%%' "
    "AND LOWER(kpi_name) NOT LIKE '%%finnce%%' "
    "AND LOWER(kpi_name) NOT LIKE '%%fin_obj1_kpi1%%'"
)

@router.get("/scorecards")
async def list_scorecards(
    ctx: dict = Depends(require_role("member")),
):
    org_id = ctx["org_id"]

    rows = await bridge._mysql(
        "SELECT id, perspective, kpi_name, target, actual, owner, status, assigned_user_id "
        "FROM scorecard_kpis WHERE id IN ("
        f"SELECT MIN(id) FROM scorecard_kpis WHERE org_id = %s {JUNK_KPIS_SQL} "
        "GROUP BY perspective, kpi_name, target, actual, status"
        ") ORDER BY perspective, id",
        (org_id,),
    )

    rows = await filter_visible_rows(ctx, rows)

    for r in rows:
        t = r.get("target")
        a = r.get("actual")
        r["target"] = float(t) if t is not None else None
        r["actual"] = float(a) if a is not None else None
    return {"scorecards": rows}


@router.get("/scorecards/summary")
async def scorecard_summary(
    ctx: dict = Depends(require_role("member")),
):
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]
    is_admin = ctx["is_admin"]
    is_manager = ctx["is_manager"]

    if is_admin or is_manager:
        rows = await bridge._mysql(
            "SELECT perspective, "
            "ROUND(AVG(actual)) as avg_score, "
            "COUNT(*) as kpi_count, "
            "SUM(CASE WHEN status = 'on-track' THEN 1 ELSE 0 END) as on_track, "
            "SUM(CASE WHEN status = 'at-risk' THEN 1 ELSE 0 END) as at_risk, "
            "SUM(CASE WHEN status = 'critical' THEN 1 ELSE 0 END) as critical "
            f"FROM (SELECT MIN(id) as mid, perspective, actual, status "
            f"FROM scorecard_kpis WHERE org_id = %s {JUNK_KPIS_SQL} "
            "GROUP BY perspective, kpi_name, target, actual, status) t "
            "GROUP BY perspective ORDER BY MIN(mid)",
            (org_id,),
        )
    else:
        rows = await bridge._mysql(
            "SELECT perspective, "
            "ROUND(AVG(actual)) as avg_score, "
            "COUNT(*) as kpi_count, "
            "SUM(CASE WHEN status = 'on-track' THEN 1 ELSE 0 END) as on_track, "
            "SUM(CASE WHEN status = 'at-risk' THEN 1 ELSE 0 END) as at_risk, "
            "SUM(CASE WHEN status = 'critical' THEN 1 ELSE 0 END) as critical "
            f"FROM (SELECT MIN(id) as mid, perspective, actual, status "
            f"FROM scorecard_kpis WHERE org_id = %s AND assigned_user_id = %s {JUNK_KPIS_SQL} "
            "GROUP BY perspective, kpi_name, target, actual, status) t "
            "GROUP BY perspective ORDER BY MIN(mid)",
            (org_id, user_id),
        )

    for r in rows:
        r["avg_score"] = int(r["avg_score"]) if r["avg_score"] is not None else 0
        r["kpi_count"] = int(r["kpi_count"])
        r["on_track"] = int(r["on_track"])
        r["at_risk"] = int(r["at_risk"])
        r["critical"] = int(r["critical"])
    return {"perspectives": rows}


@router.get("/scorecards/list")
async def list_scorecards_dropdown(
    ctx: dict = Depends(require_role("member")),
):
    """Returns distinct scorecard definitions for multi-scorecard dropdown selection."""
    org_id = ctx["org_id"]
    try:
        rows = await bridge._mysql(
            "SELECT id, score_name, perspective_name, org_id FROM score_card WHERE org_id = %s ORDER BY id ASC",
            (org_id,),
        )
        items = [
            {
                "id": r.get("id"),
                "name": r.get("score_name") or f"Scorecard #{r.get('id')}",
                "perspective": r.get("perspective_name") or "General",
                "org_id": r.get("org_id"),
            }
            for r in (rows or [])
        ]
        return {"scorecards": items}
    except Exception as exc:
        logger.warning("Failed to query score_card list: %s", exc)
        return {"scorecards": []}


def _parse_kpi_blob(raw):
    """Parse the kpi_value JSON blob, handling the b'...' wrapper and escaped JSON."""
    if not raw:
        return {}
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "replace")
    s = str(raw)
    # Strip b'...' or b"..." wrapper
    if (s.startswith("b'") and s.endswith("'")) or (s.startswith('b"') and s.endswith('"')):
        s = s[2:-1]
    try:
        return json.loads(s.replace("\\'", "'").replace("\\\\", "\\"))
    except Exception:
        try:
            return json.loads(s)
        except Exception:
            return {}


def _compute_score(actual, target, formula=""):
    """Compute KPI score from actual and target using the formula."""
    try:
        a = float(actual) if actual not in (None, "", "0") else 0.0
        t = float(target) if target not in (None, "", "0") else 0.0
        if t == 0:
            return 0.0
        # Default formula: (Actual/Target)*100
        return round((a / t) * 100, 2)
    except (ValueError, TypeError, ZeroDivisionError):
        return 0.0


def _rag_status(score, red=60, amber=80, green=100):
    """Determine RAG status from score and threshold boundaries."""
    try:
        s = float(score)
        r = float(red) if red else 60
        a = float(amber) if amber else 80
    except (ValueError, TypeError):
        return "critical"
    if s >= a:
        return "on-track"
    elif s >= r:
        return "at-risk"
    else:
        return "critical"


def _format_value(val, data_type="", currency=""):
    """Format a value based on its data type and currency."""
    if val is None or val == "" or val == "0":
        return ""
    try:
        v = float(val)
    except (ValueError, TypeError):
        return str(val)
    dt = (data_type or "").lower()
    cur = (currency or "").strip()
    if dt == "percentage":
        if v == int(v):
            return f"{int(v)}%"
        return f"{v:.1f}%" if abs(v) < 100 else f"{v:.0f}%"
    if cur and cur != "0.0" and cur != "0":
        prefix = cur if cur not in ("KES", "USD", "GBP", "EUR") else {"KES": "KES ", "USD": "$", "GBP": "£", "EUR": "€"}.get(cur, cur + " ")
        if abs(v) >= 1_000_000:
            return f"{prefix}{v/1_000_000:,.4f} M"
        elif abs(v) >= 1_000:
            return f"{prefix}{v:,.0f}"
        return f"{prefix}{v:,.2f}"
    if abs(v) >= 1_000_000:
        return f"{v/1_000_000:,.4f} M"
    if v == int(v) and abs(v) < 10_000:
        return str(int(v))
    return f"{v:,.2f}" if abs(v) >= 100 else f"{v}"


@router.get("/scorecards/balanced")
async def get_balanced_scorecard(
    perspective: Optional[str] = None,
    ctx: dict = Depends(require_role("member")),
):
    """Returns the full SKL Group Scorecard with hierarchical Perspective → Objective → KPI.

    Queries the `kpi` table for SKL-* entries (org_id=4), enriches with
    `org_kpi_details` actuals, and groups by the Excel structure mapping.
    """
    try:
        # 1. Get all SKL KPIs from the kpi table
        skl_kpis = await bridge._mysql(
            "SELECT id, kpi_name, kpi_id, objective_id, kpi_value, "
            "start_date, end_date "
            "FROM kpi WHERE kpi_id LIKE 'SKL-K%%' AND org_id = 4 "
            "ORDER BY kpi_id",
            (),
        )
        if not skl_kpis:
            skl_kpis = []

        # 2. Get org_kpi_details for actual/target values
        kpi_db_ids = [k["id"] for k in skl_kpis]
        actuals_map = {}  # node_key → latest actual/target
        if kpi_db_ids:
            placeholders = ",".join(["%s"] * len(kpi_db_ids))
            okd_rows = await bridge._mysql(
                f"SELECT node_key, mtd_actual, mtd_target, real_date_from, "
                f"real_date_to, type, currency "
                f"FROM org_kpi_details "
                f"WHERE node_key IN ({placeholders}) "
                f"ORDER BY node_key, real_date_from DESC",
                tuple(kpi_db_ids),
            )
            if okd_rows:
                for row in okd_rows:
                    nk = row.get("node_key")
                    if nk and nk not in actuals_map:
                        actuals_map[nk] = row

        # 3. Build the hierarchical structure
        perspectives_data = {}  # persp_id → {name, objectives: {obj_id → {name, kpis: []}}}

        for kpi_row in skl_kpis:
            kpi_id_code = kpi_row.get("kpi_id", "")
            mapping = SKL_KPI_MAP.get(kpi_id_code)
            if not mapping:
                continue

            persp_id = mapping["persp"]
            obj_id = mapping["obj_id"]
            obj_name = mapping["obj_name"]
            persp_info = SKL_PERSPECTIVES.get(persp_id, {})

            if persp_id not in perspectives_data:
                perspectives_data[persp_id] = {
                    "id": persp_id,
                    "name": persp_info.get("name", "Unknown"),
                    "type": persp_info.get("type", ""),
                    "tab": persp_info.get("tab", "all"),
                    "objectives": {},
                }

            if obj_id not in perspectives_data[persp_id]["objectives"]:
                perspectives_data[persp_id]["objectives"][obj_id] = {
                    "id": obj_id,
                    "name": obj_name,
                    "kpis": [],
                }

            # Parse KPI blob for metadata
            blob = _parse_kpi_blob(kpi_row.get("kpi_value", ""))
            db_id = kpi_row["id"]

            # Get actuals from org_kpi_details with fallback to SKL_KPI_DEFAULTS
            def_val = SKL_KPI_DEFAULTS.get(kpi_id_code, {})
            okd = actuals_map.get(db_id, {})
            raw_actual = okd.get("mtd_actual") or blob.get("actual")
            if raw_actual in (None, "", "0", 0):
                raw_actual = def_val.get("actual", "")

            raw_target = okd.get("mtd_target") or blob.get("target")
            if raw_target in (None, "", "0", 0):
                raw_target = def_val.get("target", "")

            data_type = blob.get("dataType") or def_val.get("type", "")
            currency = blob.get("kpiCurrency") or blob.get("targetCurrency") or def_val.get("currency", "")
            period = blob.get("kpi_measurement") or "Quarterly"
            weight = blob.get("weight", 0)
            red_thresh = blob.get("optioncolor1") or "60"
            amber_thresh = blob.get("optioncolor2") or "80"

            score = _compute_score(raw_actual, raw_target, blob.get("thresholdFormula", ""))
            status = _rag_status(score, red_thresh, amber_thresh)

            formatted_actual = _format_value(raw_actual, data_type, currency)
            formatted_target = _format_value(raw_target, data_type, currency)

            perspectives_data[persp_id]["objectives"][obj_id]["kpis"].append({
                "id": kpi_id_code,
                "db_id": db_id,
                "name": kpi_row.get("kpi_name", ""),
                "period": period,
                "score": score,
                "actual": formatted_actual,
                "actual_raw": float(raw_actual) if raw_actual and raw_actual != "" else None,
                "target": formatted_target,
                "target_raw": float(raw_target) if raw_target and raw_target not in ("", "0") else None,
                "status": status,
                "data_type": data_type,
                "currency": currency,
                "weight": float(weight) if weight else 0,
            })

        # 4. Convert to ordered list and compute perspective scores
        result_perspectives = []
        persp_order = ["SKL-P01", "SKL-P02", "SKL-P03", "SKL-P04", "SKL-P05", "SKL-P06"]
        for pid in persp_order:
            if pid not in perspectives_data:
                continue
            pdata = perspectives_data[pid]

            # Filter by perspective if requested
            if perspective and perspective.lower() != "all":
                tab = pdata.get("tab", "")
                if tab != perspective.lower():
                    continue

            # Convert objectives dict to ordered list
            objectives_list = []
            all_scores = []
            for oid in sorted(pdata["objectives"].keys()):
                obj = pdata["objectives"][oid]
                obj_scores = [k["score"] for k in obj["kpis"] if k["score"] > 0]
                obj_avg = round(sum(obj_scores) / len(obj_scores), 2) if obj_scores else 0.0
                all_scores.extend(obj_scores)
                objectives_list.append({
                    "id": obj["id"],
                    "name": obj["name"],
                    "score": obj_avg,
                    "kpis": obj["kpis"],
                })

            persp_score = round(sum(all_scores) / len(all_scores), 2) if all_scores else 0.0
            total_kpis = sum(len(o["kpis"]) for o in objectives_list)

            result_perspectives.append({
                "id": pdata["id"],
                "name": pdata["name"],
                "type": pdata["type"],
                "tab": pdata["tab"],
                "score": persp_score,
                "total_kpis": total_kpis,
                "objectives": objectives_list,
            })

        return {
            "scorecard_name": "SKL Group Scorecard",
            "scorecard_description": "SKL Group - Owner Corporate Scorecard | Strategic Period 2026-2030",
            "total_perspectives": len(result_perspectives),
            "total_kpis": sum(p["total_kpis"] for p in result_perspectives),
            "perspectives": result_perspectives,
        }

    except Exception as exc:
        logger.error("Failed to build balanced scorecard: %s", exc, exc_info=True)
        return {
            "scorecard_name": "SKL Group Scorecard",
            "perspectives": [],
            "error": str(exc),
        }


@router.get("/scorecards/{scorecard_id}")
async def get_scorecard(
    scorecard_id: int,
    ctx: dict = Depends(require_role("member")),
):
    data = await bridge.get(bridge.db_service, f"/scorecard/{scorecard_id}")
    if not data:
        raise HTTPException(status_code=404, detail="Scorecard not found")
    row = data[0] if isinstance(data, list) and data else (data if isinstance(data, dict) else {"scorecard": data})
    await enforce_record_access(ctx, _record_owner_emp_id(row))
    return row


@router.post("/scorecards", status_code=201)
async def create_scorecard(
    payload: ScorecardCreate,
    ctx: dict = Depends(require_role("manager")),
):
    body = {
        "perspective": payload.perspective,
        "kpiName": payload.kpi_name,
        "target": payload.target,
        "actual": payload.actual,
        "owner": payload.owner or ctx["email"],
        "status": payload.status,
        "assignedUserId": payload.assigned_user_id or ctx["user_id"],
        "empId": ctx["user_id"],
        "orgId": ctx["org_id"],
    }
    result = await bridge.post(bridge.db_service, "/scorecard", json=body)
    scorecard_id = result.get("id")
    logger.info("Scorecard created: id=%s org=%s by user=%s", scorecard_id, ctx["org_id"], ctx["user_id"])
    return {"id": scorecard_id, "ok": True}


@router.put("/scorecards/{scorecard_id}")
async def update_scorecard(
    scorecard_id: int,
    payload: ScorecardUpdate,
    ctx: dict = Depends(require_role("member")),
):
    data = await bridge.get(bridge.db_service, f"/scorecard/{scorecard_id}")
    if not data:
        raise HTTPException(status_code=404, detail="Scorecard not found")
    record = data[0] if isinstance(data, list) and data else (data if isinstance(data, dict) else {})
    await enforce_record_access(ctx, _record_owner_emp_id(record))

    body = {"id": scorecard_id}
    if payload.perspective is not None:
        body["perspective"] = payload.perspective
    if payload.kpi_name is not None:
        body["kpiName"] = payload.kpi_name
    if payload.target is not None:
        body["target"] = payload.target
    if payload.actual is not None:
        body["actual"] = payload.actual
    if payload.owner is not None:
        body["owner"] = payload.owner
    if payload.status is not None:
        body["status"] = payload.status
    if payload.assigned_user_id is not None:
        body["assignedUserId"] = payload.assigned_user_id

    await bridge.put(bridge.db_service, "/scorecardDetails", json=body)
    logger.info("Scorecard updated: id=%d org=%s", scorecard_id, ctx["org_id"])
    return {"ok": True}


@router.delete("/scorecards/{scorecard_id}")
async def delete_scorecard(
    scorecard_id: int,
    ctx: dict = Depends(require_role("admin")),
):
    data = await bridge.get(bridge.db_service, f"/scorecard/{scorecard_id}")
    if not data:
        raise HTTPException(status_code=404, detail="Scorecard not found")
    record = data[0] if isinstance(data, list) and data else (data if isinstance(data, dict) else {})
    await enforce_record_access(ctx, _record_owner_emp_id(record))

    await bridge.delete(bridge.db_service, f"/scorecard/{scorecard_id}")
    logger.info("Scorecard deleted: id=%d org=%s", scorecard_id, ctx["org_id"])
    return {"ok": True}

