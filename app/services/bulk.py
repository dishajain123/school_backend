# app/services/bulk.py
"""
Phase 15 — Bulk Operations Service.

Provides:
  bulk_admit_students() — admit multiple students + parents + enrollments.
  bulk_assign_fees()    — apply fee structures to multiple classes at once.

Each operation validates individual rows, processes them independently,
and returns a per-row result. Errors in one row do not abort others.
All audit log entries are written for successful rows.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import ValidationException, ForbiddenException
from app.models.fee_structure import FeeStructure
from app.models.student import Student
from app.models.parent import Parent
from app.models.user import User
from app.schemas.bulk import (
    BulkStudentAdmissionRequest,
    BulkStudentAdmissionResponse,
    BulkStudentResultRow,
    BulkFeeAssignmentRequest,
    BulkFeeAssignmentResponse,
    BulkFeeResultRow,
)
from app.services.audit_log import AuditLogService
from app.services.identifier import IdentifierService
from app.utils.enums import (
    RoleEnum,
    UserStatus,
    RegistrationSource,
    IdentifierType,
    AuditAction,
    FeeCategory,
)
from app.core.security import get_password_hash


class BulkService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.audit = AuditLogService(db)
        self.id_service = IdentifierService(db)

    # ─────────────────────────────────────────────────────────────────────────
    # BULK STUDENT ADMISSION
    # ─────────────────────────────────────────────────────────────────────────

    async def bulk_admit_students(
        self,
        body: BulkStudentAdmissionRequest,
        current_user: CurrentUser,
    ) -> BulkStudentAdmissionResponse:
        school_id = current_user.school_id
        if not school_id:
            raise ForbiddenException("School context required")
        if current_user.role not in (
            RoleEnum.PRINCIPAL, RoleEnum.SUPERADMIN
        ) and "user:manage" not in current_user.permissions:
            raise ForbiddenException("Only Principal, Superadmin, or staff with user:manage can bulk admit students")

        results: list[BulkStudentResultRow] = []
        created = 0
        skipped = 0
        error_count = 0

        for row in body.rows:
            row_idx = row.row_index
            try:
                # ── Duplicate check ───────────────────────────────────────
                existing_email = await self.db.execute(
                    select(User).where(User.email == row.email.lower())
                )
                if existing_email.scalar_one_or_none():
                    results.append(BulkStudentResultRow(
                        row_index=row_idx,
                        full_name=row.full_name,
                        email=row.email,
                        status="skipped",
                        error=f"User with email '{row.email}' already exists.",
                    ))
                    skipped += 1
                    continue

                existing_phone = await self.db.execute(
                    select(User).where(User.phone == row.phone)
                )
                if existing_phone.scalar_one_or_none():
                    results.append(BulkStudentResultRow(
                        row_index=row_idx,
                        full_name=row.full_name,
                        email=row.email,
                        status="skipped",
                        error=f"User with phone '{row.phone}' already exists.",
                    ))
                    skipped += 1
                    continue

                # ── Resolve or create parent ──────────────────────────────
                resolved_parent_id: Optional[uuid.UUID] = None

                if row.parent_id:
                    try:
                        resolved_parent_id = uuid.UUID(row.parent_id)
                        parent_check = await self.db.execute(
                            select(Parent).where(
                                Parent.id == resolved_parent_id,
                                Parent.school_id == school_id,
                            )
                        )
                        if not parent_check.scalar_one_or_none():
                            raise ValueError(f"Parent {row.parent_id} not found in this school")
                    except (ValueError, Exception) as e:
                        results.append(BulkStudentResultRow(
                            row_index=row_idx,
                            full_name=row.full_name,
                            email=row.email,
                            status="error",
                            error=str(e),
                        ))
                        error_count += 1
                        continue
                else:
                    # Create parent user + profile
                    if not row.parent_email or not row.parent_phone or not row.parent_password:
                        results.append(BulkStudentResultRow(
                            row_index=row_idx,
                            full_name=row.full_name,
                            email=row.email,
                            status="error",
                            error="parent_email, parent_phone, parent_password are required when parent_id is not provided.",
                        ))
                        error_count += 1
                        continue

                    # Check parent email/phone duplicates
                    pe = await self.db.execute(
                        select(User).where(User.email == row.parent_email.lower())
                    )
                    pp = await self.db.execute(
                        select(User).where(User.phone == row.parent_phone)
                    )
                    existing_parent_user = pe.scalar_one_or_none() or pp.scalar_one_or_none()

                    if existing_parent_user:
                        # Re-use existing parent profile
                        parent_row = await self.db.execute(
                            select(Parent).where(
                                Parent.user_id == existing_parent_user.id,
                                Parent.school_id == school_id,
                            )
                        )
                        parent_obj = parent_row.scalar_one_or_none()
                        if parent_obj:
                            resolved_parent_id = parent_obj.id
                        else:
                            results.append(BulkStudentResultRow(
                                row_index=row_idx,
                                full_name=row.full_name,
                                email=row.email,
                                status="error",
                                error=f"Parent user exists but has no profile in this school.",
                            ))
                            error_count += 1
                            continue
                    else:
                        # Create new parent user
                        parent_user = User(
                            full_name=row.parent_full_name or "",
                            email=row.parent_email.lower(),
                            phone=row.parent_phone,
                            hashed_password=get_password_hash(row.parent_password),
                            role=RoleEnum.PARENT,
                            school_id=school_id,
                            status=UserStatus.ACTIVE,
                            is_active=True,
                            registration_source=RegistrationSource.ADMIN_CREATED,
                        )
                        self.db.add(parent_user)
                        await self.db.flush()

                        # Generate parent code
                        parent_code = await self.id_service.generate(
                            school_id=school_id,
                            identifier_type=IdentifierType.PARENT_CODE,
                            actor=current_user,
                        )
                        parent_obj = Parent(
                            user_id=parent_user.id,
                            school_id=school_id,
                            parent_code=parent_code,
                            occupation=row.parent_occupation,
                            relation=row.parent_relation,
                            identifier_issued_at=datetime.now(timezone.utc),
                        )
                        self.db.add(parent_obj)
                        await self.db.flush()
                        resolved_parent_id = parent_obj.id

                # ── Create student user ───────────────────────────────────
                student_user = User(
                    full_name=row.full_name,
                    email=row.email.lower(),
                    phone=row.phone,
                    hashed_password=get_password_hash(row.password),
                    role=RoleEnum.STUDENT,
                    school_id=school_id,
                    status=UserStatus.ACTIVE,
                    is_active=True,
                    registration_source=RegistrationSource.ADMIN_CREATED,
                )
                self.db.add(student_user)
                await self.db.flush()

                # ── Generate admission number ─────────────────────────────
                admission_number = await self.id_service.generate(
                    school_id=school_id,
                    identifier_type=IdentifierType.ADMISSION_NUMBER,
                    year=datetime.now().year,
                    custom_value=row.admission_number if row.admission_number else None,
                    actor=current_user,
                )

                # ── Create student profile ────────────────────────────────
                now = datetime.now(timezone.utc)
                student = Student(
                    user_id=student_user.id,
                    school_id=school_id,
                    parent_id=resolved_parent_id,
                    admission_number=admission_number,
                    admission_date=row.admission_date or now.date(),
                    date_of_birth=row.date_of_birth,
                    identifier_issued_at=now,
                )
                self.db.add(student)
                await self.db.flush()

                # ── Create enrollment mapping ─────────────────────────────
                from app.models.student_year_mapping import StudentYearMapping
                from app.utils.enums import EnrollmentStatus, AdmissionType as AdmType

                adm_type_map = {
                    "NEW_ADMISSION": AdmType.NEW_ADMISSION,
                    "MID_YEAR": AdmType.MID_YEAR,
                    "TRANSFER_IN": AdmType.TRANSFER_IN,
                    "READMISSION": AdmType.READMISSION,
                }
                adm_type = adm_type_map.get(
                    (row.admission_type or "NEW_ADMISSION").upper(),
                    AdmType.NEW_ADMISSION,
                )

                mapping = StudentYearMapping(
                    student_id=student.id,
                    school_id=school_id,
                    academic_year_id=row.academic_year_id,
                    standard_id=row.standard_id,
                    section_id=row.section_id,
                    roll_number=row.roll_number,
                    status=EnrollmentStatus.ACTIVE,
                    admission_type=adm_type,
                    joined_on=row.admission_date or now.date(),
                    created_by_id=current_user.id,
                    last_modified_by_id=current_user.id,
                )
                self.db.add(mapping)
                await self.db.flush()

                # ── Sync student flat fields ──────────────────────────────
                student.standard_id = row.standard_id
                student.academic_year_id = row.academic_year_id
                await self.db.flush()

                # ── Audit ─────────────────────────────────────────────────
                await self.audit.log(
                    action=AuditAction.STUDENT_ENROLLED,
                    actor_id=current_user.id,
                    target_user_id=student_user.id,
                    entity_type="Student",
                    entity_id=str(student.id),
                    description=(
                        f"Bulk admission: '{row.full_name}' ({admission_number}) "
                        f"admitted via bulk upload by {current_user.full_name}."
                    ),
                    school_id=school_id,
                )

                await self.db.commit()

                results.append(BulkStudentResultRow(
                    row_index=row_idx,
                    full_name=row.full_name,
                    email=row.email,
                    status="created",
                    student_id=student.id,
                    admission_number=admission_number,
                    parent_id=resolved_parent_id,
                ))
                created += 1

            except Exception as exc:
                await self.db.rollback()
                results.append(BulkStudentResultRow(
                    row_index=row_idx,
                    full_name=row.full_name,
                    email=row.email,
                    status="error",
                    error=str(exc),
                ))
                error_count += 1

        return BulkStudentAdmissionResponse(
            total=len(body.rows),
            created=created,
            skipped=skipped,
            error_count=error_count,
            results=results,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # BULK FEE ASSIGNMENT
    # ─────────────────────────────────────────────────────────────────────────

    async def bulk_assign_fees(
        self,
        body: BulkFeeAssignmentRequest,
        current_user: CurrentUser,
    ) -> BulkFeeAssignmentResponse:
        school_id = current_user.school_id
        if not school_id:
            raise ForbiddenException("School context required")
        if "fee:create" not in current_user.permissions and current_user.role not in (
            RoleEnum.PRINCIPAL, RoleEnum.SUPERADMIN
        ):
            raise ForbiddenException("fee:create permission required for bulk fee assignment")

        results: list[BulkFeeResultRow] = []
        created = 0
        skipped = 0
        error_count = 0

        fee_cat_map = {c.value: c for c in FeeCategory}

        for row in body.rows:
            try:
                # Validate fee category
                cat = fee_cat_map.get(row.fee_category.upper())
                if cat is None:
                    results.append(BulkFeeResultRow(
                        standard_id=row.standard_id,
                        fee_category=row.fee_category,
                        status="error",
                        error=f"Invalid fee_category '{row.fee_category}'.",
                    ))
                    error_count += 1
                    continue

                # Check duplicate: same school + standard + year + category + custom_head
                dup_stmt = select(FeeStructure).where(
                    FeeStructure.school_id == school_id,
                    FeeStructure.standard_id == row.standard_id,
                    FeeStructure.academic_year_id == body.academic_year_id,
                    FeeStructure.fee_category == cat,
                )
                if row.custom_fee_head:
                    normalized = " ".join(row.custom_fee_head.strip().split())
                    dup_stmt = dup_stmt.where(
                        FeeStructure.custom_fee_head == normalized
                    )
                dup = await self.db.execute(dup_stmt)
                if dup.scalar_one_or_none():
                    results.append(BulkFeeResultRow(
                        standard_id=row.standard_id,
                        fee_category=row.fee_category,
                        status="skipped",
                        error="Duplicate fee structure (same class + category + year).",
                    ))
                    skipped += 1
                    continue

                structure = FeeStructure(
                    school_id=school_id,
                    standard_id=row.standard_id,
                    academic_year_id=body.academic_year_id,
                    fee_category=cat,
                    custom_fee_head=(
                        " ".join(row.custom_fee_head.strip().split())
                        if row.custom_fee_head else None
                    ),
                    amount=row.amount,
                    due_date=row.due_date,
                    description=row.description,
                )
                self.db.add(structure)
                await self.db.flush()

                await self.audit.log(
                    action=AuditAction.STUDENT_ENROLLED,  # closest available action
                    actor_id=current_user.id,
                    target_user_id=None,
                    entity_type="FeeStructure",
                    entity_id=str(structure.id),
                    description=(
                        f"Bulk fee: {cat.value} ₹{row.amount} assigned to "
                        f"standard {row.standard_id} by {current_user.full_name}."
                    ),
                    school_id=school_id,
                )

                await self.db.commit()
                results.append(BulkFeeResultRow(
                    standard_id=row.standard_id,
                    fee_category=row.fee_category,
                    status="created",
                    structure_id=structure.id,
                ))
                created += 1

            except Exception as exc:
                await self.db.rollback()
                results.append(BulkFeeResultRow(
                    standard_id=row.standard_id,
                    fee_category=row.fee_category,
                    status="error",
                    error=str(exc),
                ))
                error_count += 1

        return BulkFeeAssignmentResponse(
            total=len(body.rows),
            created=created,
            skipped=skipped,
            error_count=error_count,
            results=results,
        )