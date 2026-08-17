"""Role-Based Access Control (RBAC) — role hierarchy and permission checks.

Role hierarchy (highest to lowest):
    admin   → Can view and modify ALL records within their organization.
    manager → Can view records for their department. Can modify own records.
    member  → Can view and modify ONLY records assigned to them.

Enterprise role mapping (from user_role_management.designation or users.role):
    CEO, COO, CFO, CTO, CRO, CISO, CSO, CMO, President, Director,
    Super User, Admin → admin
    Manager, Lead, Head, Owner → manager
    Everything else   → member
"""
import logging

from collections import defaultdict

from fastapi import HTTPException

from app.services.java_bridge import bridge

logger = logging.getLogger("stratroom.rbac")

# ── Access-denied response messages (Phase 2 spec) ──
MSG_TASK_NOT_ASSIGNED = "This task is not assigned to you; it is assigned to a different user."
MSG_ACCESS_RESTRICTED = "You don't have permission to access this data"

# Numeric levels for hierarchy comparison.
# Higher number = more privilege.
ROLE_LEVELS: dict[str, int] = {
    "admin": 100,
    "manager": 50,
    "member": 10,
}

# Enterprise designation → application RBAC role mapping.
# Keys are lowered for case-insensitive matching.
ADMIN_DESIGNATIONS: frozenset[str] = frozenset({
    "ceo", "coo", "cfo", "cto", "cro", "ciso", "cso", "cmo",
    "president", "director", "super user", "superuser", "admin",
    "chief financial officer", "chief technology officer",
    "chief risk officer", "chief information security officer",
    "chief strategy officer", "chief marketing officer",
    "chief operating officer", "chief executive officer",
})

MANAGER_DESIGNATIONS: frozenset[str] = frozenset({
    "manager", "lead", "head", "owner", "vice president", "vp",
    "budget planner", "budget planners", "accounting",
    "techadmin",
})


def normalize_role(role: str | None) -> str:
    """Map any role string (app role, enterprise designation, etc.) to a normalized RBAC role.

    Returns 'admin', 'manager', or 'member'.
    """
    if not role:
        return "member"

    normalized = role.strip().lower()

    # Direct match against known app roles
    if normalized in ROLE_LEVELS:
        return normalized

    # Check enterprise designation mapping
    if normalized in ADMIN_DESIGNATIONS:
        return "admin"
    if normalized in MANAGER_DESIGNATIONS:
        return "manager"

    return "member"


def get_role_level(role: str | None) -> int:
    """Get the numeric privilege level for a role string."""
    normalized = normalize_role(role)
    return ROLE_LEVELS.get(normalized, ROLE_LEVELS["member"])


def has_permission(user_role: str | None, required_role: str) -> bool:
    """Check if user_role has at least the privilege of required_role."""
    return get_role_level(user_role) >= get_role_level(required_role)


def resolve_rbac_role(identity: dict) -> str:
    """Determine the effective RBAC role from a full identity dict.

    Checks app_role, designation, and enterprise_role in priority order.
    Returns the highest-privilege role found.
    """
    candidates: list[str | None] = []

    # App role (users.role) — primary
    candidates.append(identity.get("app_role"))

    # Enterprise designation (user_role_management.designation)
    candidates.append(identity.get("designation"))

    # Enterprise role (user_role_management.role)
    ent_role = identity.get("enterprise_role")
    if isinstance(ent_role, dict):
        candidates.append(ent_role.get("role"))
    elif isinstance(ent_role, str):
        candidates.append(ent_role)

    # Return the highest-privilege role among all candidates
    best_level = -1
    best_role = "member"
    for candidate in candidates:
        level = get_role_level(candidate)
        if level > best_level:
            best_level = level
            best_role = normalize_role(candidate)

    return best_role


def can_view_all(identity: dict) -> bool:
    """Check if the user can view all records in their organization (bypass ownership filter)."""
    role = resolve_rbac_role(identity)
    return has_permission(role, "admin")


def can_view_department(identity: dict) -> bool:
    """Check if the user can view all records in their department."""
    role = resolve_rbac_role(identity)
    return has_permission(role, "manager")


# ────────────────────────────────────────────────────────────────
# Phase 2: Hierarchical (parent_emp_id) + ownership access control
# ────────────────────────────────────────────────────────────────

def _as_int(value, default=None):
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def effective_emp_id(identity: dict) -> int | None:
    """Resolve the caller's own employee id (emp_id) from the identity dict.

    Prefers employee_details.emp_id; falls back to users.id (user_id).
    """
    emp = identity.get("employee")
    if isinstance(emp, dict):
        eid = _as_int(emp.get("emp_id"))
        if eid:
            return eid
    return _as_int(identity.get("emp_id")) or _as_int(identity.get("user_id"))


async def get_report_tree() -> dict[int, list[int]]:
    """Build {manager_emp_id: [direct_report_emp_ids]} from employee_details.

    Uses parent_emp_id as the manager link. Empty on failure (deny-by-default).
    """
    tree: dict[int, list[int]] = defaultdict(list)
    try:
        rows = await bridge._mysql(
            "SELECT emp_id, org_id, parent_emp_id FROM employee_details"
        )
    except Exception:
        logger.warning("Hierarchy lookup failed; defaulting to empty report tree")
        return tree
    for r in rows or []:
        emp_id = _as_int(r.get("emp_id"))
        parent = _as_int(r.get("parent_emp_id"))
        if emp_id and parent:
            tree[parent].append(emp_id)
    return tree


async def get_direct_and_indirect_reports(manager_emp_id: int) -> set[int]:
    """Return all emp_ids that roll up to the given manager (recursive).

    Recursively descends parent -> child via parent_emp_id.
    """
    tree = await get_report_tree()
    result: set[int] = set()
    stack = [manager_emp_id]
    visited_managers: set[int] = set()
    while stack:
        current = stack.pop()
        if current in visited_managers:
            continue
        visited_managers.add(current)
        for child in tree.get(current, []):
            if child not in result:
                result.add(child)
                stack.append(child)
    return result


async def get_department_emp_ids(org_id: int | None, dept_id: int | None) -> set[int]:
    """Emp_ids sharing the caller's department (dept_id)."""
    if not dept_id:
        return set()
    dept_set: set[int] = set()
    try:
        rows = await bridge._mysql(
            "SELECT emp_id FROM employee_details WHERE dept_id = %s AND org_id = %s",
            (dept_id, org_id or 1),
        )
    except Exception:
        logger.warning("Department lookup failed; empty department scope")
        return dept_set
    for r in rows or []:
        eid = _as_int(r.get("emp_id"))
        if eid:
            dept_set.add(eid)
    return dept_set


async def get_visible_emp_ids(identity: dict) -> set[int] | None:
    """Return the set of emp_ids the caller may view, or None = "all".

    - admin   -> all (None)
    - manager -> self + department members + all (direct & indirect) reports
    - member  -> self only
    """
    role = resolve_rbac_role(identity)
    own = effective_emp_id(identity)
    if role == "admin":
        return None
    if own is None:
        # Cannot establish ownership → deny (degrade safely).
        return set()
    visible: set[int] = {own}
    if role == "manager":
        try:
            visible |= await get_direct_and_indirect_reports(own)
            dept_id = _as_int((identity.get("employee") or {}).get("dept_id"))
            visible |= await get_department_emp_ids(identity.get("org_id"), dept_id)
        except Exception:
            logger.warning("Manager scope resolution failed", exc_info=True)
    return visible


# Backward-compatible alias for tests/callers expecting the old name.
async def get_visible_employee_ids(identity: dict) -> set[int] | None:
    return await get_visible_emp_ids(identity)


def _record_owner_emp_id(record: dict) -> int | None:
    """Normalize a data row's owner to an emp_id (or None if unresolved).

    Recognizes assigned_user_id/assignedUserId/owner_id/user_id/emp_id and
    the owner/ownerName fields stored as emp_id or an email, and the nested
    task_value JSON blob used by the MySQL bridge.
    """
    # primary numeric keys
    for key in ("assigned_user_id", "assignedUserId", "user_id", "emp_id"):
        val = _as_int(record.get(key))
        if val:
            return val

    # nested task_value JSON
    tv = record.get("task_value")
    if isinstance(tv, dict):
        nested = _as_int(tv.get("assignedUserId"))
        if nested:
            return nested

    # owner fields (may be emp_id or email) / owner_id
    owner_id = _as_int(record.get("owner_id"))
    if owner_id:
        return owner_id
    owner = record.get("owner")
    if isinstance(owner, (int, float)):
        return int(owner)
    owner_s = str(owner or "").strip()
    if owner_s.isdigit():
        return int(owner_s)
    if "@" in owner_s:
        # email owner is not resolvable offline -> fall back to caller's id
        pass
    return None


def is_self_record(identity: dict, owner_emp_id: int | None) -> bool:
    me = effective_emp_id(identity)
    return owner_emp_id is not None and me is not None and owner_emp_id == me


async def can_view_record(identity: dict, record: dict) -> bool:
    """True if the caller may view this single record.

    Enforces task ownership + parent-child hierarchy:
      - member: own records only
      - manager: own + department + subordinates
      - admin: everything
    """
    owner = _record_owner_emp_id(record)
    if owner is not None and is_self_record(identity, owner):
        return True
    visible = await get_visible_emp_ids(identity)
    if visible is None:  # admin
        return True
    return owner is not None and owner in visible


async def can_view_owner(identity: dict, owner_emp_id: int | None) -> bool:
    """True if the caller may view a record owned by the given emp_id."""
    if owner_emp_id is None:
        return True
    visible = await get_visible_emp_ids(identity)
    if visible is None:
        return True
    return owner_emp_id in visible


async def filter_visible_rows(identity: dict, rows: list[dict]) -> list[dict]:
    """Reduce a fetched row list to only the rows the caller may view."""
    visible = await get_visible_emp_ids(identity)
    if visible is None:
        return rows
    filtered = []
    for r in rows:
        if is_self_record(identity, _record_owner_emp_id(r)):
            filtered.append(r)
            continue
        owner = _record_owner_emp_id(r)
        if owner is not None and owner in visible:
            filtered.append(r)
    return filtered


def raise_access_denied():
    raise HTTPException(status_code=403, detail=MSG_ACCESS_RESTRICTED)


def raise_task_not_assigned():
    raise HTTPException(status_code=403, detail=MSG_TASK_NOT_ASSIGNED)


async def enforce_task_access(identity: dict, owner_emp_id: int | None):
    """Gate a single task record by the caller's ownership + hierarchy scope.

    Raises:
      - MSG_TASK_NOT_ASSIGNED when a member queries a task owned by a
        different user (not a parent manager).
      - MSG_ACCESS_RESTRICTED when the target owner is out of the caller's
        scope (e.g. a member probing manager data, or a manager probing
        outside department/report-tree).
    """
    await _enforce_record_access(identity, owner_emp_id, use_task_message=True)


async def enforce_record_access(identity: dict, owner_emp_id: int | None):
    """Gate a non-task record (risk, scorecard, ...) by ownership/hierarchy.

    Uses the generic MSG_ACCESS_RESTRICTED message for all out-of-scope
    access, including a member probing another member's data.
    """
    await _enforce_record_access(identity, owner_emp_id, use_task_message=False)


async def _owner_is_manager(owner_emp_id: int | None) -> bool:
    """True if the record owner is a manager/admin-level employee.

    A manager is someone who either has direct reports in the hierarchy
    (appears as a parent_emp_id) or whose title/designation maps to a
    manager/admin RBAC role.
    """
    if owner_emp_id is None:
        return False
    try:
        tree = await get_report_tree()
        if tree.get(owner_emp_id):
            return True
    except Exception:
        logger.warning("report-tree check failed in _owner_is_manager", exc_info=True)
    try:
        rows = await bridge._mysql(
            "SELECT title FROM employee_details WHERE emp_id = %s LIMIT 1",
            (owner_emp_id,),
        )
        if rows:
            title = rows[0].get("title")
            if title:
                return has_permission(resolve_rbac_role({"designation": title}), "manager")
    except Exception:
        logger.warning("title lookup failed in _owner_is_manager", exc_info=True)
    return False


async def _enforce_record_access(
    identity: dict, owner_emp_id: int | None, *, use_task_message: bool
):
    me = effective_emp_id(identity)

    # Admin bypass
    if resolve_rbac_role(identity) == "admin":
        return

    if owner_emp_id is not None and me is not None and owner_emp_id == me:
        return  # own record: always allowed

    visible = await get_visible_emp_ids(identity)

    # Manager viewing report/department/self record -> allowed.
    if visible is not None:
        if owner_emp_id is not None and owner_emp_id in visible:
            return

    # Out of scope. Pick the exact denial message:
    #  - member probing a MANAGER's record  -> "You don't have permission..."
    #  - member probing a PEER member's task -> "This task is not assigned..."
    if resolve_rbac_role(identity) == "member":
        if use_task_message and not await _owner_is_manager(owner_emp_id):
            raise_task_not_assigned()
        raise_access_denied()
    raise_access_denied()


async def has_module_permission(identity: dict, module_name: str, action: str = "view") -> bool:
    """Check if the user has permission for a specific module in user_module_permissions table.

    Admin role bypasses module checks. Non-admins look up (emp_id, module_name).
    Defaults to True if no restriction row exists.
    """
    role = resolve_rbac_role(identity)
    if role == "admin":
        return True

    emp_id = effective_emp_id(identity)
    if not emp_id:
        return True

    try:
        col = "can_view" if action == "view" else ("can_edit" if action == "edit" else "can_delete")
        row = await bridge._mysql(
            f"SELECT {col} FROM user_module_permissions WHERE emp_id = %s AND module_name = %s LIMIT 1",
            (emp_id, module_name.lower()),
            one=True,
        )
        if row:
            return bool(row.get(col, 1))
    except Exception as exc:
        logger.warning("has_module_permission check failed: %s", exc)

    return True

