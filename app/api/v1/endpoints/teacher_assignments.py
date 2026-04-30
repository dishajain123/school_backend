import uuid
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_db
from app.core.dependencies import CurrentUser, get_current_user
from app.core.exceptions import ValidationException, ForbiddenException
from app.models.school import School
from app.services.teacher_class_subject import TeacherClassSubjectService
from app.repositories.masters import SectionRepository
from app.schemas.teacher_class_subject import (
    TeacherAssignmentCreate,
    TeacherAssignmentUpdate,
    TeacherAssignmentResponse,
    TeacherAssignmentListResponse,
    TeacherSummary,
    StandardSummary,
    SubjectSummary,
    AcademicYearSummary,
)
from app.utils.enums import RoleEnum

router = APIRouter(prefix="/teacher-assignments", tags=["Teacher Assignments"])


async def _resolve_school_scope(current_user: CurrentUser, db: AsyncSession) -> uuid.UUID:
    if current_user.school_id is not None:
        return current_user.school_id
    row = await db.execute(
        select(School.id).where(School.is_active.is_(True)).order_by(School.created_at.asc())
    )
    sid = row.scalar_one_or_none()
    if sid is None:
        raise ValidationException("No active school configured")
    return sid


def _can_manage_assignments(current_user: CurrentUser) -> bool:
    if "teacher_assignment:manage" in current_user.permissions:
        return True
    return current_user.role in (RoleEnum.PRINCIPAL, RoleEnum.SUPERADMIN)


async def _resolve_or_create_section_id(obj, db: AsyncSession) -> Optional[uuid.UUID]:
    section_name = (obj.section or "").strip().upper()
    if not section_name:
        return None

    section_repo = SectionRepository(db)
    existing = await section_repo.get_by_key(
        school_id=obj.standard.school_id,
        standard_id=obj.standard_id,
        academic_year_id=obj.academic_year_id,
        name=section_name,
    )
    if existing:
        return existing.id

    created = await section_repo.create(
        {
            "school_id": obj.standard.school_id,
            "standard_id": obj.standard_id,
            "academic_year_id": obj.academic_year_id,
            "name": section_name,
            "is_active": True,
            "capacity": None,
        }
    )
    await db.flush()
    return created.id


async def _to_response(obj, db: AsyncSession) -> TeacherAssignmentResponse:
    section_id = await _resolve_or_create_section_id(obj, db)
    return TeacherAssignmentResponse(
        id=obj.id,
        section=obj.section,
        section_id=section_id,
        teacher=TeacherSummary(
            id=obj.teacher.id,
            employee_code=obj.teacher.employee_code,
            user_id=obj.teacher.user_id,
            full_name=getattr(getattr(obj.teacher, "user", None), "full_name", None),
            email=getattr(getattr(obj.teacher, "user", None), "email", None),
            phone=getattr(getattr(obj.teacher, "user", None), "phone", None),
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
    school_id = await _resolve_school_scope(current_user, db)
    service = TeacherClassSubjectService(db)
    obj = await service.create_assignment(payload, school_id)
    response = await _to_response(obj, db)
    await db.commit()
    return response


@router.get("/mine", response_model=TeacherAssignmentListResponse)
async def list_my_assignments(
    academic_year_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    school_id = await _resolve_school_scope(current_user, db)
    service = TeacherClassSubjectService(db)
    items, total = await service.list_mine(
        current_user=current_user,
        school_id=school_id,
        academic_year_id=academic_year_id,
    )
    responses = [await _to_response(i, db) for i in items]
    await db.commit()
    return TeacherAssignmentListResponse(
        items=responses,
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
    school_id = await _resolve_school_scope(current_user, db)
    service = TeacherClassSubjectService(db)
    await service.delete_assignment(assignment_id, school_id)


@router.patch("/{assignment_id}", response_model=TeacherAssignmentResponse)
async def update_assignment(
    assignment_id: uuid.UUID,
    payload: TeacherAssignmentUpdate,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not _can_manage_assignments(current_user):
        raise ForbiddenException(
            detail="Only principal/superadmin or users with 'teacher_assignment:manage' can update assignments"
        )
    school_id = await _resolve_school_scope(current_user, db)
    service = TeacherClassSubjectService(db)
    obj = await service.update_assignment(assignment_id, payload, school_id)
    response = await _to_response(obj, db)
    await db.commit()
    return response


@router.get("", response_model=TeacherAssignmentListResponse)
async def list_assignments(
    teacher_id: Optional[uuid.UUID] = Query(None),
    standard_id: Optional[uuid.UUID] = Query(None),
    section: Optional[str] = Query(None),
    academic_year_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    school_id = await _resolve_school_scope(current_user, db)
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
    elif standard_id is not None:
        items, total = await service.list_by_standard(
            standard_id=standard_id,
            school_id=school_id,
            academic_year_id=academic_year_id,
        )
    else:
        raise ValidationException(
            "Provide either 'teacher_id', or 'standard_id' (optional 'section') as query parameters"
        )

    responses = [await _to_response(i, db) for i in items]
    await db.commit()
    return TeacherAssignmentListResponse(items=responses, total=total)
