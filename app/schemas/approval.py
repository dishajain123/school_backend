import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.utils.enums import ApprovalAction, RegistrationSource, RoleEnum, UserStatus


class ApprovalQueueItem(BaseModel):
    user_id: uuid.UUID
    full_name: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    role: RoleEnum
    school_id: Optional[uuid.UUID]
    status: UserStatus
    registration_source: RegistrationSource
    rejection_reason: Optional[str]
    hold_reason: Optional[str]
    approved_at: Optional[datetime]
    created_at: datetime


class ApprovalQueueResponse(BaseModel):
    items: list[ApprovalQueueItem]
    total: int
    page: int
    page_size: int
    total_pages: int


class ApprovalDetailResponse(BaseModel):
    user_id: uuid.UUID
    full_name: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    role: RoleEnum
    school_id: Optional[uuid.UUID]
    status: UserStatus
    registration_source: RegistrationSource
    rejection_reason: Optional[str]
    hold_reason: Optional[str]
    approved_by_id: Optional[uuid.UUID]
    approved_at: Optional[datetime]
    submitted_data: Optional[dict[str, Any]]
    validation_issues: list[dict[str, Any]]
    duplicate_matches: list[dict[str, Any]]
    created_at: datetime
    updated_at: datetime


class ApprovalDecisionRequest(BaseModel):
    action: ApprovalAction
    note: Optional[str] = Field(None, max_length=500)
    override_validation: bool = False

    model_config = {"str_strip_whitespace": True}


class ApprovalDecisionResponse(BaseModel):
    user_id: uuid.UUID
    action: ApprovalAction
    status: UserStatus
    is_active: bool
    note: Optional[str]
    acted_by_id: uuid.UUID
    acted_at: datetime


class ApprovalAuditItem(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    acted_by_id: uuid.UUID
    action: ApprovalAction
    from_status: Optional[UserStatus]
    to_status: Optional[UserStatus]
    note: Optional[str]
    validation_issues: Optional[list[dict[str, Any]]]
    duplicate_matches: Optional[list[dict[str, Any]]]
    acted_at: datetime
    created_at: datetime


class ApprovalAuditResponse(BaseModel):
    items: list[ApprovalAuditItem]
    total: int
    page: int
    page_size: int
    total_pages: int


# ── INTEGRATED APPROVAL + ROLE PROFILE CREATION ──────────────────────────────
# For convenience: approve user and immediately create role profile in one step

class ApprovalWithProfileRequest(BaseModel):
    """Approve user and optionally create role profile in one operation"""
    action: ApprovalAction
    note: Optional[str] = Field(None, max_length=500)
    override_validation: bool = False
    
    # Optional role profile data (only used if action == APPROVE)
    create_student_profile: Optional[dict[str, Any]] = None  # StudentProfileCreate data
    create_teacher_profile: Optional[dict[str, Any]] = None  # TeacherProfileCreate data
    create_parent_profile: Optional[dict[str, Any]] = None   # ParentProfileCreate data

    model_config = {"str_strip_whitespace": True}


class ApprovalWithProfileResponse(BaseModel):
    """Response includes both approval and optional profile creation results"""
    user_id: uuid.UUID
    action: ApprovalAction
    status: UserStatus
    is_active: bool
    note: Optional[str]
    acted_by_id: uuid.UUID
    acted_at: datetime
    
    # Optional profile data
    student_profile: Optional[dict[str, Any]] = None
    teacher_profile: Optional[dict[str, Any]] = None
    parent_profile: Optional[dict[str, Any]] = None
    profile_error: Optional[str] = None  # If profile creation failed but approval succeeded

