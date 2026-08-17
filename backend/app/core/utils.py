import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.java_bridge import bridge

logger = logging.getLogger("stratroom.utils")


async def resolve_user(email: str) -> tuple[int | None, int | None]:
    try:
        rows = await bridge.get(bridge.db_service, f"/findByUser", params={"email": email})
        if isinstance(rows, list) and rows:
            return rows[0].get("emp_id"), rows[0].get("org_id", 1)
    except Exception:
        logger.debug("MySQL resolve_user failed for %s", email)
    return None, None


async def resolve_user_full(email: str, db: AsyncSession | None = None) -> dict | None:
    try:
        rows = await bridge.get(bridge.db_service, f"/findByUser", params={"email": email})
        if isinstance(rows, list) and rows:
            row = rows[0]
            return {
                "user_id": row.get("emp_id"),
                "org_id": row.get("org_id", 1),
                "role": row.get("title", "member"),
                "full_name": f"{row.get('first_name','') or ''} {row.get('last_name','') or ''}".strip(),
                "email": row.get("email_address", email),
            }
    except Exception:
        logger.debug("MySQL resolve_user_full failed for %s", email)

    try:
        rows = await bridge._mysql(
            "SELECT id, org_id, role, full_name, email FROM users WHERE LOWER(email) = %s",
            (email.lower(),),
        )
        if rows:
            row = rows[0]
            return {
                "user_id": row["id"],
                "org_id": row["org_id"],
                "role": row["role"],
                "full_name": row["full_name"] or "",
                "email": row["email"],
            }
    except Exception:
        logger.debug("MySQL users fallback failed for %s", email)
    return None


async def resolve_employee(email: str, db: AsyncSession | None = None) -> dict | None:
    try:
        rows = await bridge.get(bridge.db_service, "/employeeDetailsList")
        if isinstance(rows, list):
            for emp in rows:
                ea = emp.get("email_address", "")
                if ea and ea.lower() == email.lower():
                    fn = (emp.get("first_name") or "").strip()
                    ln = (emp.get("last_name") or "").strip()
                    return {
                        "emp_id": emp.get("emp_id"),
                        "full_name": f"{fn} {ln}".strip() or None,
                        "title": emp.get("title"),
                        "department": emp.get("department"),
                        "location": emp.get("location"),
                        "email_address": emp.get("email_address"),
                        "status": emp.get("status"),
                        "dept_id": emp.get("dept_id"),
                        "parent_emp_id": emp.get("parent_emp_id"),
                    }
    except Exception:
        logger.debug("MySQL resolve_employee failed for %s", email)

    if db:
        try:
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
        except Exception:
            logger.debug("PostgreSQL resolve_employee failed for %s", email)
    return None


async def resolve_enterprise_role(email: str, db: AsyncSession | None = None) -> dict | None:
    try:
        data = await bridge.get(bridge.user_service, "/findByUser", params={"email": email})
        if isinstance(data, dict) and data.get("empId"):
            return {
                "emp_id": data.get("empId"),
                "designation": data.get("designation", ""),
                "role": data.get("role", ""),
                "login_status": data.get("loginStatus", "Active"),
                "department": data.get("department"),
                "location": data.get("location"),
                "status": data.get("status", "Active"),
            }
    except Exception:
        logger.debug("Java resolve_enterprise_role failed for %s", email)

    try:
        rows = await bridge._mysql(
            "SELECT emp_id, designation, role, login_status, department, location, status "
            "FROM user_role_management "
            "WHERE LOWER(email_address) = LOWER(%s) "
            "AND (status IS NULL OR status NOT IN ('InActive', 'Inactive')) "
            "LIMIT 1",
            (email,),
        )
        if rows and rows[0]:
            r = rows[0]
            return {
                "emp_id": r.get("emp_id"),
                "designation": r.get("designation") or "",
                "role": r.get("role") or "",
                "login_status": r.get("login_status") or "Active",
                "department": r.get("department"),
                "location": r.get("location"),
                "status": r.get("status") or "Active",
            }
    except Exception:
        logger.debug("MySQL direct resolve_enterprise_role failed for %s", email)

    if db:
        try:
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
        except Exception:
            logger.debug("PostgreSQL resolve_enterprise_role failed for %s", email)
    return None


async def resolve_full_identity(email: str, db: AsyncSession | None = None) -> dict | None:
    """Resolve full user identity from email.

    Fast path: single MySQL JOIN query combining employee_details +
    user_role_management in one round-trip (replaces 3 sequential calls).
    Falls back to the original multi-call chain if the fast path fails.
    """
    # ── Fast path: single JOIN query ──
    try:
        rows = await bridge._mysql(
            "SELECT ed.emp_id, ed.org_id, ed.first_name, ed.last_name, "
            "ed.title, ed.department, ed.location, ed.email_address, "
            "ed.status, ed.dept_id, ed.parent_emp_id, "
            "urm.designation, urm.role AS urm_role, "
            "urm.login_status, urm.department AS urm_department, "
            "urm.location AS urm_location, urm.status AS urm_status "
            "FROM employee_details ed "
            "LEFT JOIN user_role_management urm "
            "  ON ed.emp_id = urm.emp_id AND ed.org_id = urm.org_id "
            "WHERE LOWER(ed.email_address) = LOWER(%s) "
            "AND (ed.status IS NULL OR ed.status NOT IN ('InActive', 'Inactive')) "
            "LIMIT 1",
            (email,),
        )
        if rows and rows[0]:
            r = rows[0]
            fn = (r.get("first_name") or "").strip()
            ln = (r.get("last_name") or "").strip()
            full_name = f"{fn} {ln}".strip()

            employee = {
                "emp_id": r.get("emp_id"),
                "full_name": full_name or None,
                "title": r.get("title"),
                "department": r.get("department"),
                "location": r.get("location"),
                "email_address": r.get("email_address"),
                "status": r.get("status"),
                "dept_id": r.get("dept_id"),
                "parent_emp_id": r.get("parent_emp_id"),
            }

            ent_role = None
            if r.get("designation") or r.get("urm_role"):
                ent_role = {
                    "emp_id": r.get("emp_id"),
                    "designation": r.get("designation") or "",
                    "role": r.get("urm_role") or "",
                    "login_status": r.get("login_status") or "Active",
                    "department": r.get("urm_department"),
                    "location": r.get("urm_location"),
                    "status": r.get("urm_status") or "Active",
                }

            app_role = r.get("title") or "member"

            return {
                "user_id": r.get("emp_id"),
                "org_id": r.get("org_id"),
                "email": r.get("email_address") or email,
                "full_name": full_name,
                "app_role": app_role,
                "employee": employee,
                "enterprise_role": ent_role,
                "designation": (
                    (ent_role.get("designation") if ent_role else None)
                    or r.get("title")
                    or app_role
                ),
                "department": (
                    (ent_role.get("department") if ent_role else None)
                    or r.get("department")
                ),
                "location": (
                    (ent_role.get("location") if ent_role else None)
                    or r.get("location")
                ),
            }
    except Exception:
        logger.debug("Fast-path identity resolution failed for %s, falling back", email)

    # ── Fallback: original 3-call chain ──
    user = await resolve_user_full(email, db)
    if not user:
        return None

    employee = await resolve_employee(email, db)
    ent_role = await resolve_enterprise_role(email, db)

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

