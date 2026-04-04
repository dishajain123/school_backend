import uuid
from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, Query
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_permission
from app.core.exceptions import ValidationException
from app.db.session import get_db
from app.schemas.diary import DiaryCreate, DiaryResponse, DiaryListResponse
from app.services.diary import DiaryService

router = APIRouter(prefix="/diary", tags=["Diary"])


@router.post("/create", response_model=DiaryResponse, status_code=201)
async def create_diary_entry_explicit(
    body: DiaryCreate,
    current_user: CurrentUser = Depends(require_permission("diary:create")),
    db: AsyncSession = Depends(get_db),
):
    """
    Explicit typed create route kept for compatibility with strict body validators.
    """
    return await DiaryService(db).create_entry(body, current_user)


@router.post("", response_model=DiaryResponse, status_code=201)
async def create_diary_entry(
    payload: Any = Body(None),
    current_user: CurrentUser = Depends(require_permission("diary:create")),
    db: AsyncSession = Depends(get_db),
):
    """
    TEACHER only (`diary:create`).
    Creates a daily class diary entry for a subject.
    """
    if payload is None:
        raise ValidationException("Diary payload is required")

    # Support both payload shapes:
    # 1) { ...fields... }
    # 2) { "payload": { ...fields... } }
    normalized: Any = payload
    if isinstance(payload, dict):
        raw_payload = payload.get("payload")
        if isinstance(raw_payload, dict):
            normalized = raw_payload

    if isinstance(normalized, DiaryCreate):
        body = normalized
    elif isinstance(normalized, dict) and normalized:
        try:
            body = DiaryCreate.model_validate(normalized)
        except ValidationError as exc:
            first = exc.errors()[0] if exc.errors() else {}
            msg = first.get("msg") or "Invalid diary payload"
            raise ValidationException(msg)
    else:
        raise ValidationException("Invalid diary payload")

    return await DiaryService(db).create_entry(body, current_user)


@router.get("", response_model=DiaryListResponse)
async def list_diary_entries(
    diary_date: Optional[date] = Query(None, alias="date"),
    standard_id: Optional[uuid.UUID] = Query(None),
    subject_id: Optional[uuid.UUID] = Query(None),
    academic_year_id: Optional[uuid.UUID] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: CurrentUser = Depends(require_permission("diary:read")),
    db: AsyncSession = Depends(get_db),
):
    """
    Students and parents see diary for their own class(es).
    Teachers see diary entries they created. Admin roles see all.
    """
    return await DiaryService(db).list_entries(
        current_user=current_user,
        record_date=diary_date,
        standard_id=standard_id,
        subject_id=subject_id,
        academic_year_id=academic_year_id,
        page=page,
        page_size=page_size,
    )
