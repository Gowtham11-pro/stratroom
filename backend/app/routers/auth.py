from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.security import (
    create_access_token,
    validate_email,
    validate_password_strength,
)
from app.core.rbac import resolve_rbac_role

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def validate_email_format(cls, v: str) -> str:
        v = v.strip().lower()
        if not validate_email(v):
            raise ValueError("Invalid email format")
        return v

    @field_validator("password")
    @classmethod
    def validate_password_not_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("Password is required")
        return v


class RegisterRequest(BaseModel):
    email: str
    password: str
    full_name: str = ""
    role: str = "member"
    org_id: int | None = None

    @field_validator("email")
    @classmethod
    def validate_email_format(cls, v: str) -> str:
        v = v.strip().lower()
        if not validate_email(v):
            raise ValueError("Invalid email format")
        return v

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        errors = validate_password_strength(v)
        if errors:
            raise ValueError("; ".join(errors))
        return v

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        if v not in ("admin", "manager", "member"):
            raise ValueError("Role must be admin, manager, or member")
        return v


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class EmployeeInfo(BaseModel):
    emp_id: int | None = None
    full_name: str | None = None
    title: str | None = None
    department: str | None = None
    location: str | None = None
    email_address: str | None = None


class UserProfileExtended(BaseModel):
    id: int
    org_id: int
    email: str
    full_name: str
    role: str
    designation: str | None = None
    department: str | None = None
    location: str | None = None
    employee: EmployeeInfo | None = None
    enterprise_role: str | None = None


@router.post("/register", response_model=TokenResponse)
async def register(payload: RegisterRequest):
    from app.core.security import hash_password
    from app.services.java_bridge import bridge

    existing = await bridge._mysql(
        "SELECT id FROM users WHERE LOWER(email) = %s",
        (payload.email.lower(),),
    )
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    if payload.org_id:
        org_rows = await bridge._mysql(
            "SELECT id FROM organizations WHERE id = %s", (payload.org_id,)
        )
        if not org_rows:
            raise HTTPException(status_code=400, detail="Organization not found")
        org_id = payload.org_id
    else:
        org_rows = await bridge._mysql(
            "SELECT id FROM organizations ORDER BY id LIMIT 1"
        )
        org_id = org_rows[0]["id"] if org_rows else None
        if org_id is None:
            raise HTTPException(status_code=500, detail="No organization found. Contact administrator.")

    hashed = hash_password(payload.password)
    await bridge._mysql_write(
        "INSERT INTO users (org_id, email, hashed_password, full_name, role) "
        "VALUES (%s, %s, %s, %s, %s)",
        (org_id, payload.email, hashed, payload.full_name.strip() if payload.full_name else "", payload.role),
    )
    return TokenResponse(access_token=create_access_token(payload.email))


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest):
    from app.core.security import verify_password
    from app.services.java_bridge import bridge

    rows = await bridge._mysql(
        "SELECT hashed_password FROM users WHERE LOWER(email) = %s",
        (payload.email.lower(),),
    )
    if not rows or not verify_password(payload.password, rows[0]["hashed_password"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return TokenResponse(access_token=create_access_token(payload.email))


@router.get("/me", response_model=UserProfileExtended)
async def get_me(
    user: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.core.utils import resolve_full_identity

    identity = await resolve_full_identity(user, db)
    if not identity:
        raise HTTPException(status_code=404, detail="User not found")

    emp = identity.get("employee")
    emp_info = None
    if emp:
        emp_info = EmployeeInfo(
            emp_id=emp.get("emp_id"),
            full_name=emp.get("full_name"),
            title=emp.get("title"),
            department=emp.get("department"),
            location=emp.get("location"),
            email_address=emp.get("email_address"),
        )

    return UserProfileExtended(
        id=identity["user_id"],
        org_id=identity["org_id"],
        email=identity["email"],
        full_name=identity.get("full_name") or "",
        role=resolve_rbac_role(identity),
        designation=identity.get("designation"),
        department=identity.get("department"),
        location=identity.get("location"),
        employee=emp_info,
        enterprise_role=identity.get("enterprise_role", {}).get("role") if identity.get("enterprise_role") else None,
    )
