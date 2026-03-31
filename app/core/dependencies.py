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
from app.utils.enums import RoleEnum

security = HTTPBearer()


class CurrentUser(BaseModel):
    id: uuid.UUID
    role: RoleEnum
    school_id: Optional[uuid.UUID]
    parent_id: Optional[uuid.UUID]
    permissions: list[str]
    email: Optional[str] = None
    phone: Optional[str] = None
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

    return CurrentUser(
        id=uuid.UUID(payload["sub"]),
        role=RoleEnum(payload["role"]),
        school_id=uuid.UUID(school_id_raw) if school_id_raw else None,
        parent_id=uuid.UUID(parent_id_raw) if parent_id_raw else None,
        permissions=payload.get("permissions", []),
        email=payload.get("email"),
        phone=payload.get("phone"),
        is_active=payload.get("is_active", True),
    )


def require_permission(permission: str):
    async def checker(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if permission not in current_user.permissions:
            raise ForbiddenException(
                detail=f"Permission '{permission}' is required to access this resource"
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