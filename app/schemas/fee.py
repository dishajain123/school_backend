import uuid
from datetime import date, datetime
from typing import Optional, Any

from pydantic import BaseModel, Field, field_validator

from app.utils.enums import FeeCategory, FeeStatus, PaymentMode


# ---------------------------------------------------------------------------
# Installment Plan
# ---------------------------------------------------------------------------

class InstallmentPlanItem(BaseModel):
    """One item in FeeStructure.installment_plan JSON array."""
    name: str = Field(..., min_length=1, max_length=120)
    due_date: date
    amount: float

    @field_validator("amount")
    @classmethod
    def amount_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Installment amount must be positive")
        return v

    @field_validator("name")
    @classmethod
    def name_clean(cls, v: str) -> str:
        v = " ".join(v.strip().split())
        if not v:
            raise ValueError("Installment name is required")
        return v


# ---------------------------------------------------------------------------
# Fee Structure
# ---------------------------------------------------------------------------

class FeeStructureCreate(BaseModel):
    standard_id: uuid.UUID
    academic_year_id: Optional[uuid.UUID] = None
    fee_category: FeeCategory
    custom_fee_head: Optional[str] = None
    amount: float
    due_date: date
    description: Optional[str] = None
    installment_plan: Optional[list[InstallmentPlanItem]] = None

    @field_validator("amount")
    @classmethod
    def amount_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Amount must be positive")
        return v

    @field_validator("custom_fee_head")
    @classmethod
    def normalize_custom_fee_head(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        normalized = " ".join(v.strip().split())
        if not normalized:
            return None
        if len(normalized) > 120:
            raise ValueError("custom_fee_head must be <= 120 characters")
        return normalized


class FeeStructureHeadCreate(BaseModel):
    name: str
    amount: float

    @field_validator("name")
    @classmethod
    def name_valid(cls, v: str) -> str:
        normalized = " ".join(v.strip().split())
        if not normalized:
            raise ValueError("Fee head name is required")
        if len(normalized) > 120:
            raise ValueError("Fee head name must be <= 120 characters")
        return normalized

    @field_validator("amount")
    @classmethod
    def amount_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Amount must be positive")
        return v


class FeeStructureBatchCreate(BaseModel):
    standard_id: Optional[uuid.UUID] = None
    standard_ids: list[uuid.UUID] = Field(default_factory=list)
    apply_to_all_classes: bool = False
    academic_year_id: Optional[uuid.UUID] = None
    due_date: date
    description: Optional[str] = None
    fee_heads: list[FeeStructureHeadCreate] = Field(default_factory=list)
    installment_plan: Optional[list[InstallmentPlanItem]] = None

    @field_validator("fee_heads")
    @classmethod
    def fee_heads_non_empty(cls, v: list[FeeStructureHeadCreate]) -> list[FeeStructureHeadCreate]:
        if not v:
            raise ValueError("At least one fee head is required")
        return v

    @field_validator("standard_ids")
    @classmethod
    def dedupe_standard_ids(cls, v: list[uuid.UUID]) -> list[uuid.UUID]:
        return list(dict.fromkeys(v))


class FeeStructureResponse(BaseModel):
    id: uuid.UUID
    standard_id: uuid.UUID
    academic_year_id: uuid.UUID
    fee_category: FeeCategory
    custom_fee_head: Optional[str] = None
    amount: float
    due_date: date
    description: Optional[str] = None
    school_id: uuid.UUID
    installment_plan: Optional[list[Any]] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("custom_fee_head", mode="before")
    @classmethod
    def empty_custom_head_to_none(cls, v: Optional[str]) -> Optional[str]:
        return v or None


class FeeStructureListResponse(BaseModel):
    items: list[FeeStructureResponse]
    total: int


class FeeStructureBatchResponse(BaseModel):
    items: list[FeeStructureResponse]
    total: int
    created: int
    updated: int


class FeeStructureUpdate(BaseModel):
    custom_fee_head: Optional[str] = None
    amount: Optional[float] = None
    due_date: Optional[date] = None
    description: Optional[str] = None
    apply_to_all_classes: bool = False
    installment_plan: Optional[list[InstallmentPlanItem]] = None

    @field_validator("custom_fee_head")
    @classmethod
    def normalize_custom_fee_head(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        normalized = " ".join(v.strip().split())
        if not normalized:
            return None
        if len(normalized) > 120:
            raise ValueError("custom_fee_head must be <= 120 characters")
        return normalized

    @field_validator("amount")
    @classmethod
    def amount_positive(cls, v: Optional[float]) -> Optional[float]:
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