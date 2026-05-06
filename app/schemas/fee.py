# app/schemas/fee.py
from __future__ import annotations

import uuid
import math
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.utils.enums import FeeCategory, FeeStatus, PaymentMode


# ---------------------------------------------------------------------------
# Installment plan item
# ---------------------------------------------------------------------------

class InstallmentPlanItem(BaseModel):
    name: str
    due_date: date
    amount: float

    @field_validator("amount")
    @classmethod
    def amount_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Installment amount must be positive")
        return v


# ---------------------------------------------------------------------------
# Fee Structures
# ---------------------------------------------------------------------------

class FeeStructureItem(BaseModel):
    standard_id: uuid.UUID
    academic_year_id: uuid.UUID
    fee_category: FeeCategory
    amount: float
    due_date: date
    custom_fee_head: Optional[str] = None
    description: Optional[str] = None
    installment_plan: Optional[list[InstallmentPlanItem]] = None

    @field_validator("custom_fee_head", mode="before")
    @classmethod
    def normalize_custom_head(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        normalized = " ".join(v.strip().split())
        return normalized if normalized else None

    @field_validator("amount")
    @classmethod
    def amount_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Amount must be positive")
        return v

    @field_validator("custom_fee_head")
    @classmethod
    def require_custom_head_for_misc(cls, v: Optional[str], info):
        fee_category = info.data.get("fee_category")
        if fee_category == FeeCategory.MISCELLANEOUS and not v:
            raise ValueError("custom_fee_head is required when fee_category is MISCELLANEOUS")
        return v


class FeeStructureBatchCreate(BaseModel):
    structures: list[FeeStructureItem] = Field(..., min_length=1)


class StandardRef(BaseModel):
    id: uuid.UUID
    name: str
    level: int

    model_config = {"from_attributes": True}


class AcademicYearRef(BaseModel):
    id: uuid.UUID
    name: str
    start_date: date
    end_date: date
    is_active: bool

    model_config = {"from_attributes": True}


class FeeStructureResponse(BaseModel):
    id: uuid.UUID
    standard_id: uuid.UUID
    academic_year_id: uuid.UUID
    fee_category: FeeCategory
    custom_fee_head: Optional[str] = None
    amount: float
    due_date: date
    description: Optional[str] = None
    installment_plan: Optional[list[dict]] = None
    school_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    standard: Optional[StandardRef] = None
    academic_year: Optional[AcademicYearRef] = None

    model_config = {"from_attributes": True}

    @field_validator("custom_fee_head", mode="before")
    @classmethod
    def empty_to_none(cls, v: Optional[str]) -> Optional[str]:
        return v or None


class FeeStructureListResponse(BaseModel):
    items: list[FeeStructureResponse]
    total: int


class FeeStructureBatchResponse(BaseModel):
    items: list[FeeStructureResponse]
    total: int
    created: int = 0
    updated: int = 0


class FeeStructureUpdate(BaseModel):
    amount: Optional[float] = None
    due_date: Optional[date] = None
    description: Optional[str] = None
    custom_fee_head: Optional[str] = None
    installment_plan: Optional[list[InstallmentPlanItem]] = None
    apply_to_all_classes: bool = False

    @field_validator("amount", mode="before")
    @classmethod
    def amount_positive_if_set(cls, v: Optional[float]) -> Optional[float]:
        if v is None:
            return None
        if v <= 0:
            raise ValueError("Amount must be positive")
        return v


class FeeStructureUpdateResponse(BaseModel):
    items: list[FeeStructureResponse]
    total: int


# ---------------------------------------------------------------------------
# Fee Ledger
# ---------------------------------------------------------------------------

class FeeLedgerResponse(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID
    fee_structure_id: uuid.UUID
    installment_name: str = ""
    fee_category: Optional[FeeCategory] = None
    custom_fee_head: Optional[str] = None
    due_date: Optional[date] = None
    fee_description: Optional[str] = None
    total_amount: float
    paid_amount: float
    outstanding_amount: float = 0.0
    status: FeeStatus
    last_payment_date: Optional[date] = None
    school_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("custom_fee_head", mode="before")
    @classmethod
    def empty_ledger_custom_head_to_none(cls, v: Optional[str]) -> Optional[str]:
        return v or None


class AdminLedgerEntry(BaseModel):
    """Ledger entry with embedded student info for admin list view."""
    id: uuid.UUID
    student_id: uuid.UUID
    fee_structure_id: uuid.UUID
    student_name: Optional[str] = None
    admission_number: Optional[str] = None
    standard_name: Optional[str] = None
    installment_name: str = ""
    fee_category: Optional[FeeCategory] = None
    custom_fee_head: Optional[str] = None
    due_date: Optional[date] = None
    total_amount: float
    paid_amount: float
    outstanding_amount: float
    status: FeeStatus
    last_payment_date: Optional[date] = None
    school_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AdminLedgerListResponse(BaseModel):
    items: list[AdminLedgerEntry]
    total: int
    page: int
    page_size: int
    pages: int
    total_billed: float = 0.0
    total_paid: float = 0.0
    total_outstanding: float = 0.0


# ---------------------------------------------------------------------------
# Student-wise class fee summary (admin console class view)
# ---------------------------------------------------------------------------

class StudentInstallmentSummary(BaseModel):
    """One installment/fee-head row for a student."""
    ledger_id: str
    fee_head: str          # custom_fee_head or fee_category
    installment_name: str
    due_date: Optional[date] = None
    total_amount: float
    paid_amount: float
    outstanding_amount: float
    status: str            # PENDING | PARTIAL | PAID | OVERDUE
    last_payment_date: Optional[date] = None


class StudentFeeRow(BaseModel):
    """One row per student in the class-wise fee view."""
    student_id: str
    student_name: Optional[str] = None
    admission_number: Optional[str] = None
    standard_name: Optional[str] = None
    section: Optional[str] = None
    # Parent info
    parent_name: Optional[str] = None
    parent_phone: Optional[str] = None
    parent_email: Optional[str] = None
    student_phone: Optional[str] = None
    payment_cycle: str = "UNASSIGNED"
    status: str = "PENDING"
    # Aggregated totals
    total_billed: float = 0.0
    total_paid: float = 0.0
    total_outstanding: float = 0.0
    has_overdue: bool = False
    # Installment breakdown
    installments: list[StudentInstallmentSummary] = []


class ClassFeeStudentListResponse(BaseModel):
    items: list[StudentFeeRow]
    total: int
    page: int = 1
    page_size: int = 50
    total_pages: int = 1
    # Summed only for students in ``items`` (current page), not the whole class.
    total_billed: float = 0.0
    total_paid: float = 0.0
    total_outstanding: float = 0.0


class CustomFeeHeadInput(BaseModel):
    name: str
    amount: float
    due_date: Optional[date] = None
    description: Optional[str] = None
    installment_plan: Optional[list[InstallmentPlanItem]] = None

    @field_validator("name")
    @classmethod
    def name_valid(cls, v: str) -> str:
        normalized = " ".join(v.strip().split())
        if not normalized:
            raise ValueError("Custom fee head name is required")
        if len(normalized) > 120:
            raise ValueError("Custom fee head name must be <= 120 characters")
        return normalized

    @field_validator("amount")
    @classmethod
    def amount_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Amount must be positive")
        return v


class LedgerGenerateRequest(BaseModel):
    standard_id: uuid.UUID
    academic_year_id: Optional[uuid.UUID] = None
    custom_fee_heads: list[CustomFeeHeadInput] = Field(default_factory=list)


class StudentLedgerGenerateRequest(BaseModel):
    """Generate fee ledger for a single student — used for mid-year admissions or overrides."""
    student_id: uuid.UUID
    standard_id: uuid.UUID
    academic_year_id: Optional[uuid.UUID] = None
    payment_cycle: Optional[str] = None


class LedgerGenerateResponse(BaseModel):
    created: int
    skipped: int
    created_structures: int = 0
    updated_structures: int = 0


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------

class PaymentCreate(BaseModel):
    student_id: uuid.UUID
    fee_ledger_id: uuid.UUID
    amount: float
    payment_date: Optional[date] = None
    payment_mode: PaymentMode
    reference_number: Optional[str] = None
    transaction_ref: Optional[str] = None

    @field_validator("amount")
    @classmethod
    def payment_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Amount must be positive")
        return v


class PaymentAllocateCreate(BaseModel):
    student_id: uuid.UUID
    amount: float
    payment_date: Optional[date] = None
    payment_mode: PaymentMode
    payment_cycle: Optional[str] = None
    academic_year_id: Optional[uuid.UUID] = None
    reference_number: Optional[str] = None
    transaction_ref: Optional[str] = None

    @field_validator("amount")
    @classmethod
    def allocate_amount_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Amount must be positive")
        return v


class PaymentAllocationItem(BaseModel):
    payment_id: uuid.UUID
    fee_ledger_id: uuid.UUID
    installment_name: str = ""
    applied_amount: float
    remaining_outstanding: float
    status: FeeStatus


class PaymentAllocateResponse(BaseModel):
    student_id: uuid.UUID
    payment_cycle: str = "UNASSIGNED"
    total_requested: float
    total_applied: float
    total_unapplied: float
    allocations: list[PaymentAllocationItem]


class PaymentResponse(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID
    fee_ledger_id: uuid.UUID
    amount: float
    payment_date: date
    payment_mode: PaymentMode
    reference_number: Optional[str] = None
    transaction_ref: Optional[str] = None
    receipt_key: Optional[str] = None
    recorded_by: Optional[uuid.UUID] = None
    late_fee_applied: bool
    original_due_date: Optional[date] = None
    school_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PaymentListResponse(BaseModel):
    items: list[PaymentResponse]
    total: int


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

class FeeDashboardResponse(BaseModel):
    items: list[FeeLedgerResponse]
    total: int
    total_billed: float = 0.0
    total_paid: float = 0.0
    total_outstanding: float = 0.0
    has_overdue: bool = False


# ---------------------------------------------------------------------------
# Defaulters
# ---------------------------------------------------------------------------

class DefaulterEntry(BaseModel):
    student_id: uuid.UUID
    admission_number: str
    student_name: Optional[str] = None
    standard_id: Optional[uuid.UUID] = None
    section: Optional[str] = None
    overdue_ledgers: int
    total_overdue_amount: float
    oldest_due_date: Optional[date] = None


class DefaulterListResponse(BaseModel):
    academic_year_id: uuid.UUID
    report_date: date
    total_defaulters: int
    defaulters: list[DefaulterEntry]


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

class FeeAnalyticsSummary(BaseModel):
    total_billed_amount: float
    total_paid_amount: float
    total_outstanding_amount: float
    collection_percentage: float
    total_ledgers: int
    total_students: int
    paid_ledgers: int
    partial_ledgers: int
    pending_ledgers: int
    overdue_ledgers: int
    defaulters_count: int
    payments_count: int
    late_payments_count: int


class FeeCategoryAnalyticsItem(BaseModel):
    fee_category: FeeCategory
    billed_amount: float
    paid_amount: float
    outstanding_amount: float
    ledgers: int


class FeeStatusAnalyticsItem(BaseModel):
    status: FeeStatus
    ledgers: int
    billed_amount: float
    paid_amount: float
    outstanding_amount: float


class PaymentModeAnalyticsItem(BaseModel):
    payment_mode: PaymentMode
    amount: float
    transactions: int


class FeeStudentAnalyticsItem(BaseModel):
    student_id: uuid.UUID
    admission_number: str
    standard_id: Optional[uuid.UUID] = None
    section: Optional[str] = None
    billed_amount: float
    paid_amount: float
    outstanding_amount: float
    ledgers: int
    paid_ledgers: int
    partial_ledgers: int
    pending_ledgers: int
    overdue_ledgers: int
    is_defaulter: bool = False
    latest_payment_date: Optional[date] = None


class FeeClassAnalyticsItem(BaseModel):
    standard_id: uuid.UUID
    standard_name: str
    section: Optional[str] = None
    total_students: int
    total_billed: float
    total_paid: float
    total_outstanding: float
    collection_percentage: float
    defaulters_count: int


class FeeInstallmentAnalyticsItem(BaseModel):
    installment_name: str
    total_ledgers: int
    paid_ledgers: int
    partial_ledgers: int
    pending_ledgers: int
    overdue_ledgers: int
    total_billed: float
    total_paid: float
    total_outstanding: float
    collection_percentage: float


class FeeAnalyticsResponse(BaseModel):
    academic_year_id: uuid.UUID
    report_date: date
    filters: dict
    summary: FeeAnalyticsSummary
    by_category: list[FeeCategoryAnalyticsItem]
    by_status: list[FeeStatusAnalyticsItem]
    by_payment_mode: list[PaymentModeAnalyticsItem]
    by_student: list[FeeStudentAnalyticsItem]
    by_class: list[FeeClassAnalyticsItem]
    by_installment: list[FeeInstallmentAnalyticsItem]