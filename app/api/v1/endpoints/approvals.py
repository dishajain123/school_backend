import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_permission
from app.db.session import get_db
from app.schemas.approval import (
    ApprovalAuditItem,
    ApprovalAuditResponse,
    ApprovalDecisionRequest,
    ApprovalDecisionResponse,
    ApprovalDetailResponse,
    ApprovalQueueItem,
    ApprovalQueueResponse,
    ApprovalWithProfileRequest,
    ApprovalWithProfileResponse,
)
from app.services.approval import ApprovalService
from app.services.role_profile import RoleProfileService
from app.utils.enums import RegistrationSource, RoleEnum, UserStatus

router = APIRouter(prefix="/approvals", tags=["Approvals"])


@router.get("/queue", response_model=ApprovalQueueResponse)
async def list_approval_queue(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[UserStatus] = Query(None),
    role: Optional[RoleEnum] = Query(None),
    source: Optional[RegistrationSource] = Query(None),
    q: Optional[str] = Query(None),
    current_user: CurrentUser = Depends(require_permission("approval:review")),
    db: AsyncSession = Depends(get_db),
):
    service = ApprovalService(db)
    items, total, total_pages = await service.list_queue(
        current_user=current_user,
        page=page,
        page_size=page_size,
        status=status,
        role=role,
        source=source,
        q=q,
    )
    return ApprovalQueueResponse(
        items=[
            ApprovalQueueItem(
                user_id=u.id,
                full_name=u.full_name,
                email=u.email,
                phone=u.phone,
                role=u.role,
                school_id=u.school_id,
                status=u.status,
                registration_source=u.registration_source,
                rejection_reason=u.rejection_reason,
                hold_reason=u.hold_reason,
                approved_at=u.approved_at,
                created_at=u.created_at,
            )
            for u in items
        ],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/audit/logs", response_model=ApprovalAuditResponse)
async def list_approval_audit_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(require_permission("approval:review")),
    db: AsyncSession = Depends(get_db),
):
    service = ApprovalService(db)
    items, total, total_pages = await service.list_audit(
        current_user=current_user,
        page=page,
        page_size=page_size,
        user_id=user_id,
    )
    return ApprovalAuditResponse(
        items=[ApprovalAuditItem.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/{user_id}", response_model=ApprovalDetailResponse)
async def get_approval_detail(
    user_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("approval:review")),
    db: AsyncSession = Depends(get_db),
):
    service = ApprovalService(db)
    user, issues, duplicates = await service.get_detail(user_id=user_id, current_user=current_user)
    return ApprovalDetailResponse(
        user_id=user.id,
        full_name=user.full_name,
        email=user.email,
        phone=user.phone,
        role=user.role,
        school_id=user.school_id,
        status=user.status,
        registration_source=user.registration_source,
        rejection_reason=user.rejection_reason,
        hold_reason=user.hold_reason,
        approved_by_id=user.approved_by_id,
        approved_at=user.approved_at,
        submitted_data=user.submitted_data,
        validation_issues=issues,
        duplicate_matches=duplicates,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


@router.post("/{user_id}/decision", response_model=ApprovalDecisionResponse)
async def decide_approval(
    user_id: uuid.UUID,
    payload: ApprovalDecisionRequest,
    current_user: CurrentUser = Depends(require_permission("approval:decide")),
    db: AsyncSession = Depends(get_db),
):
    service = ApprovalService(db)
    user, _issues, _duplicates, acted_at = await service.decide(
        user_id=user_id,
        data=payload,
        current_user=current_user,
    )
    return ApprovalDecisionResponse(
        user_id=user.id,
        action=payload.action,
        status=user.status,
        is_active=user.is_active,
        note=payload.note,
        acted_by_id=current_user.id,
        acted_at=acted_at,
    )


@router.post("/{user_id}/decision-with-profile", response_model=ApprovalWithProfileResponse)
async def decide_approval_with_profile(
    user_id: uuid.UUID,
    payload: ApprovalWithProfileRequest,
    current_user: CurrentUser = Depends(require_permission("approval:decide")),
    db: AsyncSession = Depends(get_db),
):
    """
    Approve/Reject/Hold user AND optionally create role profile in one request.
    
    Profile creation only happens if:
    1. action == APPROVE
    2. Corresponding profile data is provided in request
    3. User role matches profile type
    
    If profile creation fails but approval succeeds, returns profile_error message
    and approval is not rolled back.
    """
    approval_service = ApprovalService(db)
    role_profile_service = RoleProfileService(db)
    
    # Step 1: Approve/Reject/Hold the user
    user, _issues, _duplicates, acted_at = await approval_service.decide(
        user_id=user_id,
        data=ApprovalDecisionRequest(
            action=payload.action,
            note=payload.note,
            override_validation=payload.override_validation,
        ),
        current_user=current_user,
    )
    
    profile_error = None
    student_profile = None
    teacher_profile = None
    parent_profile = None
    
    # Step 2: Optionally create role profile (only if APPROVE action and data provided)
    if user.status == UserStatus.ACTIVE and payload.action.value == "APPROVE":
        try:
            if user.role == RoleEnum.STUDENT and payload.create_student_profile:
                from app.schemas.role_profile import StudentProfileCreate
                profile_data = StudentProfileCreate(
                    user_id=user_id,
                    **payload.create_student_profile
                )
                result = await role_profile_service.create_student_profile(
                    profile_data, current_user
                )
                student_profile = {
                    "student_id": str(result.student_id),
                    "user_id": str(result.user_id),
                    "admission_number": result.admission_number,
                    "is_identifier_custom": result.is_identifier_custom,
                    "identifier_issued_at": result.identifier_issued_at.isoformat() if result.identifier_issued_at else None,
                }
            
            elif user.role == RoleEnum.TEACHER and payload.create_teacher_profile:
                from app.schemas.role_profile import TeacherProfileCreate
                profile_data = TeacherProfileCreate(
                    user_id=user_id,
                    **payload.create_teacher_profile
                )
                result = await role_profile_service.create_teacher_profile(
                    profile_data, current_user
                )
                teacher_profile = {
                    "teacher_id": str(result.teacher_id),
                    "user_id": str(result.user_id),
                    "employee_id": result.employee_id,
                    "is_identifier_custom": result.is_identifier_custom,
                    "identifier_issued_at": result.identifier_issued_at.isoformat() if result.identifier_issued_at else None,
                }
            
            elif user.role == RoleEnum.PARENT and payload.create_parent_profile:
                from app.schemas.role_profile import ParentProfileCreate
                profile_data = ParentProfileCreate(
                    user_id=user_id,
                    **payload.create_parent_profile
                )
                result = await role_profile_service.create_parent_profile(
                    profile_data, current_user
                )
                parent_profile = {
                    "parent_id": str(result.parent_id),
                    "user_id": str(result.user_id),
                    "parent_code": result.parent_code,
                    "is_identifier_custom": result.is_identifier_custom,
                    "identifier_issued_at": result.identifier_issued_at.isoformat() if result.identifier_issued_at else None,
                }
        except Exception as e:
            # Profile creation failed, but approval already succeeded
            profile_error = f"Profile creation failed: {str(e)}"
    
    return ApprovalWithProfileResponse(
        user_id=user.id,
        action=payload.action,
        status=user.status,
        is_active=user.is_active,
        note=payload.note,
        acted_by_id=current_user.id,
        acted_at=acted_at,
        student_profile=student_profile,
        teacher_profile=teacher_profile,
        parent_profile=parent_profile,
        profile_error=profile_error,
    )
