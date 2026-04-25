import uuid
from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.core.dependencies import CurrentUser, require_permission, get_current_user
from app.core.exceptions import ValidationException
from app.services.attendance import AttendanceService
from app.schemas.attendance import (
    MarkAttendanceRequest,
    MarkAttendanceResponse,
    AttendanceListResponse,
    StudentAttendanceAnalytics,
    BelowThresholdResponse,
    LectureAttendanceResponse,
    StudentDetailAttendanceResponse,
    AttendanceDashboardResponse,
)

router = APIRouter(prefix="/attendance", tags=["Attendance"])


def _require_school(current_user: CurrentUser) -> uuid.UUID:
    if not current_user.school_id:
        raise ValidationException("school_id is required")
    return current_user.school_id


# ── Mark Attendance ───────────────────────────────────────────────────────────

@router.post("", response_model=MarkAttendanceResponse, status_code=201)
async def mark_attendance(
    payload: MarkAttendanceRequest,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(require_permission("attendance:create")),
    db: AsyncSession = Depends(get_db),
):
    """
    TEACHER only.
    Mark attendance for a lecture. Defaults all students to PRESENT; caller
    must explicitly include students who are ABSENT/LATE.
    Duplicate submissions for the same lecture are silently upserted.
    """
    service = AttendanceService(db)
    return await service.mark_attendance(payload, current_user, background_tasks)


# ── List Attendance (class/student raw records) ───────────────────────────────

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
    """
    Dual-mode endpoint:
    - Pass student_id → returns that student's attendance history (STUDENT/PARENT/TEACHER/PRINCIPAL/TRUSTEE).
    - Pass standard_id + section + date → returns class snapshot (TEACHER/PRINCIPAL/TRUSTEE).
    """
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


# ── Lecture-wise snapshot ─────────────────────────────────────────────────────

@router.get("/lecture", response_model=LectureAttendanceResponse)
async def get_lecture_attendance(
    standard_id: uuid.UUID = Query(...),
    section: str = Query(..., max_length=10),
    subject_id: uuid.UUID = Query(...),
    academic_year_id: uuid.UUID = Query(...),
    date: date = Query(...),
    lecture_number: int = Query(1, ge=1, le=12),
    current_user: CurrentUser = Depends(require_permission("attendance:read")),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns a full lecture-wise attendance snapshot for a class.
    Includes ALL students in the class-section even if not yet marked
    (unmarked students are shown as ABSENT for the UI to toggle).

    Access:
    - TEACHER: must own this class-subject assignment.
    - PRINCIPAL / TRUSTEE: unrestricted read.
    - STUDENT / PARENT: forbidden.
    """
    service = AttendanceService(db)
    return await service.get_lecture_attendance(
        standard_id=standard_id,
        section=section,
        subject_id=subject_id,
        academic_year_id=academic_year_id,
        record_date=date,
        lecture_number=lecture_number,
        current_user=current_user,
    )


# ── Student comprehensive detail ──────────────────────────────────────────────

@router.get("/student/{student_id}", response_model=StudentDetailAttendanceResponse)
async def get_student_detail_attendance(
    student_id: uuid.UUID,
    year: Optional[int] = Query(None, ge=2000),
    current_user: CurrentUser = Depends(require_permission("attendance:read")),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns a comprehensive attendance view for a single student:
    - Lecture-wise raw records
    - Subject-wise attendance %
    - Month-by-month summary

    Access:
    - STUDENT: only their own.
    - PARENT: only their linked child.
    - TEACHER: only students from their assigned class-sections.
    - PRINCIPAL / TRUSTEE: unrestricted.
    """
    service = AttendanceService(db)
    return await service.get_student_detail_attendance(
        student_id=student_id,
        current_user=current_user,
        year=year,
    )


# ── Analytics: Student subject-wise (existing) ────────────────────────────────

@router.get("/analytics/student/{student_id}", response_model=StudentAttendanceAnalytics)
async def student_analytics(
    student_id: uuid.UUID,
    month: Optional[int] = Query(None, ge=1, le=12),
    year: Optional[int] = Query(None, ge=2000),
    current_user: CurrentUser = Depends(require_permission("attendance:analytics")),
    db: AsyncSession = Depends(get_db),
):
    """
    Subject-wise attendance analytics for a single student.
    Optionally filtered by month/year.
    """
    service = AttendanceService(db)
    return await service.student_analytics(student_id, current_user, month, year)


# ── Analytics: Below threshold (existing) ────────────────────────────────────

@router.get("/analytics/below-threshold", response_model=BelowThresholdResponse)
async def below_threshold(
    standard_id: uuid.UUID = Query(...),
    academic_year_id: uuid.UUID = Query(...),
    threshold: float = Query(75.0, ge=0, le=100),
    current_user: CurrentUser = Depends(require_permission("attendance:analytics")),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns all students in a class whose overall attendance % is below
    the given threshold (default 75%).
    """
    service = AttendanceService(db)
    return await service.below_threshold(
        standard_id=standard_id,
        academic_year_id=academic_year_id,
        current_user=current_user,
        threshold=threshold,
    )


# ── Analytics: Dashboard (Principal / Trustee) ────────────────────────────────

@router.get("/analytics/dashboard", response_model=AttendanceDashboardResponse)
async def attendance_dashboard(
    academic_year_id: uuid.UUID = Query(...),
    standard_id: Optional[uuid.UUID] = Query(None, description="Optional class filter"),
    top_absentees_limit: int = Query(10, ge=1, le=50),
    trend_weeks: int = Query(8, ge=1, le=52),
    trend_months: int = Query(6, ge=1, le=12),
    current_user: CurrentUser = Depends(require_permission("attendance:analytics")),
    db: AsyncSession = Depends(get_db),
):
    """
    Full attendance analytics dashboard.

    Returns:
    - School-wide overall attendance %
    - Class-wise breakdown
    - Subject-wise breakdown
    - Top absentees
    - Weekly & monthly trends

    Access: PRINCIPAL and TRUSTEE only.
    """
    service = AttendanceService(db)
    return await service.get_analytics_dashboard(
        academic_year_id=academic_year_id,
        current_user=current_user,
        standard_id=standard_id,
        top_absentees_limit=top_absentees_limit,
        trend_weeks=trend_weeks,
        trend_months=trend_months,
    )