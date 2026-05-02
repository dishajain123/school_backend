import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, get_current_user
from app.core.exceptions import ForbiddenException, ValidationException
from app.db.session import get_db
from app.repositories.parent import ParentRepository
from app.repositories.student import StudentRepository
from app.schemas.attendance import (
    AttendanceListResponse,
    AttendanceResponse,
    AttendanceDashboardResponse,
    BelowThresholdResponse,
    LectureAttendanceResponse,
    MarkAttendanceRequest,
    MarkAttendanceResponse,
    StudentAttendanceAnalytics,
    StudentDetailAttendanceResponse,
)
from app.services.attendance import AttendanceService
from app.utils.enums import RoleEnum

router = APIRouter(prefix="/attendance", tags=["Attendance"])


def get_service(db: AsyncSession = Depends(get_db)) -> AttendanceService:
    return AttendanceService(db)


@router.post("/mark", response_model=MarkAttendanceResponse)
async def mark_attendance(
    payload: MarkAttendanceRequest,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(get_current_user),
    service: AttendanceService = Depends(get_service),
):
    return await service.mark_attendance(payload, current_user, background_tasks)


@router.get("", response_model=AttendanceListResponse)
async def list_attendance(
    student_id: Optional[uuid.UUID] = Query(None),
    standard_id: Optional[uuid.UUID] = Query(None),
    section: Optional[str] = Query(None),
    academic_year_id: Optional[uuid.UUID] = Query(None),
    record_date: Optional[date] = Query(None, alias="date"),
    month: Optional[int] = Query(None, ge=1, le=12),
    year: Optional[int] = Query(None, ge=2000, le=2100),
    subject_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    service: AttendanceService = Depends(get_service),
):
    data = await service.list_attendance(
        current_user=current_user,
        student_id=student_id,
        standard_id=standard_id,
        section=section,
        academic_year_id=academic_year_id,
        record_date=record_date,
        month=month,
        year=year,
        subject_id=subject_id,
    )
    return AttendanceListResponse(
        items=[AttendanceResponse.model_validate(item) for item in data["items"]],
        total=int(data["total"]),
    )


@router.get("/me", response_model=StudentDetailAttendanceResponse)
async def get_my_attendance(
    student_id: Optional[uuid.UUID] = Query(None),
    year: Optional[int] = Query(None, ge=2000, le=2100),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: AttendanceService = Depends(get_service),
):
    if current_user.role == RoleEnum.STUDENT:
        student = await StudentRepository(db).get_by_user_id(current_user.id)
        if not student:
            raise ValidationException("Student profile not found for current user")
        return await service.get_student_detail_attendance(
            student_id=student.id,
            current_user=current_user,
            year=year,
        )

    if current_user.role == RoleEnum.PARENT:
        parent = await ParentRepository(db).get_by_user_id(current_user.id)
        if not parent:
            raise ValidationException("Parent profile not found for current user")
        children = await StudentRepository(db).list_by_parent(parent.id, current_user.school_id)
        if not children:
            raise ValidationException("No child linked to current parent profile")
        target_student_id = student_id or children[0].id
        return await service.get_student_detail_attendance(
            student_id=target_student_id,
            current_user=current_user,
            year=year,
        )

    raise ForbiddenException("Use student-specific attendance endpoints for this role")


@router.get("/student/{student_id}/detail", response_model=StudentDetailAttendanceResponse)
async def get_student_detail_attendance(
    student_id: uuid.UUID,
    year: Optional[int] = Query(None, ge=2000, le=2100),
    current_user: CurrentUser = Depends(get_current_user),
    service: AttendanceService = Depends(get_service),
):
    return await service.get_student_detail_attendance(
        student_id=student_id,
        current_user=current_user,
        year=year,
    )


@router.get("/student/{student_id}/analytics", response_model=StudentAttendanceAnalytics)
async def get_student_analytics(
    student_id: uuid.UUID,
    month: Optional[int] = Query(None, ge=1, le=12),
    year: Optional[int] = Query(None, ge=2000, le=2100),
    current_user: CurrentUser = Depends(get_current_user),
    service: AttendanceService = Depends(get_service),
):
    return await service.student_analytics(
        student_id=student_id,
        current_user=current_user,
        month=month,
        year=year,
    )


@router.get("/lecture", response_model=LectureAttendanceResponse)
async def get_lecture_attendance(
    standard_id: uuid.UUID = Query(...),
    section: str = Query(...),
    subject_id: uuid.UUID = Query(...),
    academic_year_id: uuid.UUID = Query(...),
    record_date: date = Query(..., alias="date"),
    current_user: CurrentUser = Depends(get_current_user),
    service: AttendanceService = Depends(get_service),
):
    return await service.get_lecture_attendance(
        standard_id=standard_id,
        section=section,
        subject_id=subject_id,
        academic_year_id=academic_year_id,
        record_date=record_date,
        current_user=current_user,
    )


@router.get("/below-threshold", response_model=BelowThresholdResponse)
async def get_below_threshold(
    standard_id: uuid.UUID = Query(...),
    academic_year_id: uuid.UUID = Query(...),
    threshold: float = Query(75.0, ge=0.0, le=100.0),
    current_user: CurrentUser = Depends(get_current_user),
    service: AttendanceService = Depends(get_service),
):
    return await service.below_threshold(
        standard_id=standard_id,
        academic_year_id=academic_year_id,
        current_user=current_user,
        threshold=threshold,
    )


@router.get("/dashboard", response_model=AttendanceDashboardResponse)
async def get_attendance_dashboard(
    academic_year_id: uuid.UUID = Query(...),
    standard_id: Optional[uuid.UUID] = Query(None),
    top_absentees_limit: int = Query(10, ge=1, le=100),
    trend_weeks: int = Query(8, ge=1, le=52),
    trend_months: int = Query(6, ge=1, le=24),
    current_user: CurrentUser = Depends(get_current_user),
    service: AttendanceService = Depends(get_service),
):
    return await service.get_analytics_dashboard(
        academic_year_id=academic_year_id,
        current_user=current_user,
        standard_id=standard_id,
        top_absentees_limit=top_absentees_limit,
        trend_weeks=trend_weeks,
        trend_months=trend_months,
    )
