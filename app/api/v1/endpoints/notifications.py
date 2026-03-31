import uuid
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.core.dependencies import CurrentUser, get_current_user
from app.services.notification import NotificationService
from app.schemas.notification import (
    MarkReadRequest,
    NotificationInboxResponse,
    NotificationResponse,
)
from app.utils.enums import NotificationType

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("", response_model=NotificationInboxResponse)
async def get_inbox(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    is_read: Optional[bool] = Query(None),
    type: Optional[NotificationType] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = NotificationService(db)
    result = await service.get_inbox(
        current_user=current_user,
        is_read=is_read,
        type_filter=type,
        page=page,
        page_size=page_size,
    )
    return NotificationInboxResponse(**result)


@router.get("/unread-count")
async def get_unread_count(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = NotificationService(db)
    return await service.get_unread_count(current_user)


@router.patch("/mark-read")
async def mark_read(
    payload: MarkReadRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = NotificationService(db)
    return await service.mark_read(payload, current_user)


@router.patch("/mark-all-read")
async def mark_all_read(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = NotificationService(db)
    return await service.mark_all_read(current_user)


@router.delete("/clear-read")
async def clear_read(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = NotificationService(db)
    return await service.clear_read(current_user)