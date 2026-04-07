import uuid

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_permission, require_roles
from app.db.session import get_db
from app.schemas.fee import (
    FeeStructureCreate,
    FeeStructureResponse,
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


@router.post("/structures", response_model=FeeStructureResponse, status_code=201)
async def create_fee_structure(
    payload: FeeStructureCreate,
    current_user: CurrentUser = Depends(require_permission("fee:create")),
    db: AsyncSession = Depends(get_db),
):
    return await FeeService(db).create_structure(payload, current_user)


@router.post("/ledger/generate", response_model=LedgerGenerateResponse)
async def generate_ledger(
    payload: LedgerGenerateRequest,
    current_user: CurrentUser = Depends(require_permission("fee:create")),
    db: AsyncSession = Depends(get_db),
):
    return await FeeService(db).generate_ledger(payload, current_user)


@router.post("/payments", response_model=PaymentResponse, status_code=201)
async def record_payment(
    payload: PaymentCreate,
    current_user: CurrentUser = Depends(require_permission("fee:create")),
    db: AsyncSession = Depends(get_db),
):
    return await FeeService(db).record_payment(payload, current_user)


@router.get("", response_model=FeeDashboardResponse)
async def fee_dashboard(
    student_id: uuid.UUID = Query(...),
    current_user: CurrentUser = Depends(require_permission("fee:read")),
    db: AsyncSession = Depends(get_db),
):
    return await FeeService(db).fee_dashboard(student_id, current_user)



@router.get("/payments", response_model=PaymentListResponse)
async def list_payments(
    fee_ledger_id: uuid.UUID = Query(...),
    current_user: CurrentUser = Depends(require_permission("fee:read")),
    db: AsyncSession = Depends(get_db),
):
    # NOTE: This endpoint was added to support payment history by ledger.
    return await FeeService(db).list_payments(fee_ledger_id, current_user)

@router.get("/payments/{payment_id}/receipt")
async def get_receipt(
    payment_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("fee:read")),
    db: AsyncSession = Depends(get_db),
):
    url = await FeeService(db).get_receipt_url(payment_id, current_user)
    return {"url": url}


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
    return await FeeService(db).fee_analytics(
        current_user=current_user,
        academic_year_id=academic_year_id,
        report_date=report_date or date.today(),
        standard_id=standard_id,
        section=section,
        student_id=student_id,
    )
