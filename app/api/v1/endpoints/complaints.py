import uuid
from typing import Optional

from fastapi import APIRouter, Depends, BackgroundTasks, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, get_current_user, require_permission
from app.core.exceptions import ForbiddenException
from app.db.session import get_db
from app.schemas.complaint import (
    ComplaintCreate,
    ComplaintStatusUpdate,
    ComplaintResponse,
    ComplaintListResponse,
    FeedbackCreate,
    FeedbackResponse,
)
from app.services.complaint import ComplaintService
from app.utils.enums import ComplaintStatus, ComplaintCategory, RoleEnum

router = APIRouter(prefix="/complaints", tags=["Complaints"])


@router.post("", response_model=ComplaintResponse, status_code=201)
async def create_complaint(
    payload: ComplaintCreate,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    can_create = (
        "complaint:create" in current_user.permissions
        or current_user.role in (RoleEnum.TEACHER, RoleEnum.STUDENT, RoleEnum.PARENT)
    )
    if not can_create:
        raise ForbiddenException(
            detail="Permission 'complaint:create' is required to access this resource"
        )
    return await ComplaintService(db).create_complaint(payload, current_user)


@router.get("", response_model=ComplaintListResponse)
async def list_complaints(
    status: Optional[ComplaintStatus] = Query(None),
    category: Optional[ComplaintCategory] = Query(None),
    submitted_by_role: Optional[RoleEnum] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    can_read = "complaint:read" in current_user.permissions
    own_complaints_fallback = current_user.role in (
        RoleEnum.TEACHER,
        RoleEnum.STUDENT,
        RoleEnum.PARENT,
    )
    if not can_read and not own_complaints_fallback:
        raise ForbiddenException(
            detail="Permission 'complaint:read' is required to access this resource"
        )
    return await ComplaintService(db).list_complaints(
        current_user=current_user,
        status=status,
        category=category,
        submitted_by_role=submitted_by_role,
    )


@router.patch("/{complaint_id}/status", response_model=ComplaintResponse)
async def update_status(
    complaint_id: uuid.UUID,
    payload: ComplaintStatusUpdate,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await ComplaintService(db).update_status(
        complaint_id, payload, current_user, background_tasks
    )


@router.post("/feedback", response_model=FeedbackResponse, status_code=201)
async def create_feedback(
    payload: FeedbackCreate,
    current_user: CurrentUser = Depends(require_permission("complaint:create")),
    db: AsyncSession = Depends(get_db),
):
    return await ComplaintService(db).create_feedback(payload, current_user)
