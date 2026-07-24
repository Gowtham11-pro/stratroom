import logging
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import require_role

logger = logging.getLogger("stratroom.org")

router = APIRouter(tags=["org"])

# Map MySQL department names to frontend dept keys
DEPT_MAP = {
    'ceo': 'exec', 'coo': 'exec', 'board': 'exec',
    'technology': 'tech', 'tech': 'tech', 'infrastructure': 'tech',
    'pmo': 'tech', 'inf': 'tech', 'cto': 'tech',
    'risk': 'risk', 'risk & compliance': 'risk', 'compliance': 'risk', 'audit': 'risk', 'security': 'risk',
    'finance': 'finance', 'accounting': 'finance', 'budget': 'finance', 'cfo': 'finance',
    'sales': 'ops', 'marketing': 'ops', 'operations': 'ops', 'supply chain': 'ops', 'cso': 'ops',
    'hr': 'hr', 'human resources': 'hr', 'people': 'hr', 'talent': 'hr',
    'legal': 'legal', 'strategy': 'legal', 'general counsel': 'legal',
}


def _map_dept(dept_name):
    if not dept_name:
        return 'exec'
    key = dept_name.strip().lower()
    return DEPT_MAP.get(key, 'exec')


def _build_tree(members, emp_lookup, struct_lookup):
    """Build a hierarchical tree from org_structure_details."""
    by_emp_id = {}
    roots = []

    # Only include employees that have a structure entry
    for m in members:
        emp_id = m['emp_id']
        if emp_id not in struct_lookup:
            continue
        node = {
            'id': str(emp_id),
            'emp_id': emp_id,
            'name': m['full_name'] or f"User {emp_id}",
            'title': m.get('title') or '',
            'dept': _map_dept(m.get('department')),
            'region': '',
            'level': '',
            'headcount': 1,
            'children': [],
            'user_id': None,
            'email': m.get('email_address'),
            'role': None,
        }
        by_emp_id[emp_id] = node

    # Build parent-child from org_structure_details
    for emp_id, node in by_emp_id.items():
        struct = struct_lookup.get(emp_id)
        if struct:
            parent_id = struct.get('parent_id')
            if parent_id and parent_id in by_emp_id:
                by_emp_id[parent_id]['children'].append(node)
            else:
                roots.append(node)
        else:
            roots.append(node)

    return roots


@router.get("/org")
async def get_org_full(
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("member")),
):
    user_id = ctx["user_id"]
    org_id = ctx["org_id"]

    # ── 1. Fetch employee details for this org ──
    try:
        result = await db.execute(
            text(
                "SELECT emp_id, org_id, dept_id, first_name, last_name, title, "
                "parent_emp_id, email_address, department, location, status "
                "FROM employee_details WHERE org_id = :oid AND (status IS NULL OR status != 'InActive')"
            ),
            {"oid": org_id},
        )
        emp_rows = [dict(r) for r in result.mappings().all()]
        for e in emp_rows:
            fn = (e.get('first_name') or '').strip()
            ln = (e.get('last_name') or '').strip()
            e['full_name'] = f"{fn} {ln}".strip() or f"User {e['emp_id']}"
    except Exception as exc:
        logger.warning("Failed to query employee_details for org=%s: %s", org_id, exc)
        emp_rows = []

    # ── 2. Fetch org structure (reporting hierarchy) - scoped to org employees ──
    try:
        result = await db.execute(
            text(
                'WITH org_employees AS ('
                '  SELECT emp_id FROM employee_details '
                '  WHERE org_id = :oid AND (status IS NULL OR status != \'InActive\')'
                '), '
                'latest_struct AS ('
                '  SELECT DISTINCT ON (empid) empid, parent_id, status '
                '  FROM org_structure_details '
                "  WHERE status = 'Active' AND empid IN (SELECT emp_id FROM org_employees) "
                '  ORDER BY empid, start_date DESC'
                ') '
                'SELECT empid, parent_id FROM latest_struct'
            ),
            {"oid": org_id},
        )
        struct_rows = [dict(r) for r in result.mappings().all()]
        struct_lookup = {r['empid']: r for r in struct_rows}
    except Exception as exc:
        logger.warning("Failed to query org_structure_details: %s", exc)
        struct_lookup = {}

    # ── 3. Fetch user role management for user info ──
    try:
        result = await db.execute(
            text(
                "SELECT emp_id, name, email_address, designation, role, department, location, status "
                "FROM user_role_management WHERE org_id = :oid AND (status IS NULL OR status != 'InActive')"
            ),
            {"oid": org_id},
        )
        user_rows = [dict(r) for r in result.mappings().all()]
    except Exception as exc:
        logger.warning("Failed to query user_role_management for org=%s: %s", org_id, exc)
        user_rows = []

    # Build user lookup by emp_id
    user_by_emp = {r['emp_id']: r for r in user_rows}

    # ── 4. Compute summary stats (needed before tree for virtual root) ──
    total_members = len(emp_rows)
    total_users = len(user_rows)
    total_headcount = total_members

    depts = defaultdict(lambda: {"count": 0, "members": 0})
    regions = defaultdict(int)
    levels = defaultdict(int)

    for e in emp_rows:
        dept_key = _map_dept(e.get('department'))
        depts[dept_key]["count"] += 1
        depts[dept_key]["members"] += 1

    for u in user_rows:
        loc = u.get('location') or ''
        if loc:
            regions[loc] += 1

    # ── 5. Build hierarchy tree from employee_details + org_structure_details ──
    tree_roots = _build_tree(emp_rows, user_by_emp, struct_lookup)

    # Ensure single root node (frontend expects one root)
    if len(tree_roots) == 0:
        tree = {"id": "0", "name": "Organization", "title": "", "dept": "exec", "region": "", "level": "", "headcount": total_headcount, "children": [], "user_id": None, "email": None, "role": None}
    elif len(tree_roots) == 1:
        tree = tree_roots[0]
    else:
        tree = {
            "id": "0", "name": "Organization", "title": "Top Level",
            "dept": "exec", "region": "", "level": "", "headcount": total_headcount,
            "children": tree_roots, "user_id": None, "email": None, "role": None,
        }

    # ── 6. Attach user_id and role to tree nodes ──
    try:
        result = await db.execute(
            text("SELECT id as user_id, full_name, email, role FROM users WHERE org_id = :oid"),
            {"oid": org_id},
        )
        app_users = [dict(r) for r in result.mappings().all()]
    except Exception:
        app_users = []

    userByEmail = {u['email'].lower(): u for u in app_users if u.get('email')}

    def attach_user_info(node):
        email = (node.get('email') or '').lower().strip()
        matched = userByEmail.get(email)
        if matched:
            node['user_id'] = matched['user_id']
            node['role'] = matched.get('role')
        emp_id = node.get('emp_id')
        if emp_id and emp_id in user_by_emp:
            urm = user_by_emp[emp_id]
            if not node.get('role') and urm.get('role'):
                node['role'] = urm['role']
            if not node.get('title') and urm.get('designation'):
                node['title'] = urm['designation']
            if urm.get('location'):
                node['region'] = urm['location']
        for child in node.get('children', []):
            attach_user_info(child)

    if isinstance(tree, dict):
        attach_user_info(tree)
    elif isinstance(tree, list):
        for root in tree:
            attach_user_info(root)

    logger.info(
        "Org loaded: %d employees, %d users [org=%s]",
        total_members, total_users, org_id,
    )

    return {
        "tree": tree,
        "users": [
            {
                "user_id": r.get("emp_id"),
                "full_name": r.get("name") or "",
                "email": r.get("email_address") or "",
                "role": r.get("designation") or r.get("role") or "user",
                "created_at": r.get("created_date"),
            }
            for r in user_rows
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
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("member")),
):
    user_id = ctx["user_id"]
    org_id = ctx["org_id"]

    try:
        result = await db.execute(
            text(
                "SELECT emp_id, org_id, dept_id, first_name, last_name, title, "
                "parent_emp_id, email_address, department, location, status "
                "FROM employee_details WHERE org_id = :oid AND (status IS NULL OR status != 'InActive')"
            ),
            {"oid": org_id},
        )
        emp_rows = [dict(r) for r in result.mappings().all()]
        for e in emp_rows:
            fn = (e.get('first_name') or '').strip()
            ln = (e.get('last_name') or '').strip()
            e['full_name'] = f"{fn} {ln}".strip() or f"User {e['emp_id']}"
    except Exception:
        return {"tree": []}

    try:
        result = await db.execute(
            text(
                'WITH org_employees AS ('
                '  SELECT emp_id FROM employee_details '
                '  WHERE org_id = :oid AND (status IS NULL OR status != \'InActive\')'
                '), '
                'latest_struct AS ('
                '  SELECT DISTINCT ON (empid) empid, parent_id '
                '  FROM org_structure_details '
                "  WHERE status = 'Active' AND empid IN (SELECT emp_id FROM org_employees) "
                '  ORDER BY empid, start_date DESC'
                ') '
                'SELECT empid, parent_id FROM latest_struct'
            ),
            {"oid": org_id},
        )
        struct_rows = [dict(r) for r in result.mappings().all()]
        struct_lookup = {r['empid']: r for r in struct_rows}
    except Exception:
        struct_lookup = {}

    tree_roots = _build_tree(emp_rows, {}, struct_lookup)
    return {"tree": tree_roots[0] if len(tree_roots) == 1 else tree_roots}


@router.get("/org/users")
async def list_org_users(
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("member")),
):
    user_id = ctx["user_id"]
    org_id = ctx["org_id"]

    try:
        result = await db.execute(
            text(
                "SELECT emp_id, name, email_address, designation, role, department, location, status "
                "FROM user_role_management WHERE org_id = :oid"
            ),
            {"oid": org_id},
        )
        rows = [dict(r) for r in result.mappings().all()]
        users = [
            {
                "user_id": r.get("emp_id"),
                "full_name": r.get("name") or "",
                "email": r.get("email_address") or "",
                "role": r.get("designation") or r.get("role") or "user",
                "created_at": r.get("created_date"),
            }
            for r in rows
        ]
    except Exception as exc:
        logger.warning("Failed to query users for org=%s: %s", org_id, exc)
        users = []

    return {"users": users}
