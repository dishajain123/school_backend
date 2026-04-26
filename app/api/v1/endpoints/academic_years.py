import uuid
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.academic_year import AcademicYearService
from app.schemas.academic_year import (
    AcademicYearCreate,
    AcademicYearUpdate,
    AcademicYearResponse,
    AcademicYearListResponse,
)
from app.core.dependencies import get_current_user, require_permission, CurrentUser
from app.core.exceptions import ForbiddenException, GoneException
from app.utils.enums import RoleEnum

router = APIRouter(prefix="/academic-years", tags=["Academic Years"])


def get_service(db: AsyncSession = Depends(get_db)) -> AcademicYearService:
    return AcademicYearService(db)


def _resolve_school_scope(
    current_user: CurrentUser,
    school_id: Optional[uuid.UUID],
) -> uuid.UUID:
    if current_user.role == RoleEnum.SUPERADMIN:
        if school_id is not None:
            return school_id
        if current_user.school_id is not None:
            return current_user.school_id
        raise ForbiddenException("Superadmin must provide school_id for academic year operation")

    if not current_user.school_id:
        raise ForbiddenException("School context required")
    if school_id is not None and school_id != current_user.school_id:
        raise ForbiddenException("Cannot operate on another school")
    return current_user.school_id


@router.post("", response_model=AcademicYearResponse, status_code=201)
async def create_academic_year(
    data: AcademicYearCreate,
    school_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(require_permission("academic_year:manage")),
    service: AcademicYearService = Depends(get_service),
):
    if current_user.role != RoleEnum.SUPERADMIN:
        raise ForbiddenException("Only Super Admin can create academic years")
    resolved_school_id = _resolve_school_scope(current_user, school_id)
    return await service.create_academic_year(data, resolved_school_id)


@router.get("", response_model=AcademicYearListResponse)
async def list_academic_years(
    school_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    service: AcademicYearService = Depends(get_service),
):
    resolved_school_id = _resolve_school_scope(current_user, school_id)
    years, total = await service.list_academic_years(resolved_school_id)
    return AcademicYearListResponse(items=years, total=total)


@router.patch("/{year_id}", response_model=AcademicYearResponse)
async def update_academic_year(
    year_id: uuid.UUID,
    data: AcademicYearUpdate,
    school_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(require_permission("academic_year:manage")),
    service: AcademicYearService = Depends(get_service),
):
    resolved_school_id = _resolve_school_scope(current_user, school_id)
    return await service.update_academic_year(year_id, resolved_school_id, data)


@router.patch("/{year_id}/activate", response_model=AcademicYearResponse)
async def activate_academic_year(
    year_id: uuid.UUID,
    school_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(require_permission("academic_year:manage")),
    service: AcademicYearService = Depends(get_service),
):
    if current_user.role != RoleEnum.SUPERADMIN:
        raise ForbiddenException("Only Super Admin can activate academic years")
    resolved_school_id = _resolve_school_scope(current_user, school_id)
    return await service.activate_academic_year(year_id, resolved_school_id)


@router.post("/{old_year_id}/rollover", deprecated=True)
async def rollover_students(
    old_year_id: uuid.UUID,
    new_year_id: Optional[uuid.UUID] = None,
    school_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(require_permission("academic_year:manage")),
):
    raise GoneException(
        detail=(
            "Deprecated API: /academic-years/{old_year_id}/rollover is no longer supported. "
            "Use the scheduled promotion workflow service instead."
        )
    )
