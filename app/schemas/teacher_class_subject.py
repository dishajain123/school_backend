import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


# ── Create ────────────────────────────────────────────────────────────────────

class TeacherAssignmentCreate(BaseModel):
    teacher_id: uuid.UUID
    standard_id: uuid.UUID
    section: str = Field(..., max_length=10)
    subject_id: uuid.UUID
    academic_year_id: uuid.UUID

    model_config = {"str_strip_whitespace": True}


# ── Nested responses ──────────────────────────────────────────────────────────

class TeacherSummary(BaseModel):
    id: uuid.UUID
    employee_code: str
    user_id: uuid.UUID

    model_config = {"from_attributes": True}


class StandardSummary(BaseModel):
    id: uuid.UUID
    name: str
    level: int

    model_config = {"from_attributes": True}


class SubjectSummary(BaseModel):
    id: uuid.UUID
    name: str
    code: str

    model_config = {"from_attributes": True}


class AcademicYearSummary(BaseModel):
    id: uuid.UUID
    name: str

    model_config = {"from_attributes": True}


# ── Response ──────────────────────────────────────────────────────────────────

class TeacherAssignmentResponse(BaseModel):
    id: uuid.UUID
    section: str
    teacher: TeacherSummary
    standard: StandardSummary
    subject: SubjectSummary
    academic_year: AcademicYearSummary
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TeacherAssignmentListResponse(BaseModel):
    items: list[TeacherAssignmentResponse]
    total: int