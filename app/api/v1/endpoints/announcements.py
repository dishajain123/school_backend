import uuid
from typing import Optional

from fastapi import APIRouter, Depends, BackgroundTasks, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, get_current_user
from app.core.exceptions import ForbiddenException
from app.db.session import get_db
from app.schemas.announcement import (
    AnnouncementCreate,
    AnnouncementUpdate,
    AnnouncementResponse,
    AnnouncementListResponse,
)
from app.services.announcement import AnnouncementService
from app.utils.enums import RoleEnum

router = APIRouter(prefix="/announcements", tags=["Announcements"])


def _can_manage_announcements(user: CurrentUser) -> bool:
    if user.role in (RoleEnum.PRINCIPAL, RoleEnum.SUPERADMIN):
        return True
    return "announcement:create" in user.permissions


@router.post("", response_model=AnnouncementResponse, status_code=201)
async def create_announcement(
    payload: AnnouncementCreate,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not _can_manage_announcements(current_user):
        raise ForbiddenException(
            "Permission 'announcement:create' is required to access this resource"
        )
    return await AnnouncementService(db).create_announcement(
        payload, current_user, background_tasks
    )


@router.get("", response_model=AnnouncementListResponse)
async def list_announcements(
    include_inactive: bool = Query(False),
    target_role: Optional[RoleEnum] = Query(None),
    target_standard_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await AnnouncementService(db).list_announcements(
        current_user=current_user,
        include_inactive=include_inactive,
        target_role=target_role,
        target_standard_id=target_standard_id,
    )


@router.get("/{announcement_id}", response_model=AnnouncementResponse)
async def get_announcement(
    announcement_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await AnnouncementService(db).get_announcement_by_id(
        announcement_id, current_user
    )


@router.patch("/{announcement_id}", response_model=AnnouncementResponse)
async def update_announcement(
    announcement_id: uuid.UUID,
    payload: AnnouncementUpdate,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not _can_manage_announcements(current_user):
        raise ForbiddenException(
            "Permission 'announcement:create' is required to access this resource"
        )
    return await AnnouncementService(db).update_announcement(
        announcement_id, payload, current_user
    )


@router.delete("/{announcement_id}", status_code=204)
async def delete_announcement(
    announcement_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not _can_manage_announcements(current_user):
        raise ForbiddenException(
            "Permission 'announcement:create' is required to access this resource"
        )
    await AnnouncementService(db).delete_announcement(announcement_id, current_user)
    return Response(status_code=204)
