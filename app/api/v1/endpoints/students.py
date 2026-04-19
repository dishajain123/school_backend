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
    StudentBulkPromotionUpdate,
    StudentSectionPromotionUpdate,
    StudentSectionCreateRequest,
    StudentSectionCreateResponse,
    StudentResponse,
    StudentListResponse,
    StudentBulkPromotionResponse,
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


@router.post("/sections", response_model=StudentSectionCreateResponse, status_code=201)
async def create_student_section(
    payload: StudentSectionCreateRequest,
    current_user: CurrentUser = Depends(require_permission("user:manage")),
    service: StudentService = Depends(get_service),
):
    if not current_user.school_id:
        raise ForbiddenException("School context required")
    created, sections, effective_year = await service.create_section(
        school_id=current_user.school_id,
        current_user=current_user,
        standard_id=payload.standard_id,
        section=payload.section,
        academic_year_id=payload.academic_year_id,
    )
    return StudentSectionCreateResponse(
        standard_id=payload.standard_id,
        academic_year_id=effective_year,
        section=created,
        sections=sections,
    )


@router.get("/me", response_model=StudentResponse)
async def get_my_student_profile(
    current_user: CurrentUser = Depends(get_current_user),
    service: StudentService = Depends(get_service),
):
    if not current_user.school_id:
        raise ForbiddenException("School context required")
    return await service.get_my_student_profile(
        school_id=current_user.school_id,
        current_user=current_user,
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


@router.patch("/promotion-status/bulk", response_model=StudentBulkPromotionResponse)
async def bulk_update_promotion_status(
    data: StudentBulkPromotionUpdate,
    current_user: CurrentUser = Depends(require_permission("student:promote")),
    service: StudentService = Depends(get_service),
):
    if not current_user.school_id:
        raise ForbiddenException("School context required")
    items = await service.bulk_update_promotion_status(
        student_ids=data.student_ids,
        school_id=current_user.school_id,
        data=StudentPromotionUpdate(promotion_status=data.promotion_status),
        current_user=current_user,
    )
    return StudentBulkPromotionResponse(
        updated_count=len(items),
        items=items,
    )


@router.patch("/promotion-status/section", response_model=StudentBulkPromotionResponse)
async def bulk_update_promotion_status_by_section(
    data: StudentSectionPromotionUpdate,
    current_user: CurrentUser = Depends(require_permission("student:promote")),
    service: StudentService = Depends(get_service),
):
    if not current_user.school_id:
        raise ForbiddenException("School context required")
    items = await service.bulk_update_promotion_status_by_section(
        standard_id=data.standard_id,
        section=data.section,
        school_id=current_user.school_id,
        data=StudentPromotionUpdate(promotion_status=data.promotion_status),
        current_user=current_user,
        academic_year_id=data.academic_year_id,
        excluded_student_ids=data.excluded_student_ids,
    )
    return StudentBulkPromotionResponse(
        updated_count=len(items),
        items=items,
    )
