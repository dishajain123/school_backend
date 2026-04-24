import uuid
from typing import Optional
from fastapi import APIRouter, Depends, Query, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.user import UserService
from app.schemas.user import (
    UserResponse,
    UserPhotoResponse,
    UserMeUpdate,
)
from app.core.dependencies import get_current_user, require_permission, CurrentUser
from app.core.exceptions import ForbiddenException, GoneException

router = APIRouter(prefix="/users", tags=["Users"])

_USERS_MANAGEMENT_GONE_DETAIL = (
    "Deprecated API: user management endpoints under /users are no longer available. "
    "Use /users/me for self updates and admin panel APIs for staff-managed operations."
)


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


@router.get("", deprecated=True)
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    role: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    current_user: CurrentUser = Depends(require_permission("user:manage")),
    service: UserService = Depends(get_service),
):
    raise GoneException(detail=_USERS_MANAGEMENT_GONE_DETAIL)


@router.post("", deprecated=True)
async def create_user(
    data: dict,
    current_user: CurrentUser = Depends(require_permission("user:manage")),
    service: UserService = Depends(get_service),
):
    raise GoneException(detail=_USERS_MANAGEMENT_GONE_DETAIL)


@router.get("/{user_id}", deprecated=True)
async def get_user(
    user_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("user:manage")),
    service: UserService = Depends(get_service),
):
    raise GoneException(detail=_USERS_MANAGEMENT_GONE_DETAIL)


@router.patch("/{user_id}", deprecated=True)
async def update_user(
    user_id: uuid.UUID,
    data: dict,
    current_user: CurrentUser = Depends(require_permission("user:manage")),
    service: UserService = Depends(get_service),
):
    raise GoneException(detail=_USERS_MANAGEMENT_GONE_DETAIL)


@router.patch("/{user_id}/deactivate", deprecated=True)
async def deactivate_user(
    user_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("user:manage")),
    service: UserService = Depends(get_service),
):
    raise GoneException(detail=_USERS_MANAGEMENT_GONE_DETAIL)


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
