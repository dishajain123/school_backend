import uuid
from typing import Optional

from fastapi import APIRouter, Depends, BackgroundTasks, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, get_current_user, require_permission
from app.db.session import get_db
from app.schemas.announcement import (
    AnnouncementCreate,
    AnnouncementUpdate,
    AnnouncementResponse,
    AnnouncementListResponse,
)
from app.services.announcement import AnnouncementService

router = APIRouter(prefix="/announcements", tags=["Announcements"])


@router.post("", response_model=AnnouncementResponse, status_code=201)
async def create_announcement(
    payload: AnnouncementCreate,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(require_permission("announcement:create")),
    db: AsyncSession = Depends(get_db),
):
    return await AnnouncementService(db).create_announcement(
        payload, current_user, background_tasks
    )


@router.get("", response_model=AnnouncementListResponse)
async def list_announcements(
    include_inactive: bool = Query(False),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await AnnouncementService(db).list_announcements(
        current_user=current_user,
        include_inactive=include_inactive,
    )


@router.patch("/{announcement_id}", response_model=AnnouncementResponse)
async def update_announcement(
    announcement_id: uuid.UUID,
    payload: AnnouncementUpdate,
    current_user: CurrentUser = Depends(require_permission("announcement:create")),
    db: AsyncSession = Depends(get_db),
):
    return await AnnouncementService(db).update_announcement(
        announcement_id, payload, current_user
    )
