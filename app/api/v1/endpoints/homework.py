import uuid
from datetime import date
from typing import Optional, Any

from fastapi import APIRouter, Depends, BackgroundTasks, Query, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_permission
from app.core.exceptions import ValidationException
from app.db.session import get_db
from app.schemas.homework import (
    HomeworkCreate,
    HomeworkResponse,
    HomeworkListResponse,
    HomeworkSubmissionCreate,
    HomeworkSubmissionResponse,
    HomeworkSubmissionListResponse,
    HomeworkSubmissionReview,
)
from app.services.homework import HomeworkService

router = APIRouter(prefix="/homework", tags=["Homework"])


def _is_multipart(request: Request) -> bool:
    content_type = (request.headers.get("content-type") or "").lower()
    return "multipart/form-data" in content_type


async def _parse_homework_create(
    request: Request,
) -> tuple[HomeworkCreate, Optional[UploadFile]]:
    payload: Any
    file: Optional[UploadFile] = None
    if _is_multipart(request):
        form = await request.form()
        payload = {
            "standard_id": form.get("standard_id"),
            "subject_id": form.get("subject_id"),
            "description": form.get("description"),
            "date": form.get("date"),
            "academic_year_id": form.get("academic_year_id"),
        }
        maybe_file = form.get("file")
        if isinstance(maybe_file, UploadFile) or (
            hasattr(maybe_file, "filename") and hasattr(maybe_file, "file")
        ):
            file = maybe_file
    else:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise ValidationException("Request body must be a JSON object")
    return HomeworkCreate.model_validate(payload), file


async def _parse_homework_submission(
    request: Request,
) -> tuple[HomeworkSubmissionCreate, Optional[UploadFile]]:
    payload: Any
    file: Optional[UploadFile] = None
    if _is_multipart(request):
        form = await request.form()
        payload = {
            "homework_id": form.get("homework_id"),
            "student_id": form.get("student_id"),
            "text_response": form.get("text_response"),
        }
        maybe_file = form.get("file")
        if isinstance(maybe_file, UploadFile) or (
            hasattr(maybe_file, "filename") and hasattr(maybe_file, "file")
        ):
            file = maybe_file
    else:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise ValidationException("Request body must be a JSON object")
    return HomeworkSubmissionCreate.model_validate(payload), file


@router.post("", response_model=HomeworkResponse, status_code=201)
async def create_homework(
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(require_permission("homework:create")),
    db: AsyncSession = Depends(get_db),
):
    """
    TEACHER only (`homework:create`).
    Creates a daily homework note with text and/or optional attachment.
    """
    payload, file = await _parse_homework_create(request)
    return await HomeworkService(db).create_homework(
        payload, current_user, background_tasks, file=file
    )


@router.get("", response_model=HomeworkListResponse)
async def list_homework(
    homework_date: Optional[date] = Query(None, alias="date"),
    standard_id: Optional[uuid.UUID] = Query(None),
    subject_id: Optional[uuid.UUID] = Query(None),
    academic_year_id: Optional[uuid.UUID] = Query(None),
    is_submitted: Optional[bool] = Query(
        None,
        description="Filter by submission status (role-aware)",
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: CurrentUser = Depends(require_permission("homework:read")),
    db: AsyncSession = Depends(get_db),
):
    """
    Students and parents see homework for their own class(es).
    Teachers see homework they created. Admin roles see all.
    """
    return await HomeworkService(db).list_homework(
        current_user=current_user,
        record_date=homework_date,
        standard_id=standard_id,
        subject_id=subject_id,
        academic_year_id=academic_year_id,
        is_submitted=is_submitted,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/responses",
    response_model=HomeworkSubmissionResponse,
    status_code=201,
)
async def create_homework_response(
    request: Request,
    current_user: CurrentUser = Depends(require_permission("submission:create")),
    db: AsyncSession = Depends(get_db),
):
    payload, file = await _parse_homework_submission(request)
    return await HomeworkService(db).create_submission(
        payload,
        current_user,
        file=file,
    )


@router.get(
    "/{homework_id}/responses",
    response_model=HomeworkSubmissionListResponse,
)
async def list_homework_responses(
    homework_id: uuid.UUID,
    student_id: Optional[uuid.UUID] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: CurrentUser = Depends(require_permission("homework:read")),
    db: AsyncSession = Depends(get_db),
):
    return await HomeworkService(db).list_submissions(
        homework_id=homework_id,
        current_user=current_user,
        student_id=student_id,
        page=page,
        page_size=page_size,
    )


@router.patch(
    "/responses/{submission_id}/review",
    response_model=HomeworkSubmissionResponse,
)
async def review_homework_response(
    submission_id: uuid.UUID,
    payload: HomeworkSubmissionReview,
    current_user: CurrentUser = Depends(require_permission("submission:grade")),
    db: AsyncSession = Depends(get_db),
):
    return await HomeworkService(db).review_submission(
        submission_id=submission_id,
        body=payload,
        current_user=current_user,
    )
