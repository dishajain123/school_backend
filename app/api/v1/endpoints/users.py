from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_any_permission
from app.core.exceptions import ForbiddenException
from app.db.session import get_db
from app.schemas.user import UserListResponse, UserResponse
from app.services.user import UserService
from app.utils.enums import RoleEnum

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("", response_model=UserListResponse)
async def list_school_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    role: Optional[RoleEnum] = Query(None),
    is_active: Optional[bool] = Query(None),
    current_user: CurrentUser = Depends(
        require_any_permission("user:manage", "document:manage")
    ),
    db: AsyncSession = Depends(get_db),
):
    """Paginated school directory. Used by admin console (documents, enrollment)."""
    if not current_user.school_id:
        raise ForbiddenException("School context required")
    items, total, total_pages = await UserService(db).list_users(
        school_id=current_user.school_id,
        role=role,
        is_active=is_active,
        page=page,
        page_size=page_size,
    )
    return UserListResponse(
        items=[UserResponse(**u) for u in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )
