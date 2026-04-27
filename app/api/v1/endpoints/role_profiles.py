# app/api/v1/endpoints/role_profiles.py

import uuid
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.core.dependencies import CurrentUser, require_permission
from app.services.identifier import IdentifierService
from app.services.role_profile import RoleProfileService
from app.schemas.role_profile import (
    StudentProfileCreate, TeacherProfileCreate, ParentProfileCreate,
    StudentProfileResponse, TeacherProfileResponse, ParentProfileResponse,
    IdentifierConfigCreate, IdentifierConfigResponse, IdentifierPreviewResponse,
    RoleProfileListResponse,
)
from app.utils.enums import RoleEnum

router = APIRouter(prefix="/role-profiles", tags=["Role Profiles"])


def get_service(db: AsyncSession = Depends(get_db)) -> RoleProfileService:
    return RoleProfileService(db)


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
    role: str = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str = Query(None),
    current_user: CurrentUser = Depends(require_permission("user:manage")),
    service: RoleProfileService = Depends(get_service),
):
    return await service.list_profiles(
        school_id=current_user.school_id,
        role=role, page=page, page_size=page_size, search=search,
    )


@router.get("/{user_id}")
async def get_role_profile(
    user_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("user:manage")),
    service: RoleProfileService = Depends(get_service),
):
    return await service.get_profile_by_user(user_id, current_user.school_id)


# ── Identifier Configuration ───────────────────────────────────────────────

@router.post("/identifier-configs", response_model=IdentifierConfigResponse)
async def set_identifier_config(
    data: IdentifierConfigCreate,
    current_user: CurrentUser = Depends(require_permission("school:manage")),
    service: RoleProfileService = Depends(get_service),
):
    if current_user.role != RoleEnum.SUPERADMIN:
        raise ForbiddenException("Only Super Admin can configure identifier formats.")
    return await service.set_identifier_config(data, current_user)


@router.get("/identifier-configs", response_model=list[IdentifierConfigResponse])
async def get_identifier_configs(
    current_user: CurrentUser = Depends(require_permission("user:manage")),
    service: RoleProfileService = Depends(get_service),
):
    return await service.get_identifier_configs(current_user.school_id)


@router.post("/identifier-configs/preview", response_model=IdentifierPreviewResponse)
async def preview_next_identifier(
    data: dict,
    current_user: CurrentUser = Depends(require_permission("user:manage")),
    service: RoleProfileService = Depends(get_service),
):
    return await service.preview_next_identifier(
        current_user.school_id, data["identifier_type"]
    )