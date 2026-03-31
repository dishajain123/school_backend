import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, BackgroundTasks, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_permission
from app.db.session import get_db
from app.schemas.homework import HomeworkCreate, HomeworkResponse, HomeworkListResponse
from app.services.homework import HomeworkService

router = APIRouter(prefix="/homework", tags=["Homework"])


@router.post("", response_model=HomeworkResponse, status_code=201)
async def create_homework(
    payload: HomeworkCreate,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(require_permission("homework:create")),
    db: AsyncSession = Depends(get_db),
):
    """
    TEACHER only (`homework:create`).
    Creates a daily homework note (no file uploads, no grading).
    """
    return await HomeworkService(db).create_homework(
        payload, current_user, background_tasks
    )


@router.get("", response_model=HomeworkListResponse)
async def list_homework(
    homework_date: Optional[date] = Query(None, alias="date"),
    standard_id: Optional[uuid.UUID] = Query(None),
    subject_id: Optional[uuid.UUID] = Query(None),
    academic_year_id: Optional[uuid.UUID] = Query(None),
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
        page=page,
        page_size=page_size,
    )
