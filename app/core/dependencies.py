import uuid
from typing import Optional

from fastapi import Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import ForbiddenException, UnauthorizedException
from app.core.security import decode_token
from app.db.session import get_db
from app.models.jti_blocklist import JtiBlocklist
from app.models.parent import Parent
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


async def hydrate_current_user_from_access_payload(
    payload: dict,
    db: AsyncSession,
) -> CurrentUser:
    """
    Build CurrentUser from a validated access-token payload + DB user row.

    ``sub`` identifies the user. Tenant context (``school_id``) always comes from the
    database (or ``DEFAULT_SCHOOL_ID`` when the user row has no school during legacy
    transition). Optional ``school_id`` / ``role`` claims on the token are validated
    against the DB but never used to derive the school.
    """
    school_id_raw = payload.get("school_id")
    parent_id_raw = payload.get("parent_id")

    resolved_parent_id: Optional[uuid.UUID] = (
        uuid.UUID(str(parent_id_raw)) if parent_id_raw else None
    )

    user_row = await db.execute(
        select(User.status, User.is_active, User.school_id, User.role).where(
            User.id == uuid.UUID(str(payload["sub"]))
        )
    )
    user_state = user_row.one_or_none()
    if not user_state:
        raise UnauthorizedException(detail="User not found")
    user_status, user_is_active, user_school_id, user_role = user_state
    if user_status != UserStatus.ACTIVE or not user_is_active:
        raise ForbiddenException(detail="Account is not active")

    role_claim = payload.get("role")
    if role_claim is not None and role_claim != user_role.value:
        raise ForbiddenException(detail="Token role claim does not match your account")

    token_school_id: Optional[uuid.UUID] = None
    if school_id_raw:
        try:
            token_school_id = uuid.UUID(str(school_id_raw))
        except (ValueError, TypeError) as exc:
            raise UnauthorizedException(detail="Invalid school claim in token") from exc

    if user_school_id is not None:
        resolved_school_id = user_school_id
    elif settings.DEFAULT_SCHOOL_ID:
        resolved_school_id = uuid.UUID(str(settings.DEFAULT_SCHOOL_ID).strip())
    else:
        raise UnauthorizedException(
            detail=(
                "School context is missing for this account. "
                "Configure DEFAULT_SCHOOL_ID or assign school_id to the user."
            )
        )

    if token_school_id is not None and token_school_id != resolved_school_id:
        raise ForbiddenException(
            detail="Token school claim does not match your account",
        )

    if resolved_parent_id is None and user_role == RoleEnum.PARENT:
        parent_row = await db.execute(
            select(Parent.id).where(Parent.user_id == uuid.UUID(str(payload["sub"])))
        )
        resolved_parent_id = parent_row.scalar_one_or_none()

    perms = payload.get("permissions", [])
    if not isinstance(perms, list):
        perms = []

    return CurrentUser(
        id=uuid.UUID(str(payload["sub"])),
        role=user_role,
        school_id=resolved_school_id,
        parent_id=resolved_parent_id,
        permissions=perms,
        full_name=payload.get("full_name"),
        email=payload.get("email"),
        phone=payload.get("phone"),
        status=user_status,
        is_active=user_is_active,
    )


async def get_current_user_from_access_token(
    token: str,
    db: AsyncSession,
) -> CurrentUser:
    """
    Full access-token auth: decode, type + JTI + blocklist, then hydrate.
    Used by HTTP Bearer and WebSocket first-frame auth so behavior stays identical.
    """
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

    return await hydrate_current_user_from_access_payload(payload, db)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> CurrentUser:
    return await get_current_user_from_access_token(credentials.credentials, db)


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
