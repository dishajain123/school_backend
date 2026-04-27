# app/schemas/bulk.py
"""
Phase 15 — Bulk Operations.
Schemas for:
  1. Bulk student admission — create multiple students + parents + enrollments
     from a validated list. Each row is processed independently; errors are
     collected and returned per-row rather than aborting the whole batch.
  2. Bulk fee assignment — apply fee structures to multiple classes at once.
"""
import uuid
from datetime import date
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ─────────────────────────────────────────────────────────────────────────────
# Bulk Student Admission
# ─────────────────────────────────────────────────────────────────────────────

class BulkStudentRow(BaseModel):
    """One student record in a bulk admission request."""
    # Student account
    full_name: str = Field(..., min_length=1, max_length=255)
    email: str = Field(..., min_length=3, max_length=255)
    phone: str = Field(..., min_length=7, max_length=20)
    password: str = Field(..., min_length=8)

    # Student profile
    admission_number: Optional[str] = Field(None, max_length=50)
    date_of_birth: Optional[date] = None
    admission_date: Optional[date] = None
    admission_type: str = Field("NEW_ADMISSION", max_length=30)

    # Parent (create inline or link existing by parent_id)
    parent_id: Optional[str] = None          # existing parent UUID; skip create if set
    parent_full_name: Optional[str] = Field(None, max_length=255)
    parent_email: Optional[str] = Field(None, max_length=255)
    parent_phone: Optional[str] = Field(None, max_length=20)
    parent_password: Optional[str] = Field(None, min_length=8)
    parent_relation: str = Field("GUARDIAN", max_length=30)
    parent_occupation: Optional[str] = Field(None, max_length=100)

    # Class assignment
    standard_id: uuid.UUID
    section_id: Optional[uuid.UUID] = None
    academic_year_id: uuid.UUID
    roll_number: Optional[str] = Field(None, max_length=20)

    # Row reference for error reporting
    row_index: Optional[int] = None

    model_config = {"str_strip_whitespace": True}

    @field_validator("email")
    @classmethod
    def lower_email(cls, v: str) -> str:
        return v.lower().strip()


class BulkStudentAdmissionRequest(BaseModel):
    """Batch of students to admit."""
    rows: list[BulkStudentRow] = Field(..., min_length=1, max_length=200)

    model_config = {"str_strip_whitespace": True}


class BulkStudentResultRow(BaseModel):
    """Per-row result of a bulk admission operation."""
    row_index: Optional[int] = None
    full_name: Optional[str] = None
    email: Optional[str] = None
    status: str              # "created" | "skipped" | "error"
    student_id: Optional[uuid.UUID] = None
    admission_number: Optional[str] = None
    parent_id: Optional[uuid.UUID] = None
    error: Optional[str] = None


class BulkStudentAdmissionResponse(BaseModel):
    total: int
    created: int
    skipped: int
    error_count: int
    results: list[BulkStudentResultRow]


# ─────────────────────────────────────────────────────────────────────────────
# Bulk Fee Assignment
# ─────────────────────────────────────────────────────────────────────────────

class BulkFeeStructureRow(BaseModel):
    """One fee head applied to one class."""
    standard_id: uuid.UUID
    fee_category: str = Field(..., max_length=50)
    custom_fee_head: Optional[str] = Field(None, max_length=120)
    amount: float = Field(..., gt=0)
    due_date: date
    description: Optional[str] = Field(None, max_length=500)

    model_config = {"str_strip_whitespace": True}


class BulkFeeAssignmentRequest(BaseModel):
    """
    Apply one or more fee heads to multiple classes in a single call.
    Each row in `rows` is an independent fee structure record.
    academic_year_id applies to all rows.
    """
    academic_year_id: uuid.UUID
    rows: list[BulkFeeStructureRow] = Field(..., min_length=1, max_length=500)

    model_config = {"str_strip_whitespace": True}


class BulkFeeResultRow(BaseModel):
    standard_id: uuid.UUID
    fee_category: str
    status: str          # "created" | "skipped" | "error"
    structure_id: Optional[uuid.UUID] = None
    error: Optional[str] = None


class BulkFeeAssignmentResponse(BaseModel):
    total: int
    created: int
    skipped: int
    error_count: int
    results: list[BulkFeeResultRow]


# ─────────────────────────────────────────────────────────────────────────────
# CSV Template Helper
# ─────────────────────────────────────────────────────────────────────────────

STUDENT_CSV_HEADERS = [
    "full_name",
    "email",
    "phone",
    "password",
    "admission_number",
    "date_of_birth",
    "admission_date",
    "admission_type",
    "parent_id",
    "parent_full_name",
    "parent_email",
    "parent_phone",
    "parent_password",
    "parent_relation",
    "parent_occupation",
    "standard_id",
    "section_id",
    "academic_year_id",
    "roll_number",
]

FEE_CSV_HEADERS = [
    "standard_id",
    "fee_category",
    "custom_fee_head",
    "amount",
    "due_date",
    "description",
]