import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, get_current_user
from app.core.exceptions import ForbiddenException, ValidationException
from app.db.session import get_db
from app.schemas.student_year_mapping import (
    ClassRosterResponse,
    RollNumberAssignRequest,
    StudentExitRequest,
    StudentYearMappingCreate,
    StudentYearMappingResponse,
    StudentYearMappingUpdate,
)
from app.services.enrollment import EnrollmentService
from app.utils.enums import RoleEnum

router = APIRouter(prefix="/enrollments", tags=["Enrollments"])


def _require_school(current_user: CurrentUser) -> uuid.UUID:
    if not current_user.school_id:
        raise ValidationException("School context is required")
    return current_user.school_id


def _can_manage_enrollment(current_user: CurrentUser) -> bool:
    if "user:manage" in current_user.permissions:
        return True
    return current_user.role in (RoleEnum.PRINCIPAL, RoleEnum.SUPERADMIN)


def _to_response(mapping) -> StudentYearMappingResponse:
    return StudentYearMappingResponse(
        id=mapping.id,
        student_id=mapping.student_id,
        school_id=mapping.school_id,
        academic_year_id=mapping.academic_year_id,
        standard_id=mapping.standard_id,
        section_id=mapping.section_id,
        section_name=mapping.section_name,
        roll_number=mapping.roll_number,
        status=mapping.status,
        joined_on=mapping.joined_on,
        left_on=mapping.left_on,
        exit_reason=mapping.exit_reason,
        student_name=(
            mapping.student.user.full_name
            if mapping.student and mapping.student.user
            else None
        ),
        admission_number=mapping.student.admission_number if mapping.student else None,
        standard_name=mapping.standard.name if mapping.standard else None,
        academic_year_name=mapping.academic_year.name if mapping.academic_year else None,
        created_at=mapping.created_at,
        updated_at=mapping.updated_at,
    )


def get_service(db: AsyncSession = Depends(get_db)) -> EnrollmentService:
    return EnrollmentService(db)


@router.post("", response_model=StudentYearMappingResponse, status_code=201)
async def create_mapping(
    payload: StudentYearMappingCreate,
    current_user: CurrentUser = Depends(get_current_user),
    service: EnrollmentService = Depends(get_service),
):
    _require_school(current_user)
    if not _can_manage_enrollment(current_user):
        raise ForbiddenException(
            "Only staff admin/principal/super admin can create enrollment mappings."
        )
    mapping = await service.create_mapping(payload, current_user)
    return _to_response(mapping)


@router.patch("/mapping/{mapping_id}", response_model=StudentYearMappingResponse)
async def update_mapping(
    mapping_id: uuid.UUID,
    payload: StudentYearMappingUpdate,
    current_user: CurrentUser = Depends(get_current_user),
    service: EnrollmentService = Depends(get_service),
):
    _require_school(current_user)
    if not _can_manage_enrollment(current_user):
        raise ForbiddenException(
            "Only staff admin/principal/super admin can update enrollment mappings."
        )
    mapping = await service.update_mapping(mapping_id, payload, current_user)
    return _to_response(mapping)


@router.get("/mapping/{mapping_id}", response_model=StudentYearMappingResponse)
async def get_mapping(
    mapping_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    service: EnrollmentService = Depends(get_service),
):
    _require_school(current_user)
    mapping = await service.get_mapping(mapping_id, current_user)
    return _to_response(mapping)


@router.post("/mapping/{mapping_id}/exit", response_model=StudentYearMappingResponse)
async def exit_student(
    mapping_id: uuid.UUID,
    payload: StudentExitRequest,
    current_user: CurrentUser = Depends(get_current_user),
    service: EnrollmentService = Depends(get_service),
):
    _require_school(current_user)
    if not _can_manage_enrollment(current_user):
        raise ForbiddenException(
            "Only staff admin/principal/super admin can mark student exit."
        )
    mapping = await service.exit_student(mapping_id, payload, current_user)
    return _to_response(mapping)


@router.get("/roster", response_model=ClassRosterResponse)
async def get_roster(
    standard_id: uuid.UUID = Query(...),
    academic_year_id: uuid.UUID = Query(...),
    section_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    service: EnrollmentService = Depends(get_service),
):
    school_id = _require_school(current_user)
    return await service.get_class_roster(
        school_id=school_id,
        standard_id=standard_id,
        section_id=section_id,
        academic_year_id=academic_year_id,
    )


@router.post("/roll-numbers/assign")
async def assign_roll_numbers(
    payload: RollNumberAssignRequest,
    current_user: CurrentUser = Depends(get_current_user),
    service: EnrollmentService = Depends(get_service),
):
    _require_school(current_user)
    if not _can_manage_enrollment(current_user):
        raise ForbiddenException(
            "Only staff admin/principal/super admin can assign roll numbers."
        )
    return await service.assign_roll_numbers(payload, current_user)
