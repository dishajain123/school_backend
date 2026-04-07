import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_roles
from app.db.session import get_db
from app.schemas.principal_report import (
    PrincipalReportOverviewResponse,
    PrincipalReportDetailsResponse,
)
from app.services.principal_report import PrincipalReportService
from app.utils.enums import RoleEnum

router = APIRouter(prefix="/principal-reports", tags=["Principal Reports"])


@router.get("/overview", response_model=PrincipalReportOverviewResponse)
async def get_principal_overview(
    academic_year_id: Optional[uuid.UUID] = Query(None),
    report_date: Optional[date] = Query(None),
    current_user: CurrentUser = Depends(
        require_roles(RoleEnum.PRINCIPAL, RoleEnum.SUPERADMIN, RoleEnum.TRUSTEE)
    ),
    db: AsyncSession = Depends(get_db),
):
    return await PrincipalReportService(db).overview(
        current_user=current_user,
        academic_year_id=academic_year_id,
        report_date=report_date or date.today(),
    )


@router.get("/details", response_model=PrincipalReportDetailsResponse)
async def get_principal_details(
    academic_year_id: Optional[uuid.UUID] = Query(None),
    report_date: Optional[date] = Query(None),
    metric: Optional[str] = Query(
        None,
        pattern="^(student_attendance|fees_paid|results|teacher_attendance)$",
    ),
    student_id: Optional[uuid.UUID] = Query(None),
    standard_id: Optional[uuid.UUID] = Query(None),
    section: Optional[str] = Query(None),
    teacher_id: Optional[uuid.UUID] = Query(None),
    subject_id: Optional[uuid.UUID] = Query(None),
    current_user: CurrentUser = Depends(
        require_roles(RoleEnum.PRINCIPAL, RoleEnum.SUPERADMIN, RoleEnum.TRUSTEE)
    ),
    db: AsyncSession = Depends(get_db),
):
    return await PrincipalReportService(db).details(
        current_user=current_user,
        academic_year_id=academic_year_id,
        report_date=report_date or date.today(),
        metric=metric,
        student_id=student_id,
        standard_id=standard_id,
        section=section,
        teacher_id=teacher_id,
        subject_id=subject_id,
    )
