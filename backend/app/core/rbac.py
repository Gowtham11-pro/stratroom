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

logger = logging.getLogger("stratroom.rbac")

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
