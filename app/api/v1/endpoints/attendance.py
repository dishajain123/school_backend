import uuid
from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.core.dependencies import CurrentUser, require_permission
from app.core.exceptions import ValidationException
from app.services.attendance import AttendanceService
from app.schemas.attendance import (
    MarkAttendanceRequest,
    MarkAttendanceResponse,
    AttendanceListResponse,
    StudentAttendanceAnalytics,
    ClassAttendanceSnapshot,
    BelowThresholdResponse,
)

router = APIRouter(prefix="/attendance", tags=["Attendance"])


def _require_school(current_user: CurrentUser) -> uuid.UUID:
    if not current_user.school_id:
        raise ValidationException("school_id is required")
    return current_user.school_id


@router.post("", response_model=MarkAttendanceResponse, status_code=201)
async def mark_attendance(
    payload: MarkAttendanceRequest,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(require_permission("attendance:create")),
    db: AsyncSession = Depends(get_db),
):
    service = AttendanceService(db)
    return await service.mark_attendance(payload, current_user, background_tasks)


@router.get("", response_model=AttendanceListResponse)
async def list_attendance(
    student_id: Optional[uuid.UUID] = Query(None),
    standard_id: Optional[uuid.UUID] = Query(None),
    section: Optional[str] = Query(None),
    academic_year_id: Optional[uuid.UUID] = Query(None),
    date: Optional[date] = Query(None),
    month: Optional[int] = Query(None, ge=1, le=12),
    year: Optional[int] = Query(None, ge=2000),
    subject_id: Optional[uuid.UUID] = Query(None),
    lecture_number: Optional[int] = Query(None, ge=1, le=12),
    current_user: CurrentUser = Depends(require_permission("attendance:read")),
    db: AsyncSession = Depends(get_db),
):
    service = AttendanceService(db)
    result = await service.list_attendance(
        current_user=current_user,
        student_id=student_id,
        standard_id=standard_id,
        section=section,
        academic_year_id=academic_year_id,
        record_date=date,
        month=month,
        year=year,
        subject_id=subject_id,
        lecture_number=lecture_number,
    )
    return AttendanceListResponse(**result)


@router.get("/analytics/student/{student_id}", response_model=StudentAttendanceAnalytics)
async def student_analytics(
    student_id: uuid.UUID,
    month: Optional[int] = Query(None, ge=1, le=12),
    year: Optional[int] = Query(None, ge=2000),
    current_user: CurrentUser = Depends(require_permission("attendance:analytics")),
    db: AsyncSession = Depends(get_db),
):
    service = AttendanceService(db)
    return await service.student_analytics(student_id, current_user, month, year)


@router.get("/analytics/class/{standard_id}", response_model=ClassAttendanceSnapshot)
async def class_snapshot(
    standard_id: uuid.UUID,
    academic_year_id: uuid.UUID = Query(...),
    date: date = Query(...),
    section: Optional[str] = Query(None),
    subject_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(require_permission("attendance:analytics")),
    db: AsyncSession = Depends(get_db),
):
    service = AttendanceService(db)
    return await service.class_snapshot(
        standard_id,
        academic_year_id,
        date,
        current_user,
        section=section,
        subject_id=subject_id,
    )


@router.get("/analytics/class", response_model=ClassAttendanceSnapshot)
async def class_snapshot_query(
    standard_id: uuid.UUID = Query(...),
    academic_year_id: uuid.UUID = Query(...),
    date: date = Query(...),
    section: Optional[str] = Query(None),
    subject_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(require_permission("attendance:analytics")),
    db: AsyncSession = Depends(get_db),
):
    service = AttendanceService(db)
    return await service.class_snapshot(
        standard_id,
        academic_year_id,
        date,
        current_user,
        section=section,
        subject_id=subject_id,
    )


@router.get("/analytics/below-threshold", response_model=BelowThresholdResponse)
async def below_threshold(
    standard_id: uuid.UUID = Query(...),
    academic_year_id: uuid.UUID = Query(...),
    threshold: float = Query(75.0, ge=0, le=100),
    current_user: CurrentUser = Depends(require_permission("attendance:analytics")),
    db: AsyncSession = Depends(get_db),
):
    service = AttendanceService(db)
    return await service.below_threshold(
        standard_id=standard_id,
        academic_year_id=academic_year_id,
        current_user=current_user,
        threshold=threshold,
    )
