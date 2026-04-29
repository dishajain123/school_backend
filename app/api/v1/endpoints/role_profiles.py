# app/api/v1/endpoints/role_profiles.py

import uuid
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_db
from app.core.dependencies import CurrentUser, require_permission, get_current_user
from app.core.exceptions import ForbiddenException
from app.models.school import School
from app.services.role_profile import RoleProfileService
from app.schemas.role_profile import (
    StudentProfileCreate, TeacherProfileCreate, ParentProfileCreate,
    StudentProfileResponse, TeacherProfileResponse, ParentProfileResponse,
    RoleProfileListResponse,
)
from app.utils.enums import RoleEnum

router = APIRouter(prefix="/role-profiles", tags=["Role Profiles"])


def get_service(db: AsyncSession = Depends(get_db)) -> RoleProfileService:
    return RoleProfileService(db)


async def _resolve_school_scope(
    current_user: CurrentUser,
    db: AsyncSession,
) -> Optional[uuid.UUID]:
    if current_user.school_id is not None:
        return current_user.school_id
    row = await db.execute(
        select(School.id).where(School.is_active.is_(True)).order_by(School.created_at.asc())
    )
    sid = row.scalar_one_or_none()
    return sid


def _can_view_profiles(current_user: CurrentUser) -> bool:
    if current_user.role in (
        RoleEnum.SUPERADMIN,
        RoleEnum.PRINCIPAL,
        RoleEnum.STAFF_ADMIN,
    ):
        return True
    perms = set(current_user.permissions or [])
    return (
        "user:manage" in perms
        or "settings:manage" in perms
        or "teacher_assignment:manage" in perms
        or "enrollment:read" in perms
        or "enrollment:update" in perms
        or "enrollment:create" in perms
        or "student:promote" in perms
    )


# ── Create Profiles ────────────────────────────────────────────────────────

@router.post("/student", response_model=StudentProfileResponse, status_code=201)
async def create_student_profile(
    data: StudentProfileCreate,
    current_user: CurrentUser = Depends(require_permission("user:manage")),
    service: RoleProfileService = Depends(get_service),
):
    return await service.create_student_profile(data, current_user)


@router.post("/teacher", response_model=TeacherProfileResponse, status_code=201)
async def create_teacher_profile(
    data: TeacherProfileCreate,
    current_user: CurrentUser = Depends(require_permission("user:manage")),
    service: RoleProfileService = Depends(get_service),
):
    return await service.create_teacher_profile(data, current_user)


@router.post("/parent", response_model=ParentProfileResponse, status_code=201)
async def create_parent_profile(
    data: ParentProfileCreate,
    current_user: CurrentUser = Depends(require_permission("user:manage")),
    service: RoleProfileService = Depends(get_service),
):
    return await service.create_parent_profile(data, current_user)


# ── Query Profiles ─────────────────────────────────────────────────────────

@router.get("", response_model=RoleProfileListResponse)
async def list_role_profiles(
    role: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None),
    academic_year_id: Optional[uuid.UUID] = Query(None),
    standard_id: Optional[uuid.UUID] = Query(None),
    section: Optional[str] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    service: RoleProfileService = Depends(get_service),
):
    if not _can_view_profiles(current_user):
        raise ForbiddenException("You do not have permission to view role profiles")
    school_id = await _resolve_school_scope(current_user, service.db)
    return await service.list_profiles(
        school_id=school_id,
        role=role,
        page=page,
        page_size=page_size,
        search=search,
        academic_year_id=academic_year_id,
        standard_id=standard_id,
        section=section,
    )


@router.get("/{user_id}")
async def get_role_profile(
    user_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    service: RoleProfileService = Depends(get_service),
):
    if not _can_view_profiles(current_user):
        raise ForbiddenException("You do not have permission to view role profiles")
    school_id = await _resolve_school_scope(current_user, service.db)
    return await service.get_profile_by_user(user_id, school_id)
