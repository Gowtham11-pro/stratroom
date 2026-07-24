"""Shared utilities for routers — user resolution, input sanitization."""
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("stratroom.utils")


async def resolve_user(db: AsyncSession, email: str) -> tuple[int | None, int | None]:
    """Resolve JWT email to (user_id, org_id). Returns (None, None) if not found.

    Used by routers that need to map authenticated user to database IDs.
    """
    result = await db.execute(
        text("SELECT id, org_id FROM users WHERE email = :email"),
        {"email": email},
    )
    row = result.first()
    if row:
        return row[0], row[1]
    return None, None


async def resolve_user_full(db: AsyncSession, email: str) -> dict | None:
    """Resolve JWT email to full user context dict. Returns None if not found.

    Returns dict with keys: user_id, org_id, role, full_name, email.
    """
    result = await db.execute(
        text("SELECT id, org_id, role, full_name, email FROM users WHERE email = :email"),
        {"email": email},
    )
    row = result.first()
    if row:
        return {
            "user_id": row[0],
            "org_id": row[1],
            "role": row[2],
            "full_name": row[3],
            "email": row[4],
        }
    return None


async def resolve_employee(db: AsyncSession, email: str) -> dict | None:
    """Resolve JWT email to enterprise employee details.

    Joins users -> employee_details via employee_id FK or email match.
    Returns dict with employee context or None if not linked.
    """
    result = await db.execute(
        text(
            "SELECT ed.emp_id, ed.first_name, ed.last_name, ed.title, "
            "ed.department, ed.location, ed.email_address, ed.status, "
            "ed.dept_id, ed.parent_emp_id "
            "FROM employee_details ed "
            "JOIN users u ON (u.employee_id = ed.emp_id OR "
            "    (u.employee_id IS NULL AND LOWER(u.email) = LOWER(ed.email_address) "
            "     AND ed.org_id = u.org_id)) "
            "WHERE LOWER(u.email) = :email "
            "AND (ed.status IS NULL OR ed.status NOT IN ('InActive', 'Inactive')) "
            "LIMIT 1"
        ),
        {"email": email},
    )
    row = result.mappings().first()
    if row:
        fn = (row.get("first_name") or "").strip()
        ln = (row.get("last_name") or "").strip()
        return {
            "emp_id": row["emp_id"],
            "full_name": f"{fn} {ln}".strip() or None,
            "title": row["title"],
            "department": row["department"],
            "location": row["location"],
            "email_address": row["email_address"],
            "status": row["status"],
            "dept_id": row["dept_id"],
            "parent_emp_id": row["parent_emp_id"],
        }
    return None


async def resolve_enterprise_role(db: AsyncSession, email: str) -> dict | None:
    """Resolve JWT email to enterprise role from user_role_management.

    Returns dict with designation, role, login_status or None.
    """
    result = await db.execute(
        text(
            "SELECT urm.emp_id, urm.designation, urm.role, urm.login_status, "
            "urm.department, urm.location, urm.status "
            "FROM user_role_management urm "
            "JOIN users u ON (LOWER(u.email) = LOWER(urm.email_address)) "
            "WHERE LOWER(u.email) = :email "
            "AND (urm.status IS NULL OR urm.status NOT IN ('InActive', 'Inactive')) "
            "LIMIT 1"
        ),
        {"email": email},
    )
    row = result.mappings().first()
    if row:
        return {
            "emp_id": row["emp_id"],
            "designation": row["designation"],
            "role": row["role"],
            "login_status": row["login_status"],
            "department": row["department"],
            "location": row["location"],
            "status": row["status"],
        }
    return None


async def resolve_full_identity(db: AsyncSession, email: str) -> dict | None:
    """Resolve JWT email to complete identity context.

    Combines application user data, enterprise employee details, and enterprise
    role into a single identity dict. Returns None if user not found.
    """
    user = await resolve_user_full(db, email)
    if not user:
        return None

    employee = await resolve_employee(db, email)
    ent_role = await resolve_enterprise_role(db, email)

    return {
        "user_id": user["user_id"],
        "org_id": user["org_id"],
        "email": user["email"],
        "full_name": user["full_name"],
        "app_role": user["role"],
        "employee": employee,
        "enterprise_role": ent_role,
        "designation": (
            (ent_role.get("designation") if ent_role else None)
            or (employee.get("title") if employee else None)
            or user["role"]
        ),
        "department": (
            (ent_role.get("department") if ent_role else None)
            or (employee.get("department") if employee else None)
        ),
        "location": (
            (ent_role.get("location") if ent_role else None)
            or (employee.get("location") if employee else None)
        ),
    }
