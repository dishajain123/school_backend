import uuid
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, field_validator

from app.utils.enums import FeeCategory, FeeStatus, PaymentMode


class FeeStructureCreate(BaseModel):
    standard_id: uuid.UUID
    academic_year_id: Optional[uuid.UUID] = None
    fee_category: FeeCategory
    amount: float
    due_date: date
    description: Optional[str] = None

    @field_validator("amount")
    @classmethod
    def amount_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Amount must be positive")
        return v


class FeeStructureResponse(BaseModel):
    id: uuid.UUID
    standard_id: uuid.UUID
    academic_year_id: uuid.UUID
    fee_category: FeeCategory
    amount: float
    due_date: date
    description: Optional[str] = None
    school_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class FeeLedgerResponse(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID
    fee_structure_id: uuid.UUID
    total_amount: float
    paid_amount: float
    outstanding_amount: float = 0.0  # computed field — not in DB, set by service
    status: FeeStatus
    school_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class LedgerGenerateRequest(BaseModel):
    standard_id: uuid.UUID
    academic_year_id: Optional[uuid.UUID] = None


class LedgerGenerateResponse(BaseModel):
    created: int
    skipped: int


class PaymentCreate(BaseModel):
    student_id: uuid.UUID
    fee_ledger_id: uuid.UUID
    amount: float
    payment_date: Optional[date] = None
    payment_mode: PaymentMode
    reference_number: Optional[str] = None

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

class FeeDashboardResponse(BaseModel):
    items: list[FeeLedgerResponse]
    total: int


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
    latest_payment_date: Optional[date] = None


class FeeAnalyticsResponse(BaseModel):
    academic_year_id: uuid.UUID
    report_date: date
    filters: dict
    summary: FeeAnalyticsSummary
    by_category: list[FeeCategoryAnalyticsItem]
    by_status: list[FeeStatusAnalyticsItem]
    by_payment_mode: list[PaymentModeAnalyticsItem]
    by_student: list[FeeStudentAnalyticsItem]
