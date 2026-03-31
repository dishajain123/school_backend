import uuid
import math
from typing import Optional
from fastapi import APIRouter, Depends, Query, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.user import UserService
from app.schemas.user import (
    UserCreate,
    UserUpdate,
    UserResponse,
    UserListResponse,
    UserPhotoResponse,
    UserMeUpdate,
)
from app.core.dependencies import get_current_user, require_permission, CurrentUser
from app.core.exceptions import ForbiddenException
from app.utils.enums import RoleEnum

router = APIRouter(prefix="/users", tags=["Users"])


def get_service(db: AsyncSession = Depends(get_db)) -> UserService:
    return UserService(db)


@router.get("/me", response_model=UserResponse)
async def get_me(
    current_user: CurrentUser = Depends(get_current_user),
    service: UserService = Depends(get_service),
):
    return await service.get_me(current_user)


@router.patch("/me", response_model=UserResponse)
async def update_me(
    data: UserMeUpdate,
    current_user: CurrentUser = Depends(get_current_user),
    service: UserService = Depends(get_service),
):
    return await service.update_me(current_user, data)


@router.get("", response_model=UserListResponse)
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    role: Optional[RoleEnum] = Query(None),
    is_active: Optional[bool] = Query(None),
    current_user: CurrentUser = Depends(require_permission("user:manage")),
    service: UserService = Depends(get_service),
):
    if not current_user.school_id:
        raise ForbiddenException("School context required")

    enriched, total, total_pages = await service.list_users(
        school_id=current_user.school_id,
        role=role,
        is_active=is_active,
        page=page,
        page_size=page_size,
    )
    return UserListResponse(
        items=enriched,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.post("", response_model=UserResponse, status_code=201)
async def create_user(
    data: UserCreate,
    current_user: CurrentUser = Depends(require_permission("user:manage")),
    service: UserService = Depends(get_service),
):
    if not current_user.school_id:
        raise ForbiddenException("School context required")
    return await service.create_user(data, current_user.school_id)


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("user:manage")),
    service: UserService = Depends(get_service),
):
    if not current_user.school_id:
        raise ForbiddenException("School context required")
    user = await service.get_user(user_id, current_user.school_id)
    return await service._enrich_with_photo_url(user)


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: uuid.UUID,
    data: UserUpdate,
    current_user: CurrentUser = Depends(require_permission("user:manage")),
    service: UserService = Depends(get_service),
):
    if not current_user.school_id:
        raise ForbiddenException("School context required")
    user = await service.update_user(user_id, current_user.school_id, data)
    return await service._enrich_with_photo_url(user)


@router.patch("/{user_id}/deactivate", response_model=UserResponse)
async def deactivate_user(
    user_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("user:manage")),
    service: UserService = Depends(get_service),
):
    if not current_user.school_id:
        raise ForbiddenException("School context required")
    user = await service.deactivate_user(user_id, current_user.school_id)
    return await service._enrich_with_photo_url(user)


@router.post("/{user_id}/photo", response_model=UserPhotoResponse)
async def upload_profile_photo(
    user_id: uuid.UUID,
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(get_current_user),
    service: UserService = Depends(get_service),
):
    if not current_user.school_id:
        raise ForbiddenException("School context required")
    return await service.upload_profile_photo(
        user_id=user_id,
        school_id=current_user.school_id,
        file=file,
        current_user=current_user,
    )