import uuid
import math
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.core.dependencies import (
    CurrentUser,
    get_current_user,
    require_permission,
)
from app.core.exceptions import ValidationException
from app.services.teacher import TeacherService
from app.schemas.teacher import (
    TeacherCreate,
    TeacherUpdate,
    TeacherResponse,
    TeacherListResponse,
    TeacherUserResponse,
)

router = APIRouter(prefix="/teachers", tags=["Teachers"])


@router.post("", response_model=TeacherResponse, status_code=201)
async def create_teacher(
    payload: TeacherCreate,
    current_user: CurrentUser = Depends(require_permission("user:manage")),
    db: AsyncSession = Depends(get_db),
):
    if not current_user.school_id:
        raise ValidationException("school_id is required")

    service = TeacherService(db)
    teacher = await service.create_teacher(payload, current_user.school_id, current_user)
    return _to_response(teacher)


@router.get("", response_model=TeacherListResponse)
async def list_teachers(
    academic_year_id: Optional[uuid.UUID] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user.school_id:
        raise ValidationException("school_id is required")

    service = TeacherService(db)
    teachers, total = await service.list_teachers(
        school_id=current_user.school_id,
        academic_year_id=academic_year_id,
        page=page,
        page_size=page_size,
    )
    return TeacherListResponse(
        items=[_to_response(t) for t in teachers],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=math.ceil(total / page_size) if total else 0,
    )


@router.get("/{teacher_id}", response_model=TeacherResponse)
async def get_teacher(
    teacher_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = TeacherService(db)
    teacher = await service.get_teacher(teacher_id, current_user)
    return _to_response(teacher)


@router.patch("/{teacher_id}", response_model=TeacherResponse)
async def update_teacher(
    teacher_id: uuid.UUID,
    payload: TeacherUpdate,
    current_user: CurrentUser = Depends(require_permission("user:manage")),
    db: AsyncSession = Depends(get_db),
):
    service = TeacherService(db)
    teacher = await service.update_teacher(teacher_id, payload, current_user)
    return _to_response(teacher)


# ── Internal helper ───────────────────────────────────────────────────────────

def _to_response(teacher) -> TeacherResponse:
    user_resp = TeacherUserResponse(
        id=teacher.user.id,
        email=teacher.user.email,
        phone=teacher.user.phone,
        is_active=teacher.user.is_active,
        profile_photo_key=teacher.user.profile_photo_key,
        profile_photo_url=None,
    )
    return TeacherResponse(
        id=teacher.id,
        school_id=teacher.school_id,
        academic_year_id=teacher.academic_year_id,
        employee_code=teacher.employee_code,
        join_date=teacher.join_date,
        specialization=teacher.specialization,
        user=user_resp,
        created_at=teacher.created_at,
        updated_at=teacher.updated_at,
    )