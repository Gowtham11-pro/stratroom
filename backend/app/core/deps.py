from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.core.db import get_db
from app.core.rbac import resolve_rbac_role, has_permission

bearer_scheme = HTTPBearer()


async def get_current_user(creds: HTTPAuthorizationCredentials = Depends(bearer_scheme)) -> str:
    try:
        return decode_access_token(creds.credentials)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


async def get_current_user_with_employee(
    user: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Dependency that provides the full identity context for the current user.

    Returns dict with keys: email, user_id, org_id, app_role, employee, enterprise_role,
    designation, department, location.
    """
    from app.core.utils import resolve_full_identity

    identity = await resolve_full_identity(db, user)
    if not identity:
        raise HTTPException(status_code=404, detail="User not found")
    return identity


class require_role:
    """FastAPI dependency factory that enforces minimum RBAC role.

    Usage:
        @router.get("/admin-only")
        async def admin_endpoint(ctx: dict = Depends(require_role("admin"))):
            # ctx["rbac_role"] contains the resolved role
            ...

    If the user's effective role level is below the required level,
    raises HTTPException(403).
    """

    def __init__(self, min_role: str):
        self.min_role = min_role

    async def __call__(
        self,
        identity: dict = Depends(get_current_user_with_employee),
    ) -> dict:
        user_role = resolve_rbac_role(identity)
        if not has_permission(user_role, self.min_role):
            raise HTTPException(
                status_code=403,
                detail=f"Insufficient permissions. Required: {self.min_role}, Current: {user_role}",
            )
        identity["rbac_role"] = user_role
        identity["is_admin"] = has_permission(user_role, "admin")
        identity["is_manager"] = has_permission(user_role, "manager")
        return identity
