from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.db import get_db
from app.core.deps import require_role

router = APIRouter(tags=["budgets"])


@router.get("/budgets")
async def list_budget_lines(
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("member")),
):
    user_id = ctx["user_id"]
    org_id = ctx["org_id"]
    is_admin = ctx["is_admin"]
    is_manager = ctx["is_manager"]

    if is_admin or is_manager:
        result = await db.execute(
            text("SELECT id, year, month, gl_account, gl_name, budget_type, project, total, department, employee, notes FROM budget_lines WHERE org_id = :oid ORDER BY year, id"),
            {"oid": org_id},
        )
    else:
        result = await db.execute(
            text("SELECT id, year, month, gl_account, gl_name, budget_type, project, total, department, employee, notes FROM budget_lines WHERE org_id = :oid AND employee = :email ORDER BY year, id"),
            {"oid": org_id, "email": ctx["email"]},
        )
    rows = result.mappings().all()
    return {"budgets": [dict(r) for r in rows]}


@router.get("/budgets/summary")
async def budget_summary(
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("member")),
):
    user_id = ctx["user_id"]
    org_id = ctx["org_id"]
    is_admin = ctx["is_admin"]
    is_manager = ctx["is_manager"]

    if is_admin or is_manager:
        result = await db.execute(
            text("""
                SELECT COUNT(*) as line_count,
                       SUM(total) as total_amount,
                       COUNT(DISTINCT project) as project_count,
                       COUNT(DISTINCT gl_account) as gl_count
                FROM budget_lines WHERE org_id = :oid
            """),
            {"oid": org_id},
        )
    else:
        result = await db.execute(
            text("""
                SELECT COUNT(*) as line_count,
                       SUM(total) as total_amount,
                       COUNT(DISTINCT project) as project_count,
                       COUNT(DISTINCT gl_account) as gl_count
                FROM budget_lines WHERE org_id = :oid AND employee = :email
            """),
            {"oid": org_id, "email": ctx["email"]},
        )
    row = result.mappings().one()
    return dict(row)
