import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import (
    CurrentUser,
    get_current_user,
    require_permission,
    require_roles,
)
from app.core.exceptions import ForbiddenException
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
    PaymentResponse,
    FeeDashboardResponse,
    PaymentListResponse,
    FeeAnalyticsResponse,
)
from app.services.fee import FeeService
from app.utils.enums import RoleEnum

router = APIRouter(prefix="/fees", tags=["Fees"])

# ---------------------------------------------------------------------------
# Helper: check fee:read or own-scope roles
# ---------------------------------------------------------------------------

def _assert_fee_read(current_user: CurrentUser) -> None:
    can_read = "fee:read" in current_user.permissions
    own_scope = current_user.role in (RoleEnum.STUDENT, RoleEnum.PARENT)
    if not can_read and not own_scope:
        raise ForbiddenException(
            detail="Permission 'fee:read' is required to access this resource"
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
    """Create or update multiple custom fee heads for a class + academic year."""
    return await FeeService(db).create_structures_batch(payload, current_user)


@router.patch("/structures/{structure_id}", response_model=FeeStructureUpdateResponse)
async def update_fee_structure(
    structure_id: uuid.UUID,
    payload: FeeStructureUpdate,
    current_user: CurrentUser = Depends(require_permission("fee:create")),
    db: AsyncSession = Depends(get_db),
):
    """Edit fee head/amount for one class or all classes with the same fee head."""
    return await FeeService(db).update_structure(
        structure_id=structure_id,
        body=payload,
        current_user=current_user,
    )


@router.get("/structures", response_model=FeeStructureListResponse)
async def list_fee_structures(
    standard_id: uuid.UUID = Query(...),
    academic_year_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(require_permission("fee:read")),
    db: AsyncSession = Depends(get_db),
):
    """List fee structures for a class and academic year."""
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
    Already-existing entries are skipped.
    """
    return await FeeService(db).generate_ledger(payload, current_user)


@router.post("/payments", response_model=PaymentResponse, status_code=201)
async def record_payment(
    payload: PaymentCreate,
    current_user: CurrentUser = Depends(require_permission("fee:create")),
    db: AsyncSession = Depends(get_db),
):
    """Record a payment against a fee ledger entry and generate a receipt."""
    return await FeeService(db).record_payment(payload, current_user)


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
    Return all ledger entries for a student.
    Students and parents are restricted to their own data.
    Optionally filter by academic_year_id.
    """
    _assert_fee_read(current_user)
    return await FeeService(db).fee_dashboard(student_id, current_user, academic_year_id)


@router.get("/payments", response_model=PaymentListResponse)
async def list_payments(
    fee_ledger_id: uuid.UUID = Query(...),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all payments for a specific fee ledger entry."""
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


# ---------------------------------------------------------------------------
# Analytics — Principal / Trustee / Superadmin only
# ---------------------------------------------------------------------------

@router.get("/analytics", response_model=FeeAnalyticsResponse)
async def fee_analytics(
    academic_year_id: Optional[uuid.UUID] = Query(None),
    report_date: Optional[date] = Query(None),
    standard_id: Optional[uuid.UUID] = Query(None),
    section: Optional[str] = Query(None),
    student_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(
        require_roles(RoleEnum.PRINCIPAL, RoleEnum.TRUSTEE, RoleEnum.SUPERADMIN)
    ),
    db: AsyncSession = Depends(get_db),
):
    """Aggregated fee analytics with optional filters."""
    return await FeeService(db).fee_analytics(
        current_user=current_user,
        academic_year_id=academic_year_id,
        report_date=report_date or date.today(),
        standard_id=standard_id,
        section=section,
        student_id=student_id,
    )
