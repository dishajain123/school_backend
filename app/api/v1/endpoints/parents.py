import uuid
import math
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.core.dependencies import (
    CurrentUser,
    get_current_user,
    require_permission,
    inject_school_id,
)
from app.core.exceptions import ValidationException
from app.services.parent import ParentService
from app.schemas.parent import (
    ParentCreate,
    ParentUpdate,
    ParentResponse,
    ParentListResponse,
    ParentChildrenResponse,
    ChildSummary,
)

router = APIRouter(prefix="/parents", tags=["Parents"])


@router.post("", response_model=ParentResponse, status_code=201)
async def create_parent(
    payload: ParentCreate,
    current_user: CurrentUser = Depends(require_permission("user:manage")),
    db: AsyncSession = Depends(get_db),
):
    if not current_user.school_id:
        raise ValidationException("school_id is required")

    service = ParentService(db)
    parent = await service.create_parent(payload, current_user.school_id, current_user)
    return _to_response(parent)


@router.get("/me/children", response_model=ParentChildrenResponse)
async def get_my_children(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = ParentService(db)
    parent_id, children = await service.get_my_children(current_user)
    return ParentChildrenResponse(
        parent_id=parent_id,
        children=[ChildSummary.model_validate(c) for c in children],
        total=len(children),
    )


@router.get("", response_model=ParentListResponse)
async def list_parents(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: CurrentUser = Depends(require_permission("user:manage")),
    db: AsyncSession = Depends(get_db),
):
    if not current_user.school_id:
        raise ValidationException("school_id is required")

    service = ParentService(db)
    parents, total = await service.list_parents(current_user.school_id, page, page_size)
    return ParentListResponse(
        items=[_to_response(p) for p in parents],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=math.ceil(total / page_size) if total else 0,
    )


@router.get("/{parent_id}", response_model=ParentResponse)
async def get_parent(
    parent_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = ParentService(db)
    parent = await service.get_parent(parent_id, current_user)
    return _to_response(parent)


@router.patch("/{parent_id}", response_model=ParentResponse)
async def update_parent(
    parent_id: uuid.UUID,
    payload: ParentUpdate,
    current_user: CurrentUser = Depends(require_permission("user:manage")),
    db: AsyncSession = Depends(get_db),
):
    service = ParentService(db)
    parent = await service.update_parent(parent_id, payload, current_user)
    return _to_response(parent)


@router.get("/{parent_id}/children", response_model=ParentChildrenResponse)
async def get_parent_children(
    parent_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = ParentService(db)
    pid, children = await service.get_children(parent_id, current_user)
    return ParentChildrenResponse(
        parent_id=pid,
        children=[ChildSummary.model_validate(c) for c in children],
        total=len(children),
    )


# ── Internal helper ───────────────────────────────────────────────────────────

def _to_response(parent) -> ParentResponse:
    from app.schemas.parent import ParentUserResponse

    user_resp = ParentUserResponse(
        id=parent.user.id,
        email=parent.user.email,
        phone=parent.user.phone,
        is_active=parent.user.is_active,
        profile_photo_key=parent.user.profile_photo_key,
        profile_photo_url=None,  # presigned URL generation can be added here if needed
    )
    return ParentResponse(
        id=parent.id,
        school_id=parent.school_id,
        occupation=parent.occupation,
        relation=parent.relation,
        user=user_resp,
        created_at=parent.created_at,
        updated_at=parent.updated_at,
    )