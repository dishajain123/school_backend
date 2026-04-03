import uuid
import math
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.student import StudentService
from app.schemas.student import (
    StudentCreate,
    StudentUpdate,
    StudentPromotionUpdate,
    StudentResponse,
    StudentListResponse,
)
from app.core.dependencies import get_current_user, require_permission, CurrentUser
from app.core.exceptions import ForbiddenException
from app.utils.enums import RoleEnum

router = APIRouter(prefix="/students", tags=["Students"])


def get_service(db: AsyncSession = Depends(get_db)) -> StudentService:
    return StudentService(db)


@router.post("", response_model=StudentResponse, status_code=201)
async def create_student(
    data: StudentCreate,
    current_user: CurrentUser = Depends(require_permission("user:manage")),
    service: StudentService = Depends(get_service),
):
    if not current_user.school_id:
        raise ForbiddenException("School context required")
    return await service.create_student(data, current_user.school_id)


@router.get("", response_model=StudentListResponse)
async def list_students(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    standard_id: Optional[uuid.UUID] = Query(None),
    section: Optional[str] = Query(None),
    academic_year_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    service: StudentService = Depends(get_service),
):
    if not current_user.school_id:
        raise ForbiddenException("School context required")

    students, total, total_pages = await service.list_students(
        school_id=current_user.school_id,
        current_user=current_user,
        standard_id=standard_id,
        section=section,
        academic_year_id=academic_year_id,
        page=page,
        page_size=page_size,
    )
    return StudentListResponse(
        items=students,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/sections", response_model=list[str])
async def list_student_sections(
    standard_id: Optional[uuid.UUID] = Query(None),
    academic_year_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    service: StudentService = Depends(get_service),
):
    if not current_user.school_id:
        raise ForbiddenException("School context required")
    return await service.list_sections(
        school_id=current_user.school_id,
        current_user=current_user,
        standard_id=standard_id,
        academic_year_id=academic_year_id,
    )


@router.get("/{student_id}", response_model=StudentResponse)
async def get_student(
    student_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    service: StudentService = Depends(get_service),
):
    if not current_user.school_id:
        raise ForbiddenException("School context required")
    return await service.get_student(student_id, current_user.school_id, current_user)


@router.patch("/{student_id}", response_model=StudentResponse)
async def update_student(
    student_id: uuid.UUID,
    data: StudentUpdate,
    current_user: CurrentUser = Depends(require_permission("user:manage")),
    service: StudentService = Depends(get_service),
):
    if not current_user.school_id:
        raise ForbiddenException("School context required")
    return await service.update_student(
        student_id, current_user.school_id, data, current_user
    )


@router.patch("/{student_id}/promotion-status", response_model=StudentResponse)
async def update_promotion_status(
    student_id: uuid.UUID,
    data: StudentPromotionUpdate,
    current_user: CurrentUser = Depends(require_permission("student:promote")),
    service: StudentService = Depends(get_service),
):
    if not current_user.school_id:
        raise ForbiddenException("School context required")
    return await service.update_promotion_status(
        student_id, current_user.school_id, data, current_user
    )
