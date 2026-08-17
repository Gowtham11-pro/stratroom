"""Initiative (project) management tools for the AI Chat Engine.

Provides query and update functions that agents can invoke via tool calls.
All functions are async and accept a DB session + user context.
Supports RBAC: admin users see/update all initiatives, members see/update
only those they own (owner column = employee emp_id).
"""
import json
import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("stratroom.agents.initiative_tools")


def _parse_initiative_progress(progress) -> tuple[int | None, str | None, bool]:
    """Validate + clamp a progress value to 0-100. Returns (value, error, clamped)."""
    if progress is None:
        return None, "progress is required. Usage: [TOOL_CALL:update_initiative_progress:id=8,progress=80]", False
    try:
        raw = int(progress)
    except (TypeError, ValueError):
        return None, f"progress must be an integer between 0 and 100, got '{progress}'", False
    new_progress = max(0, min(100, raw))
    return new_progress, None, raw != new_progress


def _status_light(pct: int) -> str:
    """Build the statusLight CSS string consistent with the initiatives UI."""
    if pct >= 75:
        cls = "progress-bar-success"
    elif pct >= 40:
        cls = "progress-bar-warning"
    else:
        cls = "progress-bar-danger"
    return f"progress-bar {cls} width-per-{pct} rounded-pill bar_height"


def _status_indicator(pct: int) -> str:
    if pct >= 75:
        return "GREEN"
    if pct >= 40:
        return "AMBER"
    return "RED"


async def query_initiatives(
    db: AsyncSession,
    user_id: int,
    org_id: int,
    is_admin: bool = False,
    email: str | None = None,
    owner_filter: str | None = None,
    status_filter: str | None = None,
) -> dict:
    """Query initiatives with RBAC scoping.

    Admins see all initiatives (business data spans orgs); members see only
    the initiatives they own.
    """
    from app.services.java_bridge import bridge

    if is_admin:
        sql = "SELECT id, initiative_id, initiative_value, owner FROM initiatives_details ORDER BY updated_time DESC"
        params: tuple = ()
    else:
        mysql_user = None
        if email:
            rows = await bridge._mysql(
                "SELECT emp_id, org_id FROM employee_details "
                "WHERE LOWER(email_address) = LOWER(%s) LIMIT 1",
                (email,),
            )
            mysql_user = rows[0] if rows else None
        if not mysql_user:
            return {"error": "User not found in employee directory."}
        sql = (
            "SELECT id, initiative_id, initiative_value, owner "
            "FROM initiatives_details WHERE owner = %s ORDER BY updated_time DESC"
        )
        params = (mysql_user["emp_id"],)

    rows = await bridge._mysql(sql, params)

    initiatives = []
    for r in rows or []:
        iv = bridge._parse_json_col(r, "initiative_value")
        pct = iv.get("progressval", iv.get("progress", ""))
        try:
            pct_int = int(pct) if str(pct).strip() not in ("", "None") else None
        except (TypeError, ValueError):
            pct_int = None
        initiatives.append({
            "id": r.get("id"),
            "initiative_id": r.get("initiative_id"),
            "name": iv.get("name", iv.get("Name", "")),
            "description": iv.get("description", ""),
            "owner": iv.get("ownerName", r.get("owner")),
            "progress": pct_int,
            "statusIndicator": iv.get("statusIndicator", ""),
        })

    return {
        "initiatives": initiatives,
        "summary": {
            "total": len(initiatives),
            "completed": sum(1 for i in initiatives if (i["progress"] or 0) >= 100),
            "in_progress": sum(1 for i in initiatives if i["progress"] is not None and 0 < i["progress"] < 100),
            "not_started": sum(1 for i in initiatives if (i["progress"] or 0) == 0),
        },
    }


async def update_initiative_progress(
    db: AsyncSession,
    user_id: int,
    org_id: int,
    initiative_id: int,
    progress: int | str | None = None,
    is_admin: bool = False,
    email: str | None = None,
) -> dict:
    """Update an initiative's progress percentage in MySQL via the bridge.

    Writes `progressval`, `statusLight`, and `statusIndicator` inside the
    `initiative_value` JSON blob (all other keys preserved). Returns a dict
    with a human-readable confirmation string.
    """
    from app.services.java_bridge import bridge

    # 1. Validate + clamp progress to 0-100
    new_progress, err, clamped = _parse_initiative_progress(progress)
    if err:
        return {"error": err}

    # 2. Resolve MySQL identity from email
    mysql_user = None
    if email:
        rows = await bridge._mysql(
            "SELECT emp_id, org_id FROM employee_details "
            "WHERE LOWER(email_address) = LOWER(%s) LIMIT 1",
            (email,),
        )
        mysql_user = rows[0] if rows else None

    if mysql_user:
        emp_id = mysql_user["emp_id"]
    elif is_admin:
        emp_id = None
    else:
        return {"error": "User not found in employee directory."}

    # 3. Fetch initiative with ownership verification
    if is_admin:
        rows = await bridge._mysql(
            "SELECT id, initiative_id, initiative_value, owner "
            "FROM initiatives_details WHERE id = %s",
            (initiative_id,),
        )
    else:
        rows = await bridge._mysql(
            "SELECT id, initiative_id, initiative_value, owner "
            "FROM initiatives_details WHERE id = %s AND owner = %s",
            (initiative_id, emp_id),
        )

    if not rows:
        if is_admin:
            return {"error": f"Initiative {initiative_id} not found."}
        return {"error": f"This initiative is not yours. Initiative {initiative_id} is not assigned to you."}

    row = rows[0]
    iv = bridge._parse_json_col(row, "initiative_value")

    try:
        old_progress = int(iv.get("progressval", iv.get("progress", 0)) or 0)
    except (TypeError, ValueError):
        old_progress = 0

    # 4. Update the progress keys inside initiative_value JSON
    iv["progressval"] = str(new_progress)
    iv["progress"] = new_progress
    iv["statusLight"] = _status_light(new_progress)
    iv["statusIndicator"] = _status_indicator(new_progress)

    if is_admin:
        await bridge._mysql_write(
            "UPDATE initiatives_details "
            "SET initiative_value = %s, updated_time = NOW(), updated_by = %s "
            "WHERE id = %s",
            (json.dumps(iv), user_id, initiative_id),
        )
    else:
        await bridge._mysql_write(
            "UPDATE initiatives_details "
            "SET initiative_value = %s, updated_time = NOW(), updated_by = %s "
            "WHERE id = %s AND owner = %s",
            (json.dumps(iv), user_id, initiative_id, emp_id),
        )

    # 5. Build response with confirmation string
    confirmation = (
        f"Successfully updated progress for Initiative #{initiative_id} "
        f"({row.get('initiative_id') or ''}) from {old_progress}% to {new_progress}% in the database."
    )
    requested = str(progress)
    if clamped:
        confirmation += (
            f" Note: the requested value {requested} was out of range and has "
            f"been clamped to {new_progress}% (progress must be 0-100)."
        )
    if new_progress >= 100:
        confirmation += " Initiative marked as fully complete (GREEN)."
    elif new_progress >= 75:
        confirmation += " Initiative status: GREEN."
    elif new_progress >= 40:
        confirmation += " Initiative status: AMBER."
    else:
        confirmation += " Initiative status: RED."

    return {
        "initiative_id": initiative_id,
        "initiative_code": row.get("initiative_id"),
        "old_progress": old_progress,
        "new_progress": new_progress,
        "confirmation": confirmation,
    }
