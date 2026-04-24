import uuid
from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, Query
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_permission
from app.core.exceptions import ValidationException
from app.core.logging import get_logger
from app.db.session import get_db
from app.schemas.diary import DiaryCreate, DiaryResponse, DiaryListResponse
from app.services.diary import DiaryService

router = APIRouter(prefix="/diary", tags=["Diary"])
logger = get_logger(__name__)


def _sanitize_payload(payload: dict) -> dict:
    optional_fields = {"academic_year_id", "date", "homework_note"}
    sanitized = {}
    for k, v in payload.items():
        if k in optional_fields and isinstance(v, str) and not v.strip():
            sanitized[k] = None
        else:
            sanitized[k] = v
    return sanitized


def _parse_diary_body(payload: Any) -> DiaryCreate:
    if payload is None:
        raise ValidationException("Request body is required")

    if (
        isinstance(payload, dict)
        and "input" in payload
        and isinstance(payload["input"], dict)
    ):
        payload = payload["input"]

    if not isinstance(payload, dict):
        raise ValidationException("Request body must be a JSON object")

    payload = _sanitize_payload(payload)

    try:
        return DiaryCreate.model_validate(payload)
    except ValidationError as exc:
        errors = exc.errors()
        # Keep structured details in server logs for troubleshooting.
        for e in errors:
            logger.warning(
                "DiaryCreate validation error loc=%s msg=%s input=%s",
                e.get("loc"),
                e.get("msg"),
                e.get("input"),
            )
        first_error = errors[0] if errors else {}
        msg = first_error.get("msg") or "Validation failed"
        if msg.lower().startswith("value error, "):
            msg = msg[len("value error, "):]
        raise ValidationException(msg)


@router.post("", response_model=DiaryResponse, status_code=201)
async def create_diary_entry(
    payload: Any = Body(...),
    current_user: CurrentUser = Depends(require_permission("diary:create")),
    db: AsyncSession = Depends(get_db),
):
    body = _parse_diary_body(payload)
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
    return await DiaryService(db).list_entries(
        current_user=current_user,
        record_date=diary_date,
        standard_id=standard_id,
        subject_id=subject_id,
        academic_year_id=academic_year_id,
        page=page,
        page_size=page_size,
    )
