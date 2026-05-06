# app/api/v1/endpoints/fees.py
import uuid
import math
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import (
    CurrentUser,
    get_current_user,
    require_permission,
    require_roles,
)
from app.core.exceptions import ForbiddenException
from app.repositories.parent import ParentRepository
from app.repositories.student import StudentRepository
from app.db.session import get_db
from app.schemas.fee import (
    FeeStructureListResponse,
    FeeStructureBatchCreate,
    FeeStructureBatchResponse,
    FeeStructureUpdate,
    FeeStructureUpdateResponse,
    LedgerGenerateRequest,
    LedgerGenerateResponse,
    PaymentCreate,
    PaymentAllocateCreate,
    PaymentAllocateResponse,
    PaymentResponse,
    FeeDashboardResponse,
    PaymentListResponse,
    FeeAnalyticsResponse,
    DefaulterListResponse,
    AdminLedgerListResponse,
    StudentLedgerGenerateRequest,
    ClassFeeStudentListResponse,
)
from app.services.fee import FeeService
from app.utils.enums import RoleEnum

router = APIRouter(prefix="/fees", tags=["Fees"])

# ---------------------------------------------------------------------------
# Helper: check fee:read or own-scope roles
# ---------------------------------------------------------------------------

def _assert_fee_read(current_user: CurrentUser) -> None:
    can_read = "fee:read" in current_user.permissions or "fee:create" in current_user.permissions
    own_scope = current_user.role in (RoleEnum.STUDENT, RoleEnum.PARENT)
    if not can_read and not own_scope:
        raise ForbiddenException(
            detail="Permission 'fee:read' or 'fee:create' is required to access this resource"
        )


def _assert_analytics_access(current_user: CurrentUser) -> None:
    allowed = (RoleEnum.PRINCIPAL, RoleEnum.TRUSTEE, RoleEnum.STAFF_ADMIN)
    has_fee_access = (
        "fee:read" in current_user.permissions
        or "fee:create" in current_user.permissions
    )
    if current_user.role not in allowed and not has_fee_access:
        raise ForbiddenException(
            detail="Fee analytics access requires Principal/Trustee/staff admin role or fee permissions"
        )


# ---------------------------------------------------------------------------
# Write endpoints — require fee:create permission
# ---------------------------------------------------------------------------

@router.post("/structures/batch", response_model=FeeStructureBatchResponse, status_code=201)
async def create_fee_structure_batch(
    payload: FeeStructureBatchCreate,
    current_user: CurrentUser = Depends(require_permission("fee:create")),
    db: AsyncSession = Depends(get_db),
):
    """
    Create or update multiple custom fee heads for a class + academic year.
    Supports optional installment_plan in the payload to configure installment-based billing.
    """
    return await FeeService(db).create_structures_batch(payload, current_user)


@router.patch("/structures/{structure_id}", response_model=FeeStructureUpdateResponse)
async def update_fee_structure(
    structure_id: uuid.UUID,
    payload: FeeStructureUpdate,
    current_user: CurrentUser = Depends(require_permission("fee:create")),
    db: AsyncSession = Depends(get_db),
):
    """Edit fee head/amount/installment_plan for one class or all classes with the same fee head."""
    return await FeeService(db).update_structure(
        structure_id=structure_id,
        body=payload,
        current_user=current_user,
    )


@router.delete("/structures/{structure_id}", status_code=204)
async def delete_fee_structure(
    structure_id: uuid.UUID,
    delete_linked_entries: bool = Query(False),
    current_user: CurrentUser = Depends(require_permission("fee:create")),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete a fee structure.
    - Cannot delete if ledger entries exist for this structure (use update instead).
    - Returns 204 No Content on success.
    """
    await FeeService(db).delete_structure(
        structure_id=structure_id,
        current_user=current_user,
        delete_linked_entries=delete_linked_entries,
    )


@router.get("/structures", response_model=FeeStructureListResponse)
async def list_fee_structures(
    standard_id: uuid.UUID = Query(...),
    academic_year_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List fee structures for a class and academic year (includes installment_plan)."""
    _assert_fee_read(current_user)
    return await FeeService(db).list_structures(
        standard_id=standard_id,
        academic_year_id=academic_year_id,
        current_user=current_user,
    )


@router.post("/ledger/generate", response_model=LedgerGenerateResponse)
async def generate_ledger(
    payload: LedgerGenerateRequest,
    current_user: CurrentUser = Depends(require_permission("fee:create")),
    db: AsyncSession = Depends(get_db),
):
    """
    Idempotent: generate fee ledger entries for all students in a class.

    - If a FeeStructure has installment_plan: ONE ledger row per student per installment.
    - If no installment_plan: ONE ledger row per student per structure.
    - Already-existing entries (student + structure + installment_name) are skipped.
    - Overdue status is set automatically for past-due installments.
    """
    return await FeeService(db).generate_ledger(payload, current_user)


@router.post("/ledger/generate-student", response_model=LedgerGenerateResponse, status_code=201)
async def generate_student_ledger(
    payload: StudentLedgerGenerateRequest,
    current_user: CurrentUser = Depends(require_permission("fee:create")),
    db: AsyncSession = Depends(get_db),
):
    """
    Generate/assign fee ledger for a single student (individual override or mid-year admission).
    Idempotent — already-existing entries are skipped.
    """
    return await FeeService(db).generate_student_ledger(payload, current_user)


@router.get("/ledger/class-students", response_model=ClassFeeStudentListResponse)
async def list_class_fee_students(
    standard_id: uuid.UUID = Query(...),
    academic_year_id: Optional[uuid.UUID] = Query(None),
    section: Optional[str] = Query(None),
    payment_cycle: Optional[str] = Query(
        None, description="MONTHLY|QUARTERLY|YEARLY|CUSTOM|UNASSIGNED"
    ),
    status: Optional[str] = Query(None, description="PENDING|PARTIAL|PAID|OVERDUE"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Admin: one row per student for a class, with parent info and installment breakdown.

    Filters and pagination are evaluated in the database (count + page of student IDs),
    then ledger lines are loaded only for that page. Aggregate money fields on the
    response refer to the current page only.
    Automatically refreshes overdue statuses before returning.
    """
    _assert_fee_read(current_user)
    return await FeeService(db).list_class_fee_students(
        current_user=current_user,
        standard_id=standard_id,
        academic_year_id=academic_year_id,
        section=section,
        payment_cycle=payment_cycle,
        status_filter=status,
        page=page,
        page_size=page_size,
    )


@router.get("/ledger", response_model=AdminLedgerListResponse)
async def list_ledger_entries(
    standard_id: Optional[uuid.UUID] = Query(None),
    academic_year_id: Optional[uuid.UUID] = Query(None),
    student_id: Optional[uuid.UUID] = Query(None),
    status: Optional[str] = Query(None, description="PENDING|PARTIAL|PAID|OVERDUE"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Admin: list all fee ledger entries across students.
    Filterable by class, academic year, student, and status.
    Includes student name, admission number, total/paid/outstanding amounts.
    """
    _assert_fee_read(current_user)
    return await FeeService(db).list_admin_ledgers(
        current_user=current_user,
        standard_id=standard_id,
        academic_year_id=academic_year_id,
        student_id=student_id,
        status=status,
        page=page,
        page_size=page_size,
    )


@router.post("/payments", response_model=PaymentResponse, status_code=201)
async def record_payment(
    payload: PaymentCreate,
    current_user: CurrentUser = Depends(require_permission("fee:create")),
    db: AsyncSession = Depends(get_db),
):
    """
    Record a payment against a fee ledger entry.

    - Validates that payment does not exceed outstanding balance (overpayment prevention).
    - Auto-computes ledger status: PAID / PARTIAL / OVERDUE.
    - Updates last_payment_date on the ledger.
    - Generates a PDF receipt and stores it in MinIO.
    - Supports transaction_ref for external payment gateway reference.
    """
    return await FeeService(db).record_payment(payload, current_user)


@router.post("/payments/allocate", response_model=PaymentAllocateResponse, status_code=201)
async def allocate_student_payment(
    payload: PaymentAllocateCreate,
    current_user: CurrentUser = Depends(require_permission("fee:create")),
    db: AsyncSession = Depends(get_db),
):
    """
    Record one consolidated payment for a student and auto-allocate it
    across overdue/pending ledgers in due-date order.
    """
    return await FeeService(db).allocate_student_payment(payload, current_user)


# ---------------------------------------------------------------------------
# Read endpoints — fee:read permission OR student/parent own-scope
# ---------------------------------------------------------------------------

@router.get("", response_model=FeeDashboardResponse)
async def fee_dashboard(
    student_id: uuid.UUID = Query(...),
    academic_year_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Return all ledger entries for a student, grouped by installment.

    - Students and parents are restricted to their own data.
    - Response includes: total_billed, total_paid, total_outstanding, has_overdue.
    - Lazily marks overdue installments on first fetch for accuracy.
    """
    _assert_fee_read(current_user)
    return await FeeService(db).fee_dashboard(student_id, current_user, academic_year_id)


@router.get("/me", response_model=FeeDashboardResponse)
async def my_fee_dashboard(
    student_id: Optional[uuid.UUID] = Query(None),
    academic_year_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _assert_fee_read(current_user)

    target_student_id: Optional[uuid.UUID] = student_id
    student_repo = StudentRepository(db)

    if current_user.role == RoleEnum.STUDENT:
        me = await student_repo.get_by_user_id(current_user.id)
        if not me:
            raise ForbiddenException(detail="Student profile not found for current user")
        target_student_id = me.id
    elif current_user.role == RoleEnum.PARENT and target_student_id is None:
        parent = await ParentRepository(db).get_by_user_id(current_user.id)
        if not parent:
            raise ForbiddenException(detail="Parent profile not found for current user")
        children = await student_repo.list_by_parent(parent.id, current_user.school_id)
        if not children:
            raise ForbiddenException(detail="No linked children found for current parent")
        if len(children) > 1:
            raise ForbiddenException(
                detail="Multiple linked children found. Please provide student_id."
            )
        target_student_id = children[0].id

    if target_student_id is None:
        raise ForbiddenException(detail="student_id is required for this role")

    return await FeeService(db).fee_dashboard(target_student_id, current_user, academic_year_id)


@router.get("/payments", response_model=PaymentListResponse)
async def list_payments(
    fee_ledger_id: uuid.UUID = Query(...),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all payments for a specific fee ledger entry (installment)."""
    _assert_fee_read(current_user)
    return await FeeService(db).list_payments(fee_ledger_id, current_user)


@router.get("/payments/{payment_id}/receipt")
async def get_receipt(
    payment_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a presigned URL for the payment receipt PDF."""
    _assert_fee_read(current_user)
    url = await FeeService(db).get_receipt_url(payment_id, current_user)
    return {"url": url}


@router.get("/payments/{payment_id}/receipt-fallback", response_class=HTMLResponse)
async def get_receipt_fallback(
    payment_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Fallback receipt page when object storage URL generation is unavailable."""
    _assert_fee_read(current_user)
    data = await FeeService(db).get_receipt_fallback_data(payment_id, current_user)
    return f"""
    <html>
      <head><title>Payment Receipt</title></head>
      <body style="font-family: Arial, sans-serif; padding: 24px;">
        <h2>Payment Receipt (Fallback)</h2>
        <p><b>Payment ID:</b> {data["payment_id"]}</p>
        <p><b>Student ID:</b> {data["student_id"]}</p>
        <p><b>Ledger ID:</b> {data["fee_ledger_id"]}</p>
        <p><b>Amount:</b> INR {data["amount"]:.2f}</p>
        <p><b>Date:</b> {data["payment_date"]}</p>
        <p><b>Mode:</b> {data["payment_mode"]}</p>
        <p><b>Reference No:</b> {data["reference_number"]}</p>
        <p><b>Transaction Ref:</b> {data["transaction_ref"]}</p>
      </body>
    </html>
    """


# ---------------------------------------------------------------------------
# Defaulters — Principal / Trustee / staff admin only
# ---------------------------------------------------------------------------

@router.get("/defaulters", response_model=DefaulterListResponse)
async def get_defaulters(
    academic_year_id: Optional[uuid.UUID] = Query(None),
    standard_id: Optional[uuid.UUID] = Query(None),
    section: Optional[str] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    List all defaulters (students with at least one OVERDUE installment).

    - Automatically refreshes overdue statuses before querying.
    - Returns: student info, count of overdue ledgers, total overdue amount, oldest due date.
    - Filterable by class and section.
    """
    _assert_analytics_access(current_user)
    return await FeeService(db).get_defaulters(
        current_user=current_user,
        academic_year_id=academic_year_id,
        standard_id=standard_id,
        section=section,
    )


# ---------------------------------------------------------------------------
# Overdue refresh — Principal / Trustee / staff admin only
# ---------------------------------------------------------------------------

@router.post("/ledger/refresh-overdue")
async def refresh_overdue(
    academic_year_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Bulk-refresh overdue statuses for all unpaid/partial ledgers past their due date.
    Safe to call repeatedly (idempotent). Returns count of updated rows.
    """
    _assert_analytics_access(current_user)
    return await FeeService(db).refresh_overdue_statuses(
        current_user=current_user,
        academic_year_id=academic_year_id,
    )


# ---------------------------------------------------------------------------
# Analytics — Principal / Trustee / staff admin only
# ---------------------------------------------------------------------------

@router.get("/analytics", response_model=FeeAnalyticsResponse)
async def fee_analytics(
    academic_year_id: Optional[uuid.UUID] = Query(None),
    report_date: Optional[date] = Query(None),
    standard_id: Optional[uuid.UUID] = Query(None),
    section: Optional[str] = Query(None),
    student_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Aggregated fee analytics with optional filters.

    Returns:
    - Summary: total collected, pending, defaulters count, collection %
    - by_category: fee head-wise breakdown
    - by_status: PAID/PARTIAL/PENDING/OVERDUE breakdown
    - by_payment_mode: cash/UPI/card breakdown
    - by_student: per-student collection with defaulter flag
    - by_class: class-wise collection with defaulters count
    - by_installment: installment-wise collection (when installment plan is used)
    """
    _assert_analytics_access(current_user)
    return await FeeService(db).fee_analytics(
        current_user=current_user,
        academic_year_id=academic_year_id,
        report_date=report_date or date.today(),
        standard_id=standard_id,
        section=section,
        student_id=student_id,
    )
