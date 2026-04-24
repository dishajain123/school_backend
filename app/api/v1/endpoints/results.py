import uuid
from typing import Optional

from fastapi import APIRouter, Depends, BackgroundTasks, Query, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, get_current_user, require_permission
from app.db.session import get_db
from app.schemas.result import (
    ExamCreate,
    ExamBulkCreate,
    ExamBulkCreateResponse,
    ExamResponse,
    ResultBulkCreate,
    ResultListResponse,
    ResultDistributionResponse,
    ReportCardResponse,
    ReportCardUploadResponse,
)
from app.services.result import ResultService

router = APIRouter(prefix="/results", tags=["Results"])


@router.post("/exams", response_model=ExamResponse, status_code=201)
async def create_exam(
    payload: ExamCreate,
    current_user: CurrentUser = Depends(require_permission("result:create")),
    db: AsyncSession = Depends(get_db),
):
    return await ResultService(db).create_exam(payload, current_user)


@router.post("/exams/bulk", response_model=ExamBulkCreateResponse, status_code=201)
async def create_exam_bulk(
    payload: ExamBulkCreate,
    current_user: CurrentUser = Depends(require_permission("result:create")),
    db: AsyncSession = Depends(get_db),
):
    return await ResultService(db).create_exams_bulk(payload, current_user)


@router.get("/exams", response_model=list[ExamResponse])
async def list_exams(
    student_id: Optional[uuid.UUID] = Query(None),
    academic_year_id: Optional[uuid.UUID] = Query(None),
    standard_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await ResultService(db).list_exams(
        current_user=current_user,
        student_id=student_id,
        academic_year_id=academic_year_id,
        standard_id=standard_id,
    )


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


@router.get("/exams/{exam_id}/distribution", response_model=ResultDistributionResponse)
async def exam_distribution(
    exam_id: uuid.UUID,
    section: Optional[str] = Query(None),
    student_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await ResultService(db).exam_distribution(
        exam_id,
        current_user,
        section=section,
        student_id=student_id,
    )


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


@router.post("/report-card/upload", response_model=ReportCardUploadResponse, status_code=201)
async def upload_report_card(
    student_id: uuid.UUID = Form(...),
    exam_id: uuid.UUID = Form(...),
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(require_permission("result:create")),
    db: AsyncSession = Depends(get_db),
):
    return await ResultService(db).upload_report_card(
        student_id=student_id,
        exam_id=exam_id,
        file=file,
        current_user=current_user,
    )


@router.get("/sections", response_model=list[str])
async def list_result_sections(
    standard_id: uuid.UUID = Query(...),
    academic_year_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await ResultService(db).list_result_sections(
        standard_id=standard_id,
        academic_year_id=academic_year_id,
        current_user=current_user,
    )
