# app/schemas/promotion_workflow.py
"""
Phase 7 — Yearly Promotion Workflow schemas.

Flow:
  1. Admin calls POST /promotions/preview  → sees all ACTIVE/COMPLETED students
     with their current class and the system-suggested next class.
  2. Admin reviews preview, overrides decisions as needed.
  3. Admin calls POST /promotions/execute  → new StudentYearMapping rows are
     created in the target year; old mappings are marked PROMOTED / REPEATED /
     GRADUATED depending on the decision.
  4. (Optional) Admin calls POST /promotions/copy-teacher-assignments to carry
     forward this year's teacher-class-subject records to the new year.
"""
import uuid
from datetime import date
from typing import Optional
from pydantic import BaseModel, Field
from app.utils.enums import PromotionDecision, EnrollmentStatus


# ── Preview ───────────────────────────────────────────────────────────────────

class PromotionPreviewItem(BaseModel):
    """One student's suggested promotion outcome."""
    student_id: uuid.UUID
    mapping_id: uuid.UUID
    admission_number: Optional[str]
    student_name: Optional[str]
    current_standard_id: uuid.UUID
    current_standard_name: str
    current_section_name: Optional[str]
    current_status: EnrollmentStatus

    # System suggestion — admin may override
    suggested_decision: PromotionDecision
    suggested_next_standard_id: Optional[uuid.UUID]
    suggested_next_standard_name: Optional[str]

    # Warning if next class does not exist in target year
    has_warning: bool = False
    warning_message: Optional[str] = None


class PromotionPreviewResponse(BaseModel):
    source_year_id: uuid.UUID
    source_year_name: str
    target_year_id: uuid.UUID
    target_year_name: str
    total_students: int
    promotable_count: int
    warning_count: int
    items: list[PromotionPreviewItem]


# ── Execute ───────────────────────────────────────────────────────────────────

class PromotionExecuteItem(BaseModel):
    """Admin's final decision for one student."""
    student_id: uuid.UUID
    mapping_id: uuid.UUID
    decision: PromotionDecision
    # Required for PROMOTE and REPEAT; ignored for GRADUATE / SKIP
    target_standard_id: Optional[uuid.UUID] = None
    target_section_id: Optional[uuid.UUID] = None
    roll_number: Optional[str] = Field(None, max_length=20)


class PromotionExecuteRequest(BaseModel):
    source_year_id: uuid.UUID
    target_year_id: uuid.UUID
    items: list[PromotionExecuteItem]

    model_config = {"str_strip_whitespace": True}


class PromotionExecuteResultItem(BaseModel):
    student_id: uuid.UUID
    admission_number: Optional[str]
    student_name: Optional[str]
    decision: PromotionDecision
    old_mapping_id: uuid.UUID
    old_status: EnrollmentStatus  # what the old mapping was set to
    new_mapping_id: Optional[uuid.UUID]  # None for GRADUATE / SKIP
    error: Optional[str] = None


class PromotionExecuteResponse(BaseModel):
    source_year_id: uuid.UUID
    target_year_id: uuid.UUID
    promoted_count: int
    repeated_count: int
    graduated_count: int
    skipped_count: int
    error_count: int
    results: list[PromotionExecuteResultItem]


# ── Single Re-enroll ──────────────────────────────────────────────────────────

class SingleReenrollRequest(BaseModel):
    """
    Phase 7: re-enroll a single student in a new academic year.
    Used for mid-year admissions (Phase 6) and for students who were
    excluded from the bulk promotion run.
    """
    target_year_id: uuid.UUID
    standard_id: uuid.UUID
    section_id: Optional[uuid.UUID] = None
    roll_number: Optional[str] = Field(None, max_length=20)
    joined_on: Optional[date] = None
    admission_type: str = "READMISSION"  # or MID_YEAR / NEW_ADMISSION

    model_config = {"str_strip_whitespace": True}


class SingleReenrollResponse(BaseModel):
    student_id: uuid.UUID
    admission_number: Optional[str]
    student_name: Optional[str]
    new_mapping_id: uuid.UUID
    target_year_id: uuid.UUID
    standard_name: Optional[str]
    section_name: Optional[str]


# ── Copy teacher assignments ──────────────────────────────────────────────────

class CopyTeacherAssignmentsRequest(BaseModel):
    source_year_id: uuid.UUID
    target_year_id: uuid.UUID
    overwrite_existing: bool = False  # if True, replace existing assignments

    model_config = {"str_strip_whitespace": True}


class CopyTeacherAssignmentsResponse(BaseModel):
    source_year_id: uuid.UUID
    target_year_id: uuid.UUID
    copied_count: int
    skipped_count: int
    error_count: int