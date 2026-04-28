# app/schemas/enrollment.py
"""
Schemas for Phase 6 (Student Lifecycle) and Phase 7 (Re-enrollment) enrollment operations.
Phase 14/15: Added SectionTransferRequest for in-year section/class transfers.
"""
import uuid
from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, Field
from app.utils.enums import EnrollmentStatus, AdmissionType


# ── Create ────────────────────────────────────────────────────────────────────

class EnrollmentMappingCreate(BaseModel):
    """Phase 6: enroll a student in an academic year."""
    student_id: uuid.UUID
    academic_year_id: uuid.UUID
    standard_id: uuid.UUID
    section_id: Optional[uuid.UUID] = None
    roll_number: Optional[str] = Field(None, max_length=20)
    joined_on: Optional[date] = None
    admission_type: AdmissionType = AdmissionType.NEW_ADMISSION

    model_config = {"str_strip_whitespace": True}


# ── Update ────────────────────────────────────────────────────────────────────

class EnrollmentMappingUpdate(BaseModel):
    """Partial update: change section, roll number, or admission type."""
    standard_id: Optional[uuid.UUID] = None
    section_id: Optional[uuid.UUID] = None
    roll_number: Optional[str] = Field(None, max_length=20)
    joined_on: Optional[date] = None
    admission_type: Optional[AdmissionType] = None

    model_config = {"str_strip_whitespace": True}


# ── Section / Class Transfer (Phase 14/15) ────────────────────────────────────

class SectionTransferRequest(BaseModel):
    """
    Phase 14/15: Transfer a student to a different section (or class) within
    the SAME academic year. The existing StudentYearMapping is updated in-place.
    A structured audit log entry is created distinguishing this from a generic update.

    - section_only=True : only section changes, standard stays the same.
    - section_only=False: both standard and section change (class transfer).
    """
    new_standard_id: uuid.UUID
    new_section_id: Optional[uuid.UUID] = None
    new_roll_number: Optional[str] = Field(None, max_length=20)
    transfer_reason: str = Field(..., min_length=3, max_length=500)
    effective_date: Optional[date] = None   # defaults to today

    model_config = {"str_strip_whitespace": True}


# ── Exit ──────────────────────────────────────────────────────────────────────

class EnrollmentExitRequest(BaseModel):
    """Phase 6: mark student as LEFT or TRANSFERRED."""
    status: EnrollmentStatus = Field(
        ...,
        description="Must be LEFT or TRANSFERRED",
    )
    left_on: date
    exit_reason: str = Field(..., min_length=3, max_length=500)

    model_config = {"str_strip_whitespace": True}


# ── Complete ──────────────────────────────────────────────────────────────────

class EnrollmentCompleteRequest(BaseModel):
    """Phase 7: mark year as COMPLETED for promotion eligibility."""
    completed_on: Optional[date] = None  # defaults to today

    model_config = {"str_strip_whitespace": True}


# ── Roll-number assignment ────────────────────────────────────────────────────

class RollNumberAssignRequest(BaseModel):
    standard_id: uuid.UUID
    section_id: uuid.UUID
    academic_year_id: uuid.UUID
    policy: str = Field(
        "AUTO_ALPHA",
        description="AUTO_SEQ | AUTO_ALPHA | MANUAL",
    )
    manual_assignments: Optional[list[dict]] = None


# ── Response ──────────────────────────────────────────────────────────────────

class EnrollmentMappingResponse(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID
    school_id: uuid.UUID
    academic_year_id: uuid.UUID
    standard_id: uuid.UUID
    section_id: Optional[uuid.UUID]
    section_name: Optional[str]
    roll_number: Optional[str]
    status: EnrollmentStatus
    admission_type: Optional[AdmissionType]
    joined_on: Optional[date]
    left_on: Optional[date]
    exit_reason: Optional[str]

    # Denormalized display helpers
    student_name: Optional[str] = None
    admission_number: Optional[str] = None
    standard_name: Optional[str] = None
    academic_year_name: Optional[str] = None

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ClassRosterResponse(BaseModel):
    academic_year_id: uuid.UUID
    academic_year_name: str
    standard_id: uuid.UUID
    standard_name: str
    section_name: Optional[str]
    total_enrolled: int
    active_count: int
    left_count: int
    completed_count: int
    mappings: list[EnrollmentMappingResponse]


class StudentAcademicHistoryResponse(BaseModel):
    """Phase 7 / 14: ordered list of all year mappings for one student."""
    student_id: uuid.UUID
    admission_number: Optional[str]
    student_name: Optional[str]
    history: list[EnrollmentMappingResponse]