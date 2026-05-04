import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, get_current_user, require_any_permission
from app.core.exceptions import ForbiddenException
from app.db.session import get_db
from app.schemas.user import (
    UserListResponse,
    UserMeUpdate,
    UserPhotoResponse,
    UserResponse,
)
from app.services.user import UserService
from app.utils.enums import RoleEnum

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("/me", response_model=UserResponse)
async def get_my_user_profile(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Current user row + presigned profile photo URL (mobile / admin parity)."""
    data = await UserService(db).get_me(current_user)
    return UserResponse(**data)


@router.patch("/me", response_model=UserResponse)
async def patch_my_user_profile(
    body: UserMeUpdate,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = UserService(db)
    user = await svc.update_me(current_user, body)
    enriched = await svc.user_to_response_dict(user)
    return UserResponse(**enriched)


@router.post("/{user_id}/photo", response_model=UserPhotoResponse)
async def upload_my_or_managed_user_photo(
    user_id: uuid.UUID,
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user.school_id:
        raise ForbiddenException("School context required")
    result = await UserService(db).upload_profile_photo(
        user_id=user_id,
        school_id=current_user.school_id,
        file=file,
        current_user=current_user,
    )
    return UserPhotoResponse(**result)


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
