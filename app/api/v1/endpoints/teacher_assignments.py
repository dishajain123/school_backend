import uuid
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.core.dependencies import CurrentUser, get_current_user
from app.core.exceptions import ValidationException, ForbiddenException
from app.services.teacher_class_subject import TeacherClassSubjectService
from app.schemas.teacher_class_subject import (
    TeacherAssignmentCreate,
    TeacherAssignmentResponse,
    TeacherAssignmentListResponse,
    TeacherSummary,
    StandardSummary,
    SubjectSummary,
    AcademicYearSummary,
)
from app.utils.enums import RoleEnum

router = APIRouter(prefix="/teacher-assignments", tags=["Teacher Assignments"])


def _require_school(current_user: CurrentUser) -> uuid.UUID:
    if not current_user.school_id:
        raise ValidationException("school_id is required")
    return current_user.school_id


def _can_manage_assignments(current_user: CurrentUser) -> bool:
    if "teacher_assignment:manage" in current_user.permissions:
        return True
    return current_user.role in (RoleEnum.PRINCIPAL, RoleEnum.SUPERADMIN)


def _to_response(obj) -> TeacherAssignmentResponse:
    return TeacherAssignmentResponse(
        id=obj.id,
        section=obj.section,
        teacher=TeacherSummary(
            id=obj.teacher.id,
            employee_code=obj.teacher.employee_code,
            user_id=obj.teacher.user_id,
        ),
        standard=StandardSummary(
            id=obj.standard.id,
            name=obj.standard.name,
            level=obj.standard.level,
        ),
        subject=SubjectSummary(
            id=obj.subject.id,
            name=obj.subject.name,
            code=obj.subject.code,
        ),
        academic_year=AcademicYearSummary(
            id=obj.academic_year.id,
            name=obj.academic_year.name,
        ),
        created_at=obj.created_at,
        updated_at=obj.updated_at,
    )


@router.post("", response_model=TeacherAssignmentResponse, status_code=201)
async def create_assignment(
    payload: TeacherAssignmentCreate,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not _can_manage_assignments(current_user):
        raise ForbiddenException(
            detail="Only principal/superadmin or users with 'teacher_assignment:manage' can assign teachers"
        )
    school_id = _require_school(current_user)
    service = TeacherClassSubjectService(db)
    obj = await service.create_assignment(payload, school_id)
    return _to_response(obj)


@router.get("/mine", response_model=TeacherAssignmentListResponse)
async def list_my_assignments(
    academic_year_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    school_id = _require_school(current_user)
    service = TeacherClassSubjectService(db)
    items, total = await service.list_mine(
        current_user=current_user,
        school_id=school_id,
        academic_year_id=academic_year_id,
    )
    return TeacherAssignmentListResponse(
        items=[_to_response(i) for i in items],
        total=total,
    )


@router.delete("/{assignment_id}", status_code=204)
async def delete_assignment(
    assignment_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not _can_manage_assignments(current_user):
        raise ForbiddenException(
            detail="Only principal/superadmin or users with 'teacher_assignment:manage' can remove assignments"
        )
    school_id = _require_school(current_user)
    service = TeacherClassSubjectService(db)
    await service.delete_assignment(assignment_id, school_id)


@router.get("", response_model=TeacherAssignmentListResponse)
async def list_assignments(
    teacher_id: Optional[uuid.UUID] = Query(None),
    standard_id: Optional[uuid.UUID] = Query(None),
    section: Optional[str] = Query(None),
    academic_year_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    school_id = _require_school(current_user)
    service = TeacherClassSubjectService(db)

    if teacher_id is not None:
        items, total = await service.list_by_teacher(
            teacher_id=teacher_id,
            school_id=school_id,
            academic_year_id=academic_year_id,
            current_user=current_user,
        )
    elif standard_id is not None and section is not None:
        items, total = await service.list_by_class(
            standard_id=standard_id,
            section=section,
            school_id=school_id,
            academic_year_id=academic_year_id,
        )
    else:
        raise ValidationException(
            "Provide either 'teacher_id' or both 'standard_id' and 'section' as query parameters"
        )

    return TeacherAssignmentListResponse(
        items=[_to_response(i) for i in items],
        total=total,
    )
