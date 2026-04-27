# app/api/v1/endpoints/bulk.py
"""
Phase 15 — Bulk Operations API.

Endpoints:
  POST /bulk/students        — Bulk student admission (max 200 per request)
  POST /bulk/fees            — Bulk fee structure assignment across classes
  GET  /bulk/students/template — Download CSV template for bulk student import
  GET  /bulk/fees/template    — Download CSV template for bulk fee import

Responsibility split:
  Staff Admin (user:manage) : executes bulk student admission
  Staff Admin (fee:create)  : executes bulk fee assignment
  Admin (Principal)         : validates results and approves
"""
import csv
import io
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.core.dependencies import CurrentUser, get_current_user
from app.schemas.bulk import (
    BulkStudentAdmissionRequest,
    BulkStudentAdmissionResponse,
    BulkFeeAssignmentRequest,
    BulkFeeAssignmentResponse,
    STUDENT_CSV_HEADERS,
    FEE_CSV_HEADERS,
)
from app.services.bulk import BulkService

router = APIRouter(prefix="/bulk", tags=["Bulk Operations"])


def get_service(db: AsyncSession = Depends(get_db)) -> BulkService:
    return BulkService(db)


# ── Bulk Student Admission ────────────────────────────────────────────────────

@router.post("/students", response_model=BulkStudentAdmissionResponse, status_code=201)
async def bulk_admit_students(
    payload: BulkStudentAdmissionRequest,
    current_user: CurrentUser = Depends(get_current_user),
    service: BulkService = Depends(get_service),
):
    """
    Phase 15: Bulk admit up to 200 students in a single request.

    For each row:
    - Creates student user account (ACTIVE, admin-created)
    - Creates parent user+profile (or re-uses existing parent by parent_id)
    - Generates admission number (auto or custom)
    - Creates StudentYearMapping for the specified class/section/year
    - Writes audit log entry

    Duplicate emails/phones are SKIPPED, not errored.
    Row-level errors do not abort other rows.
    Returns per-row status: created | skipped | error.

    Permission: Principal, Superadmin, or staff with user:manage.
    """
    return await service.bulk_admit_students(payload, current_user)


@router.get("/students/template")
async def download_student_template(
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    Download a blank CSV template with all required columns for bulk student admission.
    Fill in one student per row, then POST to /bulk/students.
    """
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(STUDENT_CSV_HEADERS)
    # Example row
    writer.writerow([
        "John Doe",           # full_name
        "john@example.com",   # email
        "+919876543210",      # phone
        "Password@123",       # password
        "",                   # admission_number (leave blank for auto)
        "2010-05-15",         # date_of_birth
        "2024-06-01",         # admission_date
        "NEW_ADMISSION",      # admission_type
        "",                   # parent_id (UUID of existing parent or blank)
        "Jane Doe",           # parent_full_name
        "jane@example.com",   # parent_email
        "+919876543211",      # parent_phone
        "Password@123",       # parent_password
        "MOTHER",             # parent_relation
        "Teacher",            # parent_occupation
        "<standard_uuid>",    # standard_id
        "<section_uuid>",     # section_id
        "<academic_year_uuid>", # academic_year_id
        "1",                  # roll_number
    ])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=bulk_student_template.csv"},
    )


# ── Bulk Fee Assignment ───────────────────────────────────────────────────────

@router.post("/fees", response_model=BulkFeeAssignmentResponse, status_code=201)
async def bulk_assign_fees(
    payload: BulkFeeAssignmentRequest,
    current_user: CurrentUser = Depends(get_current_user),
    service: BulkService = Depends(get_service),
):
    """
    Phase 15: Bulk assign fee structures to multiple classes in one request.

    For each row in `rows`:
    - Validates fee category against FeeCategory enum
    - Checks for duplicate (same school + class + year + category + custom_head)
    - Creates FeeStructure record
    - Writes audit log entry

    Duplicates are SKIPPED, row errors do not abort others.
    Returns per-row status: created | skipped | error.

    Use /fees/ledger/generate per class afterwards to create student ledger entries.

    Permission: Principal, Superadmin, or staff with fee:create.
    """
    return await service.bulk_assign_fees(payload, current_user)


@router.get("/fees/template")
async def download_fee_template(
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    Download a blank CSV template for bulk fee structure assignment.
    academic_year_id is set at the request level (not per-row).
    """
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(FEE_CSV_HEADERS)
    writer.writerow([
        "<standard_uuid>",   # standard_id
        "TUITION",           # fee_category (TUITION/TRANSPORT/LIBRARY/LABORATORY/SPORTS/EXAMINATION/MISCELLANEOUS)
        "Tuition Fee Q1",    # custom_fee_head (optional label)
        "12000.00",          # amount
        "2024-07-31",        # due_date
        "First quarter tuition", # description
    ])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=bulk_fee_template.csv"},
    )