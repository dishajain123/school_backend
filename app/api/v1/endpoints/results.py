import uuid

from fastapi import APIRouter, Depends, BackgroundTasks, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, get_current_user, require_permission
from app.db.session import get_db
from app.schemas.result import (
    ExamCreate,
    ExamResponse,
    ResultBulkCreate,
    ResultListResponse,
    ReportCardResponse,
)
from app.services.result import ResultService

router = APIRouter(prefix="/results", tags=["Results"])


@router.post("/exams", response_model=ExamResponse, status_code=201)
async def create_exam(
    payload: ExamCreate,
    current_user: CurrentUser = Depends(require_permission("result:publish")),
    db: AsyncSession = Depends(get_db),
):
    return await ResultService(db).create_exam(payload, current_user)


@router.post("/entries", response_model=ResultListResponse, status_code=201)
async def bulk_enter_results(
    payload: ResultBulkCreate,
    current_user: CurrentUser = Depends(require_permission("result:create")),
    db: AsyncSession = Depends(get_db),
):
    return await ResultService(db).bulk_enter_results(payload, current_user)


@router.patch("/exams/{exam_id}/publish")
async def publish_exam(
    exam_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(require_permission("result:publish")),
    db: AsyncSession = Depends(get_db),
):
    updated = await ResultService(db).publish_exam(
        exam_id, current_user, background_tasks
    )
    return {"updated": updated}


@router.get("", response_model=ResultListResponse)
async def list_results(
    student_id: uuid.UUID = Query(...),
    exam_id: uuid.UUID = Query(...),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await ResultService(db).list_results(student_id, exam_id, current_user)


@router.get("/report-card/{student_id}", response_model=ReportCardResponse)
async def report_card(
    student_id: uuid.UUID,
    exam_id: uuid.UUID = Query(...),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await ResultService(db).generate_report_card(
        student_id=student_id,
        exam_id=exam_id,
        current_user=current_user,
    )
