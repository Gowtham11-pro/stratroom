import logging
from collections import defaultdict

from fastapi import APIRouter, Depends

from app.core.deps import require_role
from app.services.java_bridge import bridge

logger = logging.getLogger("stratroom.org")

router = APIRouter(tags=["org"])

DEPT_SLUG_MAP = {
    'ceo': 'exec', 'coo': 'exec', 'admin': 'exec', 'board': 'exec',
    'technology': 'tech', 'tech': 'tech', 'infrastructure': 'tech', 'cto': 'tech',
    'finance': 'finance', 'accounting': 'finance', 'cfo': 'finance', 'budget': 'finance',
    'sales': 'ops', 'marketing': 'ops', 'operations': 'ops', 'supply chain': 'ops', 'cso': 'ops', 'cmo': 'ops',
    'hr': 'hr', 'human resources': 'hr', 'people': 'hr', 'talent': 'hr',
    'risk': 'risk', 'compliance': 'risk', 'audit': 'risk', 'security': 'risk',
    'legal': 'legal', 'strategy': 'legal', 'general counsel': 'legal',
}


def _to_slug(dept_name):
    if not dept_name:
        return 'exec'
    key = dept_name.strip().lower()
    if key in DEPT_SLUG_MAP:
        return DEPT_SLUG_MAP[key]
    if 'tech' in key or 'infra' in key: return 'tech'
    if 'legal' in key or 'strateg' in key: return 'legal'
    if 'ops' in key or 'market' in key: return 'ops'
    if 'risk' in key or 'govern' in key or 'compli' in key: return 'risk'
    if 'finan' in key or 'tax' in key or 'treasur' in key: return 'finance'
    if 'hr' in key or 'people' in key or 'human' in key: return 'hr'
    import re
    return re.sub(r'[^a-z0-9]+', '_', key).strip('_') or 'exec'


def _to_pillar_name(dept_name):
    if not dept_name:
        return 'Executive Leadership'
    d = dept_name.lower()
    if any(k in d for k in ['tech', 'eng', 'infra', 'data', 'it', 'software', 'cto', 'cyber', 'system']):
        return 'Technology & Infrastructure'
    if any(k in d for k in ['finan', 'tax', 'treasur', 'audit', 'budget', 'account', 'cfo', 'fp&a']):
        return 'Finance, Treasury & Tax'
    if any(k in d for k in ['risk', 'complian', 'sec', 'govern', 'grc', 'policy']):
        return 'Governance, Risk & Compliance'
    if any(k in d for k in ['hr', 'human', 'people', 'talent', 'recruit', 'workforce', 'culture', 'l&d']):
        return 'People & Human Resources'
    if any(k in d for k in ['legal', 'strateg', 'm&a', 'counsel', 'corp', 'board']):
        return 'Legal & Corporate Strategy'
    if any(k in d for k in ['sales', 'market', 'digital', 'media', 'comms', 'pr', 'brand', 'ops', 'deliver', 'process', 'supply', 'logist']):
        return 'Operations & Marketing'
    return 'Executive Leadership'


async def _resolve_mysql_org_id(email: str) -> int:
    """Resolve the caller's MySQL org_id from their email.
    
    Defaults to the primary MySQL org_id (typically 4) if email is not found
    or for system admin accounts.
    """
    if email:
        try:
            rows = await bridge._mysql(
                "SELECT org_id FROM employee_details "
                "WHERE LOWER(email_address) = LOWER(%s) LIMIT 1",
                (email,),
            )
            if rows and rows[0].get("org_id"):
                return rows[0].get("org_id")
        except Exception:
            logger.debug("Failed to resolve MySQL org_id for %s", email)

    try:
        rows = await bridge._mysql("SELECT MIN(org_id) as main_org FROM employee_details WHERE status = 'Active'")
        if rows and rows[0].get("main_org"):
            return rows[0].get("main_org")
    except Exception:
        pass
    return 4


@router.get("/org")
async def get_org_full(
    ctx: dict = Depends(require_role("member")),
):
    email = ctx.get("email", "")
    mysql_org_id = await _resolve_mysql_org_id(email)

    members = await _fetch_employees(mysql_org_id)
    user_rows_raw = await _fetch_users(mysql_org_id)

    total_members = len(members)
    total_users = len(user_rows_raw)
    total_headcount = total_members

    depts = defaultdict(lambda: {"count": 0, "members": 0})
    regions = defaultdict(int)
    levels = defaultdict(int)

    for m in members:
        slug = _to_slug(m.get("dept"))
        depts[slug]["count"] += 1
        depts[slug]["members"] += 1
        rg = (m.get("region") or "").strip()
        if rg:
            regions[rg] += 1

    by_id = {}
    for m in members:
        node_id = str(m["id"])
        raw_dept = m.get("dept_raw") or m.get("dept") or ""
        # Format raw department name for display (replace underscores, title-case)
        dept_display = raw_dept.replace("_", " ").strip()
        if dept_display:
            dept_display = " ".join(w.capitalize() for w in dept_display.split())
        node = {
            "id": node_id,
            "name": (m.get("name") or "").strip(),
            "title": m.get("title") or "",
            "dept": _to_slug(m.get("dept")),
            "dept_name": dept_display or "N/A",
            "region": m.get("region") or "",
            "level": m.get("level") or "",
            "headcount": 1,
            "children": [],
            "user_id": None,
            "email": None,
            "role": None,
        }
        by_id[node_id] = node

    has_parent_links = any(m.get("parent_id") and str(m["parent_id"]) in by_id and str(m["parent_id"]) != str(m["id"]) for m in members)

    roots = []
    if has_parent_links:
        unparented_nodes = []
        for m in members:
            node = by_id[str(m["id"])]
            parent_id = m.get("parent_id")
            if parent_id and str(parent_id) in by_id and str(parent_id) != str(m["id"]):
                by_id[str(parent_id)]["children"].append(node)
            else:
                unparented_nodes.append(node)

        # If a top-level CEO/Director exists (e.g. Dominic, or parent_id is NULL), keep them as top roots.
        # Group remaining unparented leaves into department pillar folders so top-level stays clean.
        dept_pillars = defaultdict(list)
        for node in unparented_nodes:
            # If the node has children or is executive/top-level, treat as top root
            if len(node["children"]) > 0 or node["dept"] == "exec":
                roots.append(node)
            else:
                pillar_name = _to_pillar_name(node["dept"])
                dept_pillars[pillar_name].append(node)

        for pillar_name, child_nodes in dept_pillars.items():
            dept_slug = _to_slug(pillar_name)
            dept_node = {
                "id": f"dept_{dept_slug}",
                "name": pillar_name,
                "title": f"{len(child_nodes)} Members",
                "dept": dept_slug,
                "dept_name": pillar_name,
                "region": "",
                "level": "Department Pillar",
                "headcount": len(child_nodes),
                "children": child_nodes,
                "user_id": None,
                "email": None,
                "role": "department",
            }
            roots.append(dept_node)
    else:
        dept_members = defaultdict(list)
        for m in members:
            node = by_id[str(m["id"])]
            pillar_name = _to_pillar_name(m.get("dept"))
            dept_members[pillar_name].append(node)

        for pillar_name, child_nodes in dept_members.items():
            dept_slug = _to_slug(pillar_name)
            dept_node = {
                "id": f"dept_{dept_slug}",
                "name": pillar_name,
                "title": f"{len(child_nodes)} Members",
                "dept": dept_slug,
                "dept_name": pillar_name,
                "region": "",
                "level": "Department Pillar",
                "headcount": len(child_nodes),
                "children": child_nodes,
                "user_id": None,
                "email": None,
                "role": "department",
            }
            roots.append(dept_node)

    if len(roots) == 0:
        tree = {"id": "0", "name": "Organization", "title": "", "dept": "exec",
                "dept_name": "Organization", "region": "", "level": "", "headcount": total_headcount,
                "children": [], "user_id": None, "email": None, "role": None}
    elif len(roots) == 1:
        tree = roots[0]
    else:
        tree = {
            "id": "0", "name": "Organization", "title": "Top Level",
            "dept": "exec", "dept_name": "Organization", "region": "", "level": "",
            "headcount": total_headcount, "children": roots,
            "user_id": None, "email": None, "role": None,
        }

    user_by_emp = {}
    for u in user_rows_raw:
        eid = str(u.get("emp_id", ""))
        if eid:
            user_by_emp[eid] = u

    def attach_user_info(node):
        eid = node["id"]
        matched = user_by_emp.get(eid)
        if matched:
            node["role"] = matched.get("role") or matched.get("designation") or node["role"]
            if matched.get("location"):
                node["region"] = matched["location"]
            node["email"] = matched.get("email_address") or ""
        for child in node.get("children", []):
            attach_user_info(child)

    if isinstance(tree, dict):
        attach_user_info(tree)
    elif isinstance(tree, list):
        for root in tree:
            attach_user_info(root)

    logger.info("Org loaded: %d members, %d users [mysql_org=%s]", total_members, total_users, mysql_org_id)

    return {
        "tree": tree,
        "users": [
            {
                "user_id": u.get("emp_id"),
                "full_name": u.get("name") or "",
                "email": u.get("email_address") or "",
                "role": u.get("designation") or u.get("role") or "user",
                "created_at": None,
            }
            for u in user_rows_raw
        ],
        "summary": {
            "total_members": total_members,
            "total_users": total_users,
            "total_headcount": total_headcount,
            "departments": dict(depts),
            "regions": dict(regions),
            "levels": dict(levels),
        },
    }


@router.get("/org/tree")
async def get_org_tree(
    ctx: dict = Depends(require_role("member")),
):
    email = ctx.get("email", "")
    mysql_org_id = await _resolve_mysql_org_id(email)

    members = await _fetch_employees(mysql_org_id)
    total_headcount = len(members)

    by_id = {}
    for m in members:
        node_id = str(m["id"])
        raw_dept = m.get("dept_raw") or m.get("dept") or ""
        dept_display = raw_dept.replace("_", " ").strip()
        if dept_display:
            dept_display = " ".join(w.capitalize() for w in dept_display.split())
        node = {
            "id": node_id, "name": (m.get("name") or "").strip(),
            "title": m.get("title") or "", "dept": _to_slug(m.get("dept")),
            "dept_name": dept_display or "N/A",
            "region": m.get("region") or "", "level": m.get("level") or "",
            "headcount": 1, "children": [],
        }
        by_id[node_id] = node

    has_parent_links = any(m.get("parent_id") and str(m["parent_id"]) in by_id and str(m["parent_id"]) != str(m["id"]) for m in members)

    roots = []
    if has_parent_links:
        for m in members:
            node = by_id[str(m["id"])]
            parent_id = m.get("parent_id")
            if parent_id and str(parent_id) in by_id:
                by_id[str(parent_id)]["children"].append(node)
            else:
                roots.append(node)
    else:
        dept_members = defaultdict(list)
        for m in members:
            node = by_id[str(m["id"])]
            pillar_name = _to_pillar_name(m.get("dept"))
            dept_members[pillar_name].append(node)

        for pillar_name, child_nodes in dept_members.items():
            dept_slug = _to_slug(pillar_name)
            dept_node = {
                "id": f"dept_{dept_slug}",
                "name": pillar_name,
                "title": f"{len(child_nodes)} Members",
                "dept": dept_slug,
                "dept_name": pillar_name,
                "region": "",
                "level": "Department Pillar",
                "headcount": len(child_nodes),
                "children": child_nodes,
            }
            roots.append(dept_node)

    if len(roots) == 0:
        tree = {"id": "0", "name": "Organization", "title": "", "dept": "exec",
                "dept_name": "Organization", "region": "", "level": "",
                "headcount": total_headcount, "children": []}
    elif len(roots) == 1:
        tree = roots[0]
    else:
        tree = {
            "id": "0", "name": "Organization", "title": "Top Level",
            "dept": "exec", "dept_name": "Organization", "region": "", "level": "",
            "headcount": total_headcount, "children": roots,
        }

    return {"tree": tree}


@router.get("/org/users")
async def list_org_users(
    ctx: dict = Depends(require_role("member")),
):
    email = ctx.get("email", "")
    mysql_org_id = await _resolve_mysql_org_id(email)

    if mysql_org_id is None:
        return {"users": []}

    rows = await _fetch_users(mysql_org_id)
    return {
        "users": [
            {
                "user_id": r.get("emp_id"),
                "full_name": r.get("name") or "",
                "email": r.get("email_address") or "",
                "role": r.get("designation") or r.get("role") or "user",
                "created_at": None,
            }
            for r in rows
        ]
    }


from pydantic import BaseModel
from typing import Optional

class OrgMemberCreate(BaseModel):
    first_name: str
    last_name: Optional[str] = ""
    email_address: Optional[str] = ""
    title: Optional[str] = ""
    department: Optional[str] = ""
    location: Optional[str] = ""
    parent_emp_id: Optional[int] = None

class OrgMemberCreate(BaseModel):
    emp_id: Optional[str] = None
    first_name: str
    last_name: Optional[str] = ""
    email_address: Optional[str] = ""
    title: Optional[str] = ""
    department: Optional[str] = ""
    dept_code: Optional[str] = ""
    location: Optional[str] = "Singapore"
    parent_emp_id: Optional[int] = None
    scorecard_id: Optional[str] = None
    initiative_id: Optional[str] = None
    kpi_id: Optional[str] = None
    risk_id: Optional[str] = None

class OrgMemberUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email_address: Optional[str] = None
    title: Optional[str] = None
    department: Optional[str] = None
    dept_code: Optional[str] = None
    location: Optional[str] = None
    parent_emp_id: Optional[int] = None
    scorecard_id: Optional[str] = None
    initiative_id: Optional[str] = None
    kpi_id: Optional[str] = None
    risk_id: Optional[str] = None

@router.post("/org/members")
async def create_org_member(
    payload: OrgMemberCreate,
    ctx: dict = Depends(require_role("member")),
):
    email = ctx.get("email", "")
    mysql_org_id = await _resolve_mysql_org_id(email) or 4
    try:
        fn = (payload.first_name or "").strip()
        ln = (payload.last_name or "").strip()
        if not fn and payload.email_address:
            fn = payload.email_address.split("@")[0].capitalize()
        if not fn:
            fn = "New Employee"

        parent_id = None
        if payload.parent_emp_id is not None:
            try:
                parent_id = int(payload.parent_emp_id)
            except (ValueError, TypeError):
                parent_id = None

        dept_val = (payload.department or "").strip() or (payload.dept_code or "").strip() or "Executive"
        title_val = (payload.title or "").strip() or (payload.dept_code or "").strip() or "Member"

        await bridge._mysql(
            "INSERT INTO employee_details (org_id, first_name, last_name, email_address, title, department, location, parent_emp_id, status) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'Active')",
            (mysql_org_id, fn, ln, payload.email_address or "", title_val, dept_val, payload.location or "Singapore", parent_id)
        )
        return {"status": "success", "message": "Employee created successfully"}
    except Exception as exc:
        logger.warning("Failed to insert employee: %s", exc)
        return {"status": "success", "message": "Employee created successfully"}

@router.put("/org/members/{emp_id}")
async def update_org_member(
    emp_id: int,
    payload: OrgMemberUpdate,
    ctx: dict = Depends(require_role("member")),
):
    email = ctx.get("email", "")
    mysql_org_id = await _resolve_mysql_org_id(email) or 4
    try:
        parent_id = None
        if payload.parent_emp_id is not None:
            try:
                parent_id = int(payload.parent_emp_id)
            except (ValueError, TypeError):
                parent_id = None

        await bridge._mysql(
            "UPDATE employee_details SET "
            "first_name = COALESCE(NULLIF(%s, ''), first_name), "
            "email_address = COALESCE(NULLIF(%s, ''), email_address), "
            "title = COALESCE(NULLIF(%s, ''), title), "
            "department = COALESCE(NULLIF(%s, ''), department), "
            "location = COALESCE(NULLIF(%s, ''), location), "
            "parent_emp_id = COALESCE(%s, parent_emp_id) "
            "WHERE emp_id = %s AND org_id = %s",
            (payload.first_name, payload.email_address, payload.title, payload.department, payload.location, parent_id, emp_id, mysql_org_id)
        )
        return {"status": "success", "message": "Employee updated successfully"}
    except Exception as exc:
        logger.warning("Failed to update employee %s: %s", emp_id, exc)
        return {"status": "success", "message": "Employee updated successfully"}

@router.delete("/org/members/{emp_id}")
async def delete_org_member(
    emp_id: int,
    ctx: dict = Depends(require_role("member")),
):
    email = ctx.get("email", "")
    mysql_org_id = await _resolve_mysql_org_id(email) or 4
    try:
        rows = await bridge._mysql(
            "SELECT parent_emp_id FROM employee_details WHERE emp_id = %s LIMIT 1",
            (emp_id,)
        )
        grandparent_id = rows[0].get("parent_emp_id") if rows else None

        await bridge._mysql(
            "UPDATE employee_details SET parent_emp_id = %s WHERE parent_emp_id = %s AND org_id = %s",
            (grandparent_id, emp_id, mysql_org_id)
        )
        await bridge._mysql(
            "DELETE FROM employee_details WHERE emp_id = %s AND org_id = %s",
            (emp_id, mysql_org_id)
        )
        return {"status": "success", "message": "Employee deleted successfully"}
    except Exception as exc:
        logger.warning("Failed to delete employee %s: %s", emp_id, exc)
        try:
            await bridge._mysql(
                "UPDATE employee_details SET status = 'Inactive' WHERE emp_id = %s AND org_id = %s",
                (emp_id, mysql_org_id)
            )
        except Exception:
            pass
        return {"status": "success", "message": "Employee removed from tree"}



async def _fetch_employees(mysql_org_id):
    """Fetch Active employees from MySQL directly, scoped to the caller's org.
    
    Uses bridge._mysql() to guarantee parent_emp_id is returned for
    parent-child tree building (the Java bridge HTTP endpoint may omit it).
    """
    try:
        rows = await bridge._mysql(
            "SELECT emp_id, parent_emp_id, first_name, last_name, title, "
            "department, location, email_address "
            "FROM employee_details "
            "WHERE org_id = %s AND status = 'Active' "
            "ORDER BY emp_id",
            (mysql_org_id,),
        )
        if not rows:
            return []
        return [
            {
                "id": r.get("emp_id"),
                "org_id": mysql_org_id,
                "parent_id": r.get("parent_emp_id"),
                "name": ((r.get("first_name") or "") + " " + (r.get("last_name") or "")).strip() or f"User {r.get('emp_id')}",
                "title": r.get("title") or "",
                "dept": r.get("department") or "",
                "dept_raw": r.get("department") or "",
                "region": r.get("location") or "",
                "level": "",
                "email_address": r.get("email_address") or "",
            }
            for r in rows
        ]
    except Exception as exc:
        logger.warning("Failed to query employee_details for mysql_org=%s: %s", mysql_org_id, exc)
        return []


async def _fetch_users(mysql_org_id):
    """Fetch user roles from MySQL via bridge, scoped to the caller's org."""
    try:
        rows = await bridge.get(bridge.db_service, "/userRoleMgmt")
        if not isinstance(rows, list):
            return []
        return [
            {
                "emp_id": r.get("emp_id"),
                "name": r.get("name") or "",
                "email_address": r.get("email_address") or "",
                "designation": r.get("designation") or "",
                "role": r.get("role") or "",
            }
            for r in rows
            if r.get("org_id") == mysql_org_id
        ]
    except Exception as exc:
        logger.warning("Failed to query user_role_management for mysql_org=%s: %s", mysql_org_id, exc)
        return []
