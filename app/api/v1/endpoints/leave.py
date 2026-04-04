import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, get_current_user, require_permission
from app.core.exceptions import ForbiddenException
from app.db.session import get_db
from app.schemas.leave import (
    LeaveApplyRequest,
    LeaveDecisionRequest,
    LeaveResponse,
    LeaveListResponse,
    LeaveBalanceResponse,
)
from app.services.leave import LeaveService
from app.utils.enums import LeaveStatus, RoleEnum

router = APIRouter(prefix="/leave", tags=["Leave"])


@router.post("/apply", response_model=LeaveResponse, status_code=201)
async def apply_leave(
    payload: LeaveApplyRequest,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(require_permission("leave:apply")),
    db: AsyncSession = Depends(get_db),
):
    return await LeaveService(db).apply_leave(payload, current_user, background_tasks)


@router.patch("/{leave_id}/decision", response_model=LeaveResponse)
async def decide_leave(
    leave_id: uuid.UUID,
    payload: LeaveDecisionRequest,
    current_user: CurrentUser = Depends(require_permission("leave:approve")),
    db: AsyncSession = Depends(get_db),
):
    return await LeaveService(db).decide_leave(leave_id, payload, current_user)


@router.get("", response_model=LeaveListResponse)
async def list_leaves(
    status: Optional[LeaveStatus] = Query(None),
    academic_year_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Backward-compatible access:
    # - Preferred: users with explicit leave:read.
    # - Teacher fallback: allow own-leave listing if leave:apply exists.
    can_read = "leave:read" in current_user.permissions
    teacher_fallback = current_user.role == RoleEnum.TEACHER
    if not can_read and not teacher_fallback:
        raise ForbiddenException(
            detail="Permission 'leave:read' is required to access this resource"
        )
    return await LeaveService(db).list_leaves(current_user, status, academic_year_id)


@router.get("/balance", response_model=list[LeaveBalanceResponse])
async def get_balance(
    academic_year_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(require_permission("leave:apply")),
    db: AsyncSession = Depends(get_db),
):
    return await LeaveService(db).get_balance(current_user, academic_year_id)
