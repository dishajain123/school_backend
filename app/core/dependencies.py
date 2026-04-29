import uuid
from typing import Optional
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from app.db.session import get_db
from app.core.security import decode_token
from app.core.exceptions import UnauthorizedException, ForbiddenException
from app.models.jti_blocklist import JtiBlocklist
from app.models.parent import Parent
from app.models.school import School
from app.models.user import User
from app.utils.enums import RoleEnum, UserStatus

security = HTTPBearer()


class CurrentUser(BaseModel):
    id: uuid.UUID
    role: RoleEnum
    school_id: Optional[uuid.UUID]
    parent_id: Optional[uuid.UUID]
    permissions: list[str]
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    status: UserStatus = UserStatus.ACTIVE
    is_active: bool = True

    model_config = {"from_attributes": True}


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> CurrentUser:
    token = credentials.credentials
    payload = decode_token(token)

    if payload.get("type") != "access":
        raise UnauthorizedException(detail="Invalid token type")

    jti = payload.get("jti")
    if not jti:
        raise UnauthorizedException(detail="Token missing JTI")

    result = await db.execute(
        select(JtiBlocklist).where(JtiBlocklist.jti == jti)
    )
    blocked = result.scalar_one_or_none()
    if blocked:
        raise UnauthorizedException(detail="Token has been revoked")

    school_id_raw = payload.get("school_id")
    parent_id_raw = payload.get("parent_id")

    resolved_parent_id: Optional[uuid.UUID] = (
        uuid.UUID(parent_id_raw) if parent_id_raw else None
    )

    user_row = await db.execute(
        select(User.status, User.is_active, User.school_id).where(
            User.id == uuid.UUID(payload["sub"])
        )
    )
    user_state = user_row.one_or_none()
    if not user_state:
        raise UnauthorizedException(detail="User not found")
    user_status, user_is_active, user_school_id = user_state
    if user_status != UserStatus.ACTIVE or not user_is_active:
        raise ForbiddenException(detail="Account is not active")

    resolved_school_id: Optional[uuid.UUID] = None
    if school_id_raw:
        resolved_school_id = uuid.UUID(school_id_raw)
    elif user_school_id:
        resolved_school_id = user_school_id
    else:
        # Single-school fallback: pick first active school when user-school is null.
        school_row = await db.execute(
            select(School.id)
            .where(School.is_active.is_(True))
            .order_by(School.created_at.asc())
        )
        resolved_school_id = school_row.scalar_one_or_none()
    # Backward compatibility: some tokens may miss parent_id for parent role.
    # Resolve it once here so all parent-scoped services work consistently.
    if resolved_parent_id is None and payload.get("role") == RoleEnum.PARENT.value:
        parent_row = await db.execute(
            select(Parent.id).where(Parent.user_id == uuid.UUID(payload["sub"]))
        )
        resolved_parent_id = parent_row.scalar_one_or_none()

    return CurrentUser(
        id=uuid.UUID(payload["sub"]),
        role=RoleEnum(payload["role"]),
        school_id=resolved_school_id,
        parent_id=resolved_parent_id,
        permissions=payload.get("permissions", []),
        full_name=payload.get("full_name"),
        email=payload.get("email"),
        phone=payload.get("phone"),
        status=user_status,
        is_active=user_is_active,
    )


def require_permission(permission: str):
    async def checker(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if permission not in current_user.permissions:
            raise ForbiddenException(
                detail=f"Permission '{permission}' is required to access this resource"
            )
        return current_user
    return checker


def require_any_permission(*permissions: str):
    async def checker(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not any(permission in current_user.permissions for permission in permissions):
            raise ForbiddenException(
                detail="One of the following permissions is required: "
                + ", ".join(permissions),
            )
        return current_user
    return checker


def require_roles(*roles: RoleEnum):
    async def checker(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if current_user.role not in roles:
            raise ForbiddenException(
                detail=f"Role '{current_user.role}' is not allowed to access this resource"
            )
        return current_user
    return checker


async def inject_school_id(
    current_user: CurrentUser = Depends(get_current_user),
) -> Optional[uuid.UUID]:
    return current_user.school_id


async def get_current_active_user(
    current_user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    if not current_user.is_active:
        raise ForbiddenException(detail="User account is deactivated")
    return current_user
