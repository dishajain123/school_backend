import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_permission
from app.core.exceptions import ForbiddenException
from app.db.session import get_db
from app.schemas.role_profile import (
    IdentifierConfigCreate,
    IdentifierConfigResponse,
    IdentifierPreviewRequest,
    IdentifierPreviewResponse,
    ParentProfileCreate,
    ParentProfileResponse,
    RoleProfileListResponse,
    StudentProfileCreate,
    StudentProfileResponse,
    TeacherProfileCreate,
    TeacherProfileResponse,
)
from app.services.role_profile import RoleProfileService
from app.utils.enums import RoleEnum

router = APIRouter(prefix="/role-profiles", tags=["Role Profiles"])


def get_service(db: AsyncSession = Depends(get_db)) -> RoleProfileService:
    return RoleProfileService(db)


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


@router.get("", response_model=RoleProfileListResponse)
async def list_role_profiles(
    role: Optional[str] = Query(None),
    school_id: Optional[uuid.UUID] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None),
    current_user: CurrentUser = Depends(require_permission("user:manage")),
    service: RoleProfileService = Depends(get_service),
):
    resolved_school_id = await service.resolve_school_scope(current_user, school_id)
    return await service.list_profiles(
        school_id=resolved_school_id,
        role=role,
        page=page,
        page_size=page_size,
        search=search,
    )


@router.post("/identifier-configs", response_model=IdentifierConfigResponse)
async def set_identifier_config(
    data: IdentifierConfigCreate,
    school_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(require_permission("user:manage")),
    service: RoleProfileService = Depends(get_service),
):
    if current_user.role != RoleEnum.SUPERADMIN and current_user.role != RoleEnum.PRINCIPAL:
        raise ForbiddenException("Only Principal or Super Admin can configure identifier formats.")
    return await service.set_identifier_config(data, current_user, school_id=school_id)


@router.get("/identifier-configs", response_model=list[IdentifierConfigResponse])
async def get_identifier_configs(
    school_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(require_permission("user:manage")),
    service: RoleProfileService = Depends(get_service),
):
    resolved_school_id = await service.resolve_school_scope(current_user, school_id)
    return await service.get_identifier_configs(resolved_school_id)


@router.post("/identifier-configs/preview", response_model=IdentifierPreviewResponse)
async def preview_next_identifier(
    data: IdentifierPreviewRequest,
    school_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(require_permission("user:manage")),
    service: RoleProfileService = Depends(get_service),
):
    resolved_school_id = await service.resolve_school_scope(current_user, school_id)
    return await service.preview_next_identifier(
        resolved_school_id,
        data.identifier_type.value,
    )


@router.get("/{user_id}")
async def get_role_profile(
    user_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("user:manage")),
    service: RoleProfileService = Depends(get_service),
):
    return await service.get_profile_by_user(user_id, current_user.school_id)
