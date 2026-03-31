import uuid
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.academic_year import AcademicYearService
from app.services.promotion import PromotionService
from app.schemas.academic_year import (
    AcademicYearCreate,
    AcademicYearUpdate,
    AcademicYearResponse,
    AcademicYearListResponse,
)
from app.core.dependencies import get_current_user, require_permission, CurrentUser
from app.core.exceptions import ForbiddenException
from app.utils.enums import RoleEnum

router = APIRouter(prefix="/academic-years", tags=["Academic Years"])


def get_service(db: AsyncSession = Depends(get_db)) -> AcademicYearService:
    return AcademicYearService(db)


def get_promotion_service(db: AsyncSession = Depends(get_db)) -> PromotionService:
    return PromotionService(db)


@router.post("", response_model=AcademicYearResponse, status_code=201)
async def create_academic_year(
    data: AcademicYearCreate,
    current_user: CurrentUser = Depends(require_permission("academic_year:manage")),
    service: AcademicYearService = Depends(get_service),
):
    if not current_user.school_id:
        raise ForbiddenException("School context required")
    return await service.create_academic_year(data, current_user.school_id)


@router.get("", response_model=AcademicYearListResponse)
async def list_academic_years(
    current_user: CurrentUser = Depends(get_current_user),
    service: AcademicYearService = Depends(get_service),
):
    if not current_user.school_id:
        raise ForbiddenException("School context required")
    years, total = await service.list_academic_years(current_user.school_id)
    return AcademicYearListResponse(items=years, total=total)


@router.get("/{year_id}", response_model=AcademicYearResponse)
async def get_academic_year(
    year_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    service: AcademicYearService = Depends(get_service),
):
    if not current_user.school_id:
        raise ForbiddenException("School context required")
    return await service.get_academic_year(year_id, current_user.school_id)


@router.patch("/{year_id}", response_model=AcademicYearResponse)
async def update_academic_year(
    year_id: uuid.UUID,
    data: AcademicYearUpdate,
    current_user: CurrentUser = Depends(require_permission("academic_year:manage")),
    service: AcademicYearService = Depends(get_service),
):
    if not current_user.school_id:
        raise ForbiddenException("School context required")
    return await service.update_academic_year(year_id, current_user.school_id, data)


@router.patch("/{year_id}/activate", response_model=AcademicYearResponse)
async def activate_academic_year(
    year_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("academic_year:manage")),
    service: AcademicYearService = Depends(get_service),
):
    if not current_user.school_id:
        raise ForbiddenException("School context required")
    return await service.activate_academic_year(year_id, current_user.school_id)


@router.post("/{old_year_id}/rollover")
async def rollover_students(
    old_year_id: uuid.UUID,
    new_year_id: uuid.UUID | None = None,
    current_user: CurrentUser = Depends(require_permission("academic_year:manage")),
    service: PromotionService = Depends(get_promotion_service),
):
    if not current_user.school_id:
        raise ForbiddenException("School context required")
    result = await service.rollover(old_year_id, new_year_id, current_user)
    return result
