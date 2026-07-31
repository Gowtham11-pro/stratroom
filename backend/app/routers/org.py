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
    return DEPT_SLUG_MAP.get(key, 'exec')


async def _resolve_mysql_org_id(email: str) -> int | None:
    """Resolve the caller's MySQL org_id from their email.

    Returns None if the user has no MySQL employee record (e.g. PG-only
    admin accounts). Same pattern as query_risks/query_tasks.
    """
    if not email:
        return None
    try:
        rows = await bridge._mysql(
            "SELECT org_id FROM employee_details "
            "WHERE LOWER(email_address) = LOWER(%s) LIMIT 1",
            (email,),
        )
        if rows:
            return rows[0].get("org_id")
    except Exception:
        logger.debug("Failed to resolve MySQL org_id for %s", email)
    return None


@router.get("/org")
async def get_org_full(
    ctx: dict = Depends(require_role("member")),
):
    email = ctx.get("email", "")
    mysql_org_id = await _resolve_mysql_org_id(email)

    # Fail-safe: no MySQL employee record -> empty result
    # (e.g. admin@stratroom.com who has pg-only org_id=1)
    if mysql_org_id is None:
        return {
            "tree": {"id": "0", "name": "Organization", "title": "", "dept": "exec",
                     "region": "", "level": "", "headcount": 0,
                     "children": [], "user_id": None, "email": None, "role": None},
            "users": [],
            "summary": {
                "total_members": 0, "total_users": 0, "total_headcount": 0,
                "departments": {}, "regions": {}, "levels": {},
            },
        }

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
        node = {
            "id": node_id,
            "name": (m.get("name") or "").strip(),
            "title": m.get("title") or "",
            "dept": _to_slug(m.get("dept")),
            "region": m.get("region") or "",
            "level": m.get("level") or "",
            "headcount": 1,
            "children": [],
            "user_id": None,
            "email": None,
            "role": None,
        }
        by_id[node_id] = node

    roots = []
    for m in members:
        node = by_id[str(m["id"])]
        parent_id = m.get("parent_id")
        if parent_id and str(parent_id) in by_id:
            by_id[str(parent_id)]["children"].append(node)
        else:
            roots.append(node)

    if len(roots) == 0:
        tree = {"id": "0", "name": "Organization", "title": "", "dept": "exec",
                "region": "", "level": "", "headcount": total_headcount,
                "children": [], "user_id": None, "email": None, "role": None}
    elif len(roots) == 1:
        tree = roots[0]
    else:
        tree = {
            "id": "0", "name": "Organization", "title": "Top Level",
            "dept": "exec", "region": "", "level": "",
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

    if mysql_org_id is None:
        return {"tree": {"id": "0", "name": "Organization", "title": "", "dept": "exec",
                         "region": "", "level": "", "headcount": 0, "children": []}}

    members = await _fetch_employees(mysql_org_id)
    total_headcount = len(members)

    by_id = {}
    for m in members:
        node_id = str(m["id"])
        node = {
            "id": node_id, "name": (m.get("name") or "").strip(),
            "title": m.get("title") or "", "dept": _to_slug(m.get("dept")),
            "region": m.get("region") or "", "level": m.get("level") or "",
            "headcount": 1, "children": [],
        }
        by_id[node_id] = node

    roots = []
    for m in members:
        node = by_id[str(m["id"])]
        parent_id = m.get("parent_id")
        if parent_id and str(parent_id) in by_id:
            by_id[str(parent_id)]["children"].append(node)
        else:
            roots.append(node)

    # Apply same virtual-root fallback as /org to ensure frontend always gets a single node
    if len(roots) == 0:
        tree = {"id": "0", "name": "Organization", "title": "", "dept": "exec",
                "region": "", "level": "", "headcount": total_headcount,
                "children": []}
    elif len(roots) == 1:
        tree = roots[0]
    else:
        tree = {
            "id": "0", "name": "Organization", "title": "Top Level",
            "dept": "exec", "region": "", "level": "",
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


async def _fetch_employees(mysql_org_id):
    """Fetch Active employees from MySQL via bridge, scoped to the caller's org."""
    try:
        rows = await bridge.get(bridge.db_service, "/employeeDetailsList")
        if not isinstance(rows, list):
            return []
        return [
            {
                "id": r.get("emp_id"),
                "org_id": r.get("org_id"),
                "parent_id": r.get("parent_emp_id"),
                "name": ((r.get("first_name") or "") + " " + (r.get("last_name") or "")).strip() or f"User {r.get('emp_id')}",
                "title": r.get("title") or "",
                "dept": r.get("department") or "",
                "region": r.get("location") or "",
                "level": "",
                "email_address": r.get("email_address") or "",
            }
            for r in rows
            if r.get("org_id") == mysql_org_id and r.get("status") == "Active"
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
