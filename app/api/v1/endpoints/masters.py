import uuid
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.core.dependencies import CurrentUser, get_current_user, require_permission
from app.core.exceptions import ValidationException
from app.services.masters import MastersService
from app.schemas.masters import (
    StandardCreate, StandardUpdate, StandardResponse, StandardListResponse,
    SubjectCreate, SubjectUpdate, SubjectResponse, SubjectListResponse,
    GradeMasterCreate, GradeMasterUpdate, GradeMasterResponse, GradeMasterListResponse,
    GradeLookupResponse,
)

router = APIRouter(prefix="/masters", tags=["Masters"])


def _require_school(current_user: CurrentUser) -> uuid.UUID:
    if not current_user.school_id:
        raise ValidationException("school_id is required")
    return current_user.school_id


# ── Standards ─────────────────────────────────────────────────────────────────

@router.post("/standards", response_model=StandardResponse, status_code=201)
async def create_standard(
    payload: StandardCreate,
    current_user: CurrentUser = Depends(require_permission("user:manage")),
    db: AsyncSession = Depends(get_db),
):
    school_id = _require_school(current_user)
    service = MastersService(db)
    return await service.create_standard(payload, school_id)


@router.get("/standards", response_model=StandardListResponse)
async def list_standards(
    academic_year_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    school_id = _require_school(current_user)
    service = MastersService(db)
    items, total = await service.list_standards(school_id, academic_year_id)
    return StandardListResponse(items=items, total=total)


@router.get("/standards/{standard_id}", response_model=StandardResponse)
async def get_standard(
    standard_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    school_id = _require_school(current_user)
    service = MastersService(db)
    return await service.get_standard(standard_id, school_id)


@router.patch("/standards/{standard_id}", response_model=StandardResponse)
async def update_standard(
    standard_id: uuid.UUID,
    payload: StandardUpdate,
    current_user: CurrentUser = Depends(require_permission("user:manage")),
    db: AsyncSession = Depends(get_db),
):
    school_id = _require_school(current_user)
    service = MastersService(db)
    return await service.update_standard(standard_id, payload, school_id)


@router.delete("/standards/{standard_id}", status_code=204)
async def delete_standard(
    standard_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("user:manage")),
    db: AsyncSession = Depends(get_db),
):
    school_id = _require_school(current_user)
    service = MastersService(db)
    await service.delete_standard(standard_id, school_id)


# ── Subjects ──────────────────────────────────────────────────────────────────

@router.post("/subjects", response_model=SubjectResponse, status_code=201)
async def create_subject(
    payload: SubjectCreate,
    current_user: CurrentUser = Depends(require_permission("user:manage")),
    db: AsyncSession = Depends(get_db),
):
    school_id = _require_school(current_user)
    service = MastersService(db)
    return await service.create_subject(payload, school_id)


@router.get("/subjects", response_model=SubjectListResponse)
async def list_subjects(
    standard_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    school_id = _require_school(current_user)
    service = MastersService(db)
    items, total = await service.list_subjects(school_id, standard_id)
    return SubjectListResponse(items=items, total=total)


@router.get("/subjects/{subject_id}", response_model=SubjectResponse)
async def get_subject(
    subject_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    school_id = _require_school(current_user)
    service = MastersService(db)
    return await service.get_subject(subject_id, school_id)


@router.patch("/subjects/{subject_id}", response_model=SubjectResponse)
async def update_subject(
    subject_id: uuid.UUID,
    payload: SubjectUpdate,
    current_user: CurrentUser = Depends(require_permission("user:manage")),
    db: AsyncSession = Depends(get_db),
):
    school_id = _require_school(current_user)
    service = MastersService(db)
    return await service.update_subject(subject_id, payload, school_id)


@router.delete("/subjects/{subject_id}", status_code=204)
async def delete_subject(
    subject_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("user:manage")),
    db: AsyncSession = Depends(get_db),
):
    school_id = _require_school(current_user)
    service = MastersService(db)
    await service.delete_subject(subject_id, school_id)


# ── Grade Master ──────────────────────────────────────────────────────────────

@router.post("/grades", response_model=GradeMasterResponse, status_code=201)
async def create_grade(
    payload: GradeMasterCreate,
    current_user: CurrentUser = Depends(require_permission("user:manage")),
    db: AsyncSession = Depends(get_db),
):
    school_id = _require_school(current_user)
    service = MastersService(db)
    return await service.create_grade(payload, school_id)


@router.get("/grades", response_model=GradeMasterListResponse)
async def list_grades(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    school_id = _require_school(current_user)
    service = MastersService(db)
    items, total = await service.list_grades(school_id)
    return GradeMasterListResponse(items=items, total=total)


@router.get("/grades/lookup", response_model=GradeLookupResponse)
async def lookup_grade(
    percent: float = Query(..., ge=0, le=100),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    school_id = _require_school(current_user)
    service = MastersService(db)
    grade = await service.lookup_grade_by_percent(school_id, percent)
    return GradeLookupResponse(
        percent=percent,
        grade_letter=grade.grade_letter,
        grade_point=float(grade.grade_point),
    )


@router.get("/grades/{grade_id}", response_model=GradeMasterResponse)
async def get_grade(
    grade_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    school_id = _require_school(current_user)
    service = MastersService(db)
    return await service.get_grade(grade_id, school_id)


@router.patch("/grades/{grade_id}", response_model=GradeMasterResponse)
async def update_grade(
    grade_id: uuid.UUID,
    payload: GradeMasterUpdate,
    current_user: CurrentUser = Depends(require_permission("user:manage")),
    db: AsyncSession = Depends(get_db),
):
    school_id = _require_school(current_user)
    service = MastersService(db)
    return await service.update_grade(grade_id, payload, school_id)


@router.delete("/grades/{grade_id}", status_code=204)
async def delete_grade(
    grade_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("user:manage")),
    db: AsyncSession = Depends(get_db),
):
    school_id = _require_school(current_user)
    service = MastersService(db)
    await service.delete_grade(grade_id, school_id)