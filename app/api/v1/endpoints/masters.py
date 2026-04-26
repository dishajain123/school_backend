import uuid
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.core.dependencies import CurrentUser, get_current_user, require_permission
from app.core.exceptions import ForbiddenException, ValidationException
from app.services.masters import MastersService
from app.schemas.masters import (
    StandardCreate, StandardUpdate, StandardResponse, StandardListResponse,
    SubjectCreate, SubjectUpdate, SubjectResponse, SubjectListResponse,
    SectionCreate, SectionUpdate, SectionResponse, SectionListResponse,
    GradeMasterCreate, GradeMasterUpdate, GradeMasterResponse, GradeMasterListResponse,
    GradeLookupResponse,
)
from app.utils.enums import RoleEnum

router = APIRouter(prefix="/masters", tags=["Masters"])


def _require_school(current_user: CurrentUser) -> uuid.UUID:
    if not current_user.school_id:
        raise ValidationException("school_id is required")
    return current_user.school_id


def _resolve_school_scope(
    current_user: CurrentUser,
    school_id: Optional[uuid.UUID],
) -> uuid.UUID:
    if current_user.role == RoleEnum.SUPERADMIN:
        if school_id is None:
            raise ValidationException("school_id is required for superadmin")
        return school_id
    if current_user.school_id is None:
        raise ValidationException("school_id is required")
    if school_id is not None and school_id != current_user.school_id:
        raise ForbiddenException("Cannot operate on another school")
    return current_user.school_id


def _require_admin_for_structure(current_user: CurrentUser) -> None:
    if current_user.role not in (RoleEnum.PRINCIPAL, RoleEnum.SUPERADMIN):
        raise ForbiddenException(
            "Only Admin/Principal or Super Admin can manage classes and sections"
        )


def _require_staff_admin_for_subjects(current_user: CurrentUser) -> None:
    # Staff-admin function is represented by delegated manage permissions.
    if current_user.role in (RoleEnum.PRINCIPAL, RoleEnum.SUPERADMIN):
        return
    if "user:manage" not in current_user.permissions and "settings:manage" not in current_user.permissions:
        raise ForbiddenException(
            "Only Staff Admin, Admin/Principal, or Super Admin can maintain subjects"
        )


# ── Standards ─────────────────────────────────────────────────────────────────

@router.post("/standards", response_model=StandardResponse, status_code=201)
async def create_standard(
    payload: StandardCreate,
    school_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_admin_for_structure(current_user)
    school_id = _resolve_school_scope(current_user, school_id)
    service = MastersService(db)
    return await service.create_standard(payload, school_id)


@router.get("/standards", response_model=StandardListResponse)
async def list_standards(
    academic_year_id: Optional[uuid.UUID] = Query(None),
    school_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    school_id = _resolve_school_scope(current_user, school_id)
    service = MastersService(db)
    items, total = await service.list_standards(school_id, academic_year_id)
    return StandardListResponse(items=items, total=total)


@router.patch("/standards/{standard_id}", response_model=StandardResponse)
async def update_standard(
    standard_id: uuid.UUID,
    payload: StandardUpdate,
    school_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_admin_for_structure(current_user)
    school_id = _resolve_school_scope(current_user, school_id)
    service = MastersService(db)
    return await service.update_standard(standard_id, payload, school_id)


@router.delete("/standards/{standard_id}", status_code=204)
async def delete_standard(
    standard_id: uuid.UUID,
    school_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_admin_for_structure(current_user)
    school_id = _resolve_school_scope(current_user, school_id)
    service = MastersService(db)
    await service.delete_standard(standard_id, school_id)


# ── Subjects ──────────────────────────────────────────────────────────────────

@router.post("/subjects", response_model=SubjectResponse, status_code=201)
async def create_subject(
    payload: SubjectCreate,
    school_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_staff_admin_for_subjects(current_user)
    school_id = _resolve_school_scope(current_user, school_id)
    service = MastersService(db)
    return await service.create_subject(payload, school_id)


@router.get("/subjects", response_model=SubjectListResponse)
async def list_subjects(
    standard_id: Optional[uuid.UUID] = Query(None),
    school_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    school_id = _resolve_school_scope(current_user, school_id)
    service = MastersService(db)
    items, total = await service.list_subjects(school_id, standard_id)
    return SubjectListResponse(items=items, total=total)


@router.patch("/subjects/{subject_id}", response_model=SubjectResponse)
async def update_subject(
    subject_id: uuid.UUID,
    payload: SubjectUpdate,
    school_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_staff_admin_for_subjects(current_user)
    school_id = _resolve_school_scope(current_user, school_id)
    service = MastersService(db)
    return await service.update_subject(subject_id, payload, school_id)


@router.delete("/subjects/{subject_id}", status_code=204)
async def delete_subject(
    subject_id: uuid.UUID,
    school_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_staff_admin_for_subjects(current_user)
    school_id = _resolve_school_scope(current_user, school_id)
    service = MastersService(db)
    await service.delete_subject(subject_id, school_id)


# ── Sections ─────────────────────────────────────────────────────────────────

@router.post("/sections", response_model=SectionResponse, status_code=201)
async def create_section(
    payload: SectionCreate,
    school_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_admin_for_structure(current_user)
    school_id = _resolve_school_scope(current_user, school_id)
    service = MastersService(db)
    return await service.create_section(payload, school_id)


@router.get("/sections", response_model=SectionListResponse)
async def list_sections(
    standard_id: Optional[uuid.UUID] = Query(None),
    academic_year_id: Optional[uuid.UUID] = Query(None),
    include_inactive: bool = Query(False),
    school_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    school_id = _resolve_school_scope(current_user, school_id)
    service = MastersService(db)
    items, total = await service.list_sections(
        school_id=school_id,
        standard_id=standard_id,
        academic_year_id=academic_year_id,
        include_inactive=include_inactive,
    )
    return SectionListResponse(items=items, total=total)


@router.patch("/sections/{section_id}", response_model=SectionResponse)
async def update_section(
    section_id: uuid.UUID,
    payload: SectionUpdate,
    school_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_admin_for_structure(current_user)
    school_id = _resolve_school_scope(current_user, school_id)
    service = MastersService(db)
    return await service.update_section(section_id, payload, school_id)


@router.delete("/sections/{section_id}", status_code=204)
async def delete_section(
    section_id: uuid.UUID,
    school_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_admin_for_structure(current_user)
    school_id = _resolve_school_scope(current_user, school_id)
    service = MastersService(db)
    await service.delete_section(section_id, school_id)


# ── Grade Master ──────────────────────────────────────────────────────────────

@router.post("/grades", response_model=GradeMasterResponse, status_code=201)
async def create_grade(
    payload: GradeMasterCreate,
    school_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(require_permission("user:manage")),
    db: AsyncSession = Depends(get_db),
):
    school_id = _resolve_school_scope(current_user, school_id)
    service = MastersService(db)
    return await service.create_grade(payload, school_id)


@router.get("/grades", response_model=GradeMasterListResponse)
async def list_grades(
    school_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    school_id = _resolve_school_scope(current_user, school_id)
    service = MastersService(db)
    items, total = await service.list_grades(school_id)
    return GradeMasterListResponse(items=items, total=total)


@router.get("/grades/lookup", response_model=GradeLookupResponse)
async def lookup_grade(
    percent: float = Query(..., ge=0, le=100),
    school_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    school_id = _resolve_school_scope(current_user, school_id)
    service = MastersService(db)
    grade = await service.lookup_grade_by_percent(school_id, percent)
    return GradeLookupResponse(
        percent=percent,
        grade_letter=grade.grade_letter,
        grade_point=float(grade.grade_point),
    )


@router.patch("/grades/{grade_id}", response_model=GradeMasterResponse)
async def update_grade(
    grade_id: uuid.UUID,
    payload: GradeMasterUpdate,
    school_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(require_permission("user:manage")),
    db: AsyncSession = Depends(get_db),
):
    school_id = _resolve_school_scope(current_user, school_id)
    service = MastersService(db)
    return await service.update_grade(grade_id, payload, school_id)


@router.delete("/grades/{grade_id}", status_code=204)
async def delete_grade(
    grade_id: uuid.UUID,
    school_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(require_permission("user:manage")),
    db: AsyncSession = Depends(get_db),
):
    school_id = _resolve_school_scope(current_user, school_id)
    service = MastersService(db)
    await service.delete_grade(grade_id, school_id)
