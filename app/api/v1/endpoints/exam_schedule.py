import uuid
from typing import Optional

from fastapi import APIRouter, Depends, BackgroundTasks, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_permission
from app.db.session import get_db
from app.schemas.exam_schedule import (
    ExamSeriesCreate,
    ExamSeriesResponse,
    ExamEntryCreate,
    ExamEntryResponse,
    ExamScheduleTable,
)
from app.services.exam_schedule import ExamScheduleService

router = APIRouter(prefix="/exam-schedule", tags=["Exam Schedule"])


@router.post("", response_model=ExamSeriesResponse, status_code=201)
async def create_series(
    payload: ExamSeriesCreate,
    current_user: CurrentUser = Depends(require_permission("exam_schedule:create")),
    db: AsyncSession = Depends(get_db),
):
    return await ExamScheduleService(db).create_series(payload, current_user)


@router.post("/{series_id}/entries", response_model=ExamEntryResponse, status_code=201)
async def add_entry(
    series_id: uuid.UUID,
    payload: ExamEntryCreate,
    current_user: CurrentUser = Depends(require_permission("exam_schedule:create")),
    db: AsyncSession = Depends(get_db),
):
    return await ExamScheduleService(db).add_entry(series_id, payload, current_user)


@router.patch("/{series_id}/publish", response_model=ExamSeriesResponse)
async def publish_series(
    series_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(require_permission("exam_schedule:create")),
    db: AsyncSession = Depends(get_db),
):
    return await ExamScheduleService(db).publish_series(
        series_id, current_user, background_tasks
    )


@router.patch("/entries/{entry_id}/cancel", response_model=ExamEntryResponse)
async def cancel_entry(
    entry_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("exam_schedule:create")),
    db: AsyncSession = Depends(get_db),
):
    return await ExamScheduleService(db).cancel_entry(entry_id, current_user)


@router.get("", response_model=ExamScheduleTable)
async def get_schedule(
    standard_id: uuid.UUID = Query(...),
    series_id: Optional[uuid.UUID] = Query(None),
    exam_id: Optional[uuid.UUID] = Query(None),
    section: Optional[str] = Query(None),
    current_user: CurrentUser = Depends(require_permission("exam_schedule:read")),
    db: AsyncSession = Depends(get_db),
):
    return await ExamScheduleService(db).get_schedule(
        standard_id=standard_id,
        series_id=series_id,
        exam_id=exam_id,
        section=section,
        current_user=current_user,
    )


@router.get("/series", response_model=list[ExamSeriesResponse])
async def list_series(
    standard_id: uuid.UUID = Query(...),
    academic_year_id: Optional[uuid.UUID] = Query(None),
    exam_id: Optional[uuid.UUID] = Query(None),
    section: Optional[str] = Query(None),
    current_user: CurrentUser = Depends(require_permission("exam_schedule:read")),
    db: AsyncSession = Depends(get_db),
):
    return await ExamScheduleService(db).list_series(
        standard_id=standard_id,
        academic_year_id=academic_year_id,
        exam_id=exam_id,
        section=section,
        current_user=current_user,
    )
