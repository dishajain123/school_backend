# app/api/v1/endpoints/promotions.py
"""
Phase 7 — Promotion Workflow API.

Principle: user identity is permanent. Promotion = new StudentYearMapping,
not new User. Previous year mappings are NEVER overwritten; they become
PROMOTED / REPEATED / COMPLETED terminal states.

Permission map:
  student:promote  → Academic Admin (PRINCIPAL), Superadmin
  enrollment:read  → Staff Admin (preview only)
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.promotion_workflow import PromotionWorkflowService
from app.schemas.promotion_workflow import (
    PromotionPreviewResponse,
    PromotionExecuteRequest,
    PromotionExecuteResponse,
    SingleReenrollRequest,
    SingleReenrollResponse,
    TeacherReenrollRequest,
    TeacherReenrollResponse,
    CopyTeacherAssignmentsRequest,
    CopyTeacherAssignmentsResponse,
)
from app.core.dependencies import get_current_user, require_any_permission, require_permission, CurrentUser
from app.core.exceptions import ForbiddenException

router = APIRouter(prefix="/promotions", tags=["Promotions"])


def get_service(db: AsyncSession = Depends(get_db)) -> PromotionWorkflowService:
    return PromotionWorkflowService(db)


# ── Preview ───────────────────────────────────────────────────────────────────

@router.get("/preview", response_model=PromotionPreviewResponse)
async def preview_promotion(
    source_year_id: uuid.UUID = Query(..., description="Source academic year ID"),
    target_year_id: uuid.UUID = Query(..., description="Target academic year ID"),
    standard_id: Optional[uuid.UUID] = Query(
        None, description="Filter preview to one class"
    ),
    section_id: Optional[uuid.UUID] = Query(
        None, description="Filter preview to one section in the selected class"
    ),
    current_user: CurrentUser = Depends(
        require_any_permission("enrollment:read", "student:promote", "user:manage")
    ),
    service: PromotionWorkflowService = Depends(get_service),
):
    """
    Phase 7: Preview the promotion run — shows all eligible students,
    their current class, the system-suggested next class, and any warnings.
    This is a READ-ONLY operation. Nothing is written to the database.
    Staff Admin (review-only), Academic Admin, and user-manage admins can call this.
    """
    if not current_user.school_id:
        raise ForbiddenException("School context required")
    return await service.preview_promotion(
        source_year_id=source_year_id,
        target_year_id=target_year_id,
        school_id=current_user.school_id,
        standard_id=standard_id,
        section_id=section_id,
    )


# ── Execute ───────────────────────────────────────────────────────────────────

@router.post("/execute", response_model=PromotionExecuteResponse)
async def execute_promotion(
    data: PromotionExecuteRequest,
    current_user: CurrentUser = Depends(require_permission("student:promote")),
    service: PromotionWorkflowService = Depends(get_service),
):
    """
    Phase 7: Execute promotion — creates new StudentYearMapping records in the
    target year and closes old mappings as PROMOTED / REPEATED / COMPLETED.

    For each item in the request:
      PROMOTE  → old mapping → PROMOTED;  new mapping in next class
      REPEAT   → old mapping → REPEATED;  new mapping in same class
      GRADUATE → old mapping → COMPLETED; no new mapping (finished schooling)
      SKIP     → no change;  handle the student manually later

    CRITICAL: Previous year mappings are NOT deleted. They become read-only
    historical records. All audit actions are logged.

    Only Academic Admin (PRINCIPAL) and Superadmin may execute.
    """
    if not current_user.school_id:
        raise ForbiddenException("School context required")
    return await service.execute_promotion(data, current_user)


# ── Single Re-enroll ──────────────────────────────────────────────────────────

@router.post("/reenroll/{student_id}", response_model=SingleReenrollResponse)
async def reenroll_student(
    student_id: uuid.UUID,
    data: SingleReenrollRequest,
    current_user: CurrentUser = Depends(require_any_permission("enrollment:create", "user:manage")),
    service: PromotionWorkflowService = Depends(get_service),
):
    """
    Phase 7: Re-enroll a single student in a new academic year.
    Used for:
      - Students excluded from the bulk promotion run (SKIP decision)
      - Mid-year admissions (admission_type=MID_YEAR)
      - Students who left and are re-joining (admission_type=READMISSION)
      - Students transferred in from another school (admission_type=TRANSFER_IN)

    The student's existing profile, admission number, and parent link remain
    completely unchanged. Only a new StudentYearMapping is created.
    """
    if not current_user.school_id:
        raise ForbiddenException("School context required")
    return await service.reenroll_student(student_id, data, current_user)


# ── Copy Teacher Assignments ──────────────────────────────────────────────────

@router.post("/copy-teacher-assignments", response_model=CopyTeacherAssignmentsResponse)
async def copy_teacher_assignments(
    data: CopyTeacherAssignmentsRequest,
    current_user: CurrentUser = Depends(require_permission("student:promote")),
    service: PromotionWorkflowService = Depends(get_service),
):
    """
    Phase 7: Copy all teacher-class-subject assignments from the source academic
    year to the target year. Classes are matched by level (not by ID), so even
    newly created standard entities for the new year are supported.

    This is an OPTIONAL convenience step after the promotion run. Fresh
    assignments can always be created manually. Existing assignments in the
    target year are skipped (not overwritten) unless overwrite_existing=true.

    Only Academic Admin / Principal / Superadmin may run this.
    """
    if not current_user.school_id:
        raise ForbiddenException("School context required")
    return await service.copy_teacher_assignments(data, current_user)


@router.post("/reenroll-teacher/{teacher_id}", response_model=TeacherReenrollResponse)
async def reenroll_teacher(
    teacher_id: uuid.UUID,
    data: TeacherReenrollRequest,
    current_user: CurrentUser = Depends(require_permission("teacher_assignment:manage")),
    service: PromotionWorkflowService = Depends(get_service),
):
    """
    Re-enroll a single teacher's assignments from source academic year to target
    academic year. Existing target-year assignments are preserved by default and
    can be replaced with overwrite_existing=true.
    """
    if not current_user.school_id:
        raise ForbiddenException("School context required")
    return await service.reenroll_teacher_assignments(teacher_id, data, current_user)
