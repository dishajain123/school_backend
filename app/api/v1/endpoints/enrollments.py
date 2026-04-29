# app/api/v1/endpoints/enrollments.py
"""
Phase 6 & 7 — Enrollment API.
Phase 14/15 — Section/Class Transfer added.
All routes require school context from the JWT.

Permission map:
  enrollment:create   → Admissions Staff, Admin, Superadmin
  enrollment:update   → Admissions Staff, Admin, Superadmin
  enrollment:read     → Teacher, Parent, Student (own), Admin, Superadmin
  student:promote     → Academic Admin, Principal, Superadmin
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.enrollment import EnrollmentService
from app.schemas.enrollment import (
    EnrollmentMappingCreate,
    EnrollmentMappingUpdate,
    EnrollmentExitRequest,
    EnrollmentCompleteRequest,
    SectionTransferRequest,
    EnrollmentMappingResponse,
    ClassRosterResponse,
    StudentAcademicHistoryResponse,
    RollNumberAssignRequest,
    OnboardingQueueItem,
    OnboardingQueueResponse,
)
from app.core.dependencies import get_current_user, require_any_permission, require_permission, CurrentUser
from app.core.exceptions import ForbiddenException, ValidationException
from app.utils.enums import RoleEnum

router = APIRouter(prefix="/enrollments", tags=["Enrollments"])


def get_service(db: AsyncSession = Depends(get_db)) -> EnrollmentService:
    return EnrollmentService(db)


# ── Create Enrollment Mapping ─────────────────────────────────────────────────

@router.post("/mappings", response_model=EnrollmentMappingResponse, status_code=201)
async def create_enrollment_mapping(
    data: EnrollmentMappingCreate,
    current_user: CurrentUser = Depends(require_any_permission("enrollment:create", "user:manage")),
    service: EnrollmentService = Depends(get_service),
):
    """
    Phase 6: Enroll a student in a specific class/section for an academic year.
    One mapping per student per academic year is enforced.
    Supports admission_type: NEW_ADMISSION, MID_YEAR, TRANSFER_IN, READMISSION.
    """
    if not current_user.school_id:
        raise ForbiddenException("School context required")
    return await service.create_mapping(data, current_user)


# ── Get Single Mapping ────────────────────────────────────────────────────────

@router.get("/mappings/{mapping_id}", response_model=EnrollmentMappingResponse)
async def get_enrollment_mapping(
    mapping_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_any_permission("enrollment:read", "user:manage")),
    service: EnrollmentService = Depends(get_service),
):
    """Get a single enrollment mapping by ID."""
    if not current_user.school_id:
        raise ForbiddenException("School context required")
    return await service.get_mapping(mapping_id, current_user)


# ── Update Mapping ────────────────────────────────────────────────────────────

@router.patch("/mappings/{mapping_id}", response_model=EnrollmentMappingResponse)
async def update_enrollment_mapping(
    mapping_id: uuid.UUID,
    data: EnrollmentMappingUpdate,
    current_user: CurrentUser = Depends(require_any_permission("enrollment:update", "user:manage")),
    service: EnrollmentService = Depends(get_service),
):
    """
    Phase 6: Update section, roll number, or admission type for an active mapping.
    Only ACTIVE and HOLD mappings can be updated.
    For a formal section/class transfer with an audit trail, use POST /mappings/{id}/transfer.
    """
    if not current_user.school_id:
        raise ForbiddenException("School context required")
    return await service.update_mapping(mapping_id, data, current_user)


# ── Section / Class Transfer (Phase 14/15) ────────────────────────────────────

@router.post("/mappings/{mapping_id}/transfer", response_model=EnrollmentMappingResponse)
async def transfer_student(
    mapping_id: uuid.UUID,
    data: SectionTransferRequest,
    current_user: CurrentUser = Depends(require_any_permission("enrollment:update", "user:manage")),
    service: EnrollmentService = Depends(get_service),
):
    """
    Phase 14/15: Formally transfer a student to a different section or class
    within the SAME academic year. Creates a structured audit log entry
    (STUDENT_SECTION_TRANSFERRED or STUDENT_CLASS_TRANSFERRED) distinguishing
    this from a generic data correction.

    - Same standard + different section → STUDENT_SECTION_TRANSFERRED
    - Different standard (class)         → STUDENT_CLASS_TRANSFERRED

    The existing StudentYearMapping is updated in-place; no historical record
    is lost. Student flat fields (standard_id, section) are synced immediately.

    Only ACTIVE and HOLD mappings can be transferred.
    Permission: enrollment:update (Admissions Staff, Admin, Principal).
    """
    if not current_user.school_id:
        raise ForbiddenException("School context required")
    return await service.transfer_student(mapping_id, data, current_user)


# ── Exit Student ──────────────────────────────────────────────────────────────

@router.post("/mappings/{mapping_id}/exit", response_model=EnrollmentMappingResponse)
async def exit_student(
    mapping_id: uuid.UUID,
    data: EnrollmentExitRequest,
    current_user: CurrentUser = Depends(require_any_permission("enrollment:update", "user:manage")),
    service: EnrollmentService = Depends(get_service),
):
    """
    Phase 6: Mark a student as LEFT or TRANSFERRED.
    Records the leaving date and reason. Data is preserved — never deleted.
    Responsibility: Admissions Staff initiates; Admin/Principal finalizes.
    """
    if not current_user.school_id:
        raise ForbiddenException("School context required")
    return await service.exit_student(mapping_id, data, current_user)


# ── Complete Mapping (Year End) ───────────────────────────────────────────────

@router.post("/mappings/{mapping_id}/complete", response_model=EnrollmentMappingResponse)
async def complete_mapping(
    mapping_id: uuid.UUID,
    data: EnrollmentCompleteRequest,
    current_user: CurrentUser = Depends(require_any_permission("student:promote", "user:manage")),
    service: EnrollmentService = Depends(get_service),
):
    """
    Phase 7: Mark a mapping as COMPLETED at year end.
    COMPLETED mappings are eligible for the promotion workflow.
    Only Academic Admin / Principal may complete mappings.
    """
    if not current_user.school_id:
        raise ForbiddenException("School context required")
    return await service.complete_mapping(mapping_id, data, current_user)


# ── Class Roster ──────────────────────────────────────────────────────────────

@router.get("/roster", response_model=ClassRosterResponse)
async def get_class_roster(
    standard_id: uuid.UUID = Query(...),
    academic_year_id: uuid.UUID = Query(...),
    section_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(require_any_permission("enrollment:read", "user:manage")),
    service: EnrollmentService = Depends(get_service),
):
    """
    Phase 6: Get the full enrollment roster for a class/section in a year.
    Returns counts by status (ACTIVE, LEFT, COMPLETED).
    """
    if not current_user.school_id:
        raise ForbiddenException("School context required")
    return await service.get_class_roster(
        school_id=current_user.school_id,
        standard_id=standard_id,
        section_id=section_id,
        academic_year_id=academic_year_id,
    )


# ── Student Academic History ──────────────────────────────────────────────────

@router.get("/history/{student_id}", response_model=StudentAcademicHistoryResponse)
async def get_student_history(
    student_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_any_permission("enrollment:read", "user:manage")),
    service: EnrollmentService = Depends(get_service),
):
    """
    Phase 7 / 14: Get all academic year mappings for a student — the complete history.
    History is immutable; no year's record is overwritten by enrollment in a new year.
    Includes all transfer events, exits, completions, and promotions.
    """
    if not current_user.school_id:
        raise ForbiddenException("School context required")
    return await service.get_student_history(student_id, current_user.school_id)


# ── Roll Number Assignment ────────────────────────────────────────────────────

@router.post("/roll-numbers/assign")
async def assign_roll_numbers(
    data: RollNumberAssignRequest,
    current_user: CurrentUser = Depends(require_permission("enrollment:update")),
    service: EnrollmentService = Depends(get_service),
):
    """
    Phase 6: Bulk-assign roll numbers to all ACTIVE students in a section.
    Policies: AUTO_SEQ (by join date), AUTO_ALPHA (alphabetical), MANUAL (explicit list).
    """
    if not current_user.school_id:
        raise ForbiddenException("School context required")
    return await service.assign_roll_numbers(data, current_user)
@router.get("/onboarding-queue", response_model=OnboardingQueueResponse)
async def get_onboarding_queue(
    role: Optional[RoleEnum] = Query(None),
    pending_only: bool = Query(True),
    academic_year_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(require_any_permission("enrollment:read", "user:manage")),
    service: EnrollmentService = Depends(get_service),
):
    """
    Approved users onboarding queue.
    Shows role-wise profile/enrollment completion states:
      - Student: profile + active class/section mapping
      - Teacher: profile + class/section/subject assignment
      - Parent: profile + child linking
      - Principal/Trustee: auto-complete (no assignment needed)
    """
    if not current_user.school_id:
        raise ForbiddenException("School context required")
    items = await service.list_onboarding_queue(
        school_id=current_user.school_id,
        role=role,
        pending_only=pending_only,
        academic_year_id=academic_year_id,
    )
    return OnboardingQueueResponse(
        items=[OnboardingQueueItem.model_validate(i) for i in items],
        total=len(items),
    )
