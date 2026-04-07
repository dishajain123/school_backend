import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_permission
from app.core.exceptions import ValidationException
from app.db.session import get_db
from app.schemas.diary import DiaryCreate, DiaryResponse, DiaryListResponse
from app.services.diary import DiaryService

router = APIRouter(prefix="/diary", tags=["Diary"])


async def _parse_diary_body(request: Request) -> DiaryCreate:
    try:
        payload = await request.json()
    except Exception:
        raise ValidationException("Request body must be valid JSON")

    if payload is None:
        raise ValidationException("Request body is required")
    if not isinstance(payload, dict):
        raise ValidationException("Request body must be a JSON object")

    try:
        return DiaryCreate.model_validate(payload)
    except ValidationError as exc:
        first_error = exc.errors()[0] if exc.errors() else {}
        message = first_error.get("msg") or "Validation failed"
        raise ValidationException(message)


@router.post("/create", response_model=DiaryResponse, status_code=201)
async def create_diary_entry_explicit(
    request: Request,
    current_user: CurrentUser = Depends(require_permission("diary:create")),
    db: AsyncSession = Depends(get_db),
):
    """
    Explicit typed create route kept for compatibility with strict body validators.
    """
    body = await _parse_diary_body(request)
    return await DiaryService(db).create_entry(body, current_user)


@router.post("", response_model=DiaryResponse, status_code=201)
async def create_diary_entry(
    request: Request,
    current_user: CurrentUser = Depends(require_permission("diary:create")),
    db: AsyncSession = Depends(get_db),
):
    """
    TEACHER only (`diary:create`).
    Creates a daily class diary entry for a subject.
    """
    body = await _parse_diary_body(request)
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
