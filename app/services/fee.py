# app/services/fee.py
from __future__ import annotations

import math
import uuid
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select, and_, func, distinct, case
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.dependencies import CurrentUser
from app.core.exceptions import ForbiddenException, NotFoundException, ValidationException
from app.models.fee import FeeStructure, FeeLedger
from app.models.payment import Payment
from app.models.student import Student
from app.models.user import User
from app.repositories.fee import FeeRepository
from app.schemas.fee import (
    FeeStructureBatchCreate,
    FeeStructureBatchResponse,
    FeeStructureResponse,
    FeeStructureUpdate,
    FeeStructureUpdateResponse,
    LedgerGenerateRequest,
    LedgerGenerateResponse,
    StudentLedgerGenerateRequest,
    PaymentCreate,
    PaymentAllocateCreate,
    PaymentAllocateResponse,
    PaymentAllocationItem,
    PaymentResponse,
    FeeDashboardResponse,
    FeeLedgerResponse,
    PaymentListResponse,
    FeeAnalyticsResponse,
    FeeAnalyticsSummary,
    FeeCategoryAnalyticsItem,
    FeeStatusAnalyticsItem,
    PaymentModeAnalyticsItem,
    FeeStudentAnalyticsItem,
    FeeClassAnalyticsItem,
    FeeInstallmentAnalyticsItem,
    DefaulterListResponse,
    DefaulterEntry,
    AdminLedgerListResponse,
    AdminLedgerEntry,
    FeeStructureListResponse,
    ClassFeeStudentListResponse,
    StudentFeeRow,
    StudentInstallmentSummary,
)
from app.utils.enums import FeeCategory, FeeStatus, PaymentMode, RoleEnum


class FeeService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = FeeRepository(db)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _ensure_school(self, current_user: CurrentUser) -> uuid.UUID:
        if not current_user.school_id:
            raise ForbiddenException("School context required")
        return current_user.school_id

    async def _resolve_academic_year(
        self, school_id: uuid.UUID, academic_year_id: Optional[uuid.UUID]
    ) -> uuid.UUID:
        if academic_year_id:
            return academic_year_id
        from app.models.academic_year import AcademicYear
        result = await self.db.execute(
            select(AcademicYear).where(
                and_(
                    AcademicYear.school_id == school_id,
                    AcademicYear.is_active.is_(True),
                )
            )
        )
        year = result.scalar_one_or_none()
        if not year:
            raise ValidationException("No active academic year found for school")
        return year.id

    def _normalize_custom_fee_head(self, value: Optional[str]) -> str:
        if not value:
            return ""
        return " ".join(value.strip().split())

    def _compute_ledger_status(
        self,
        paid: float,
        total: float,
        due_date: Optional[date],
        today: date,
    ) -> FeeStatus:
        if paid >= total - 0.01:
            return FeeStatus.PAID
        if paid > 0:
            if due_date and today > due_date:
                return FeeStatus.OVERDUE
            return FeeStatus.PARTIAL
        if due_date and today > due_date:
            return FeeStatus.OVERDUE
        return FeeStatus.PENDING

    def _serialize_structure(self, structure: FeeStructure) -> FeeStructureResponse:
        """
        Build a FeeStructureResponse without triggering async lazy-loads.
        """
        payload = {
            "id": structure.id,
            "standard_id": structure.standard_id,
            "academic_year_id": structure.academic_year_id,
            "fee_category": structure.fee_category,
            "custom_fee_head": structure.custom_fee_head or None,
            "amount": structure.amount,
            "due_date": structure.due_date,
            "description": structure.description,
            "installment_plan": structure.installment_plan,
            "school_id": structure.school_id,
            "created_at": structure.created_at,
            "updated_at": structure.updated_at,
            "standard": None,
            "academic_year": None,
        }

        # Avoid relationship lazy loading; use related objects only if already present.
        standard_obj = structure.__dict__.get("standard")
        if standard_obj is not None:
            payload["standard"] = standard_obj

        academic_year_obj = structure.__dict__.get("academic_year")
        if academic_year_obj is not None:
            payload["academic_year"] = academic_year_obj

        return FeeStructureResponse.model_validate(payload)

    async def _assert_student_access(
        self,
        school_id: uuid.UUID,
        student_id: uuid.UUID,
        current_user: CurrentUser,
    ) -> None:
        if current_user.role in (RoleEnum.STUDENT, RoleEnum.PARENT):
            if current_user.role == RoleEnum.STUDENT:
                result = await self.db.execute(
                    select(Student).where(
                        and_(
                            Student.id == student_id,
                            Student.user_id == current_user.id,
                            Student.school_id == school_id,
                        )
                    )
                )
                if not result.scalar_one_or_none():
                    raise ForbiddenException("Access denied to this student's fee records")
            elif current_user.role == RoleEnum.PARENT:
                from app.models.parent import Parent
                result = await self.db.execute(
                    select(Parent).where(
                        and_(
                            Parent.user_id == current_user.id,
                            Parent.school_id == school_id,
                        )
                    )
                )
                parent = result.scalar_one_or_none()
                if not parent:
                    raise ForbiddenException("Parent record not found")
                # Check child linkage strictly against this parent.
                from app.models.student import Student as StudentModel
                result2 = await self.db.execute(
                    select(StudentModel)
                    .where(
                        and_(
                            StudentModel.id == student_id,
                            StudentModel.school_id == school_id,
                            StudentModel.parent_id == parent.id,
                        )
                    )
                )
                student_obj = result2.scalar_one_or_none()
                if not student_obj:
                    raise ForbiddenException("Access denied to this student's fee records")

    async def _sync_ledgers_for_structure(
        self, school_id: uuid.UUID, structure: FeeStructure
    ) -> None:
        """Update existing PENDING ledgers when structure amount/due_date changes."""
        from sqlalchemy import update as sa_update
        ledgers_result = await self.db.execute(
            select(FeeLedger).where(
                and_(
                    FeeLedger.fee_structure_id == structure.id,
                    FeeLedger.school_id == school_id,
                    FeeLedger.paid_amount == 0,
                )
            )
        )
        ledgers = list(ledgers_result.scalars().all())
        for ledger in ledgers:
            ledger.total_amount = structure.amount
            ledger.due_date = structure.due_date

    # ------------------------------------------------------------------
    # Fee Structure Batch Create
    # ------------------------------------------------------------------

    async def create_structures_batch(
        self,
        body: FeeStructureBatchCreate,
        current_user: CurrentUser,
    ) -> FeeStructureBatchResponse:
        school_id = self._ensure_school(current_user)
        structures = []
        seen_structure_ids: set[uuid.UUID] = set()
        created = updated = 0

        for item in body.structures:
            resolved_year_id = await self._resolve_academic_year(
                school_id, item.academic_year_id
            )
            custom_fee_head = self._normalize_custom_fee_head(item.custom_fee_head)
            installment_plan = None
            if item.installment_plan:
                installment_plan = [
                    {
                        "name": ip.name,
                        "due_date": ip.due_date.isoformat(),
                        "amount": ip.amount,
                    }
                    for ip in item.installment_plan
                ]

            existing = await self.repo.get_structure_duplicate(
                school_id=school_id,
                standard_id=item.standard_id,
                academic_year_id=resolved_year_id,
                fee_category=item.fee_category,
                custom_fee_head=custom_fee_head,
            )

            is_created = False
            if existing:
                existing_ledger_count = await self.repo.count_ledgers_for_structure(
                    existing.id, school_id
                )
                if existing_ledger_count > 0:
                    raise ValidationException(
                        "Fee structure is immutable after assignment. "
                        "Create a new fee head/version instead of updating the existing one."
                    )
                structure = await self.repo.update_structure(
                    existing,
                    {
                        "amount": item.amount,
                        "due_date": item.due_date,
                        "description": item.description,
                        "installment_plan": installment_plan,
                    },
                )
                updated += 1
            else:
                structure = await self.repo.create_structure(
                    {
                        "school_id": school_id,
                        "standard_id": item.standard_id,
                        "academic_year_id": resolved_year_id,
                        "fee_category": item.fee_category,
                        "custom_fee_head": custom_fee_head,
                        "amount": item.amount,
                        "due_date": item.due_date,
                        "description": item.description,
                        "installment_plan": installment_plan,
                    }
                )
                is_created = True
                created += 1

            if structure.id not in seen_structure_ids:
                structures.append(structure)
                seen_structure_ids.add(structure.id)

        for s in structures:
            await self.db.refresh(s)

        return FeeStructureBatchResponse(
            items=[self._serialize_structure(s) for s in structures],
            total=len(structures),
            created=created,
            updated=updated,
        )

    # ------------------------------------------------------------------
    # Fee Structure Update
    # ------------------------------------------------------------------

    async def update_structure(
        self,
        *,
        structure_id: uuid.UUID,
        body: FeeStructureUpdate,
        current_user: CurrentUser,
    ) -> FeeStructureUpdateResponse:
        school_id = self._ensure_school(current_user)
        source_structure = await self.repo.get_structure_by_id(structure_id, school_id)
        if not source_structure:
            raise NotFoundException("Fee structure")

        target_structures = [source_structure]
        if body.apply_to_all_classes:
            matching = await self.db.execute(
                select(FeeStructure).where(
                    and_(
                        FeeStructure.school_id == school_id,
                        FeeStructure.academic_year_id == source_structure.academic_year_id,
                        FeeStructure.fee_category == source_structure.fee_category,
                        FeeStructure.custom_fee_head == source_structure.custom_fee_head,
                        FeeStructure.id != source_structure.id,
                    )
                )
            )
            target_structures.extend(matching.scalars().all())

        update_data: dict = {}
        if body.amount is not None:
            update_data["amount"] = body.amount
        if body.due_date is not None:
            update_data["due_date"] = body.due_date
        if body.description is not None:
            update_data["description"] = body.description
        if body.custom_fee_head is not None:
            update_data["custom_fee_head"] = self._normalize_custom_fee_head(body.custom_fee_head)
        if body.installment_plan is not None:
            update_data["installment_plan"] = [
                {
                    "name": item.name,
                    "due_date": item.due_date.isoformat(),
                    "amount": item.amount,
                }
                for item in body.installment_plan
            ]

        updated_structures = []
        for structure in target_structures:
            linked_ledger_count = await self.repo.count_ledgers_for_structure(
                structure.id, school_id
            )
            if linked_ledger_count > 0:
                raise ValidationException(
                    "Cannot update fee structure after student ledger assignment. "
                    "Create a new fee structure version for future assignments."
                )
            updated = await self.repo.update_structure(structure, update_data)
            await self._sync_ledgers_for_structure(school_id=school_id, structure=updated)
            updated_structures.append(updated)

        for s in updated_structures:
            await self.db.refresh(s)

        return FeeStructureUpdateResponse(
            items=[self._serialize_structure(s) for s in updated_structures],
            total=len(updated_structures),
        )

    # ------------------------------------------------------------------
    # Fee Structure Delete
    # ------------------------------------------------------------------

    async def delete_structure(
        self,
        *,
        structure_id: uuid.UUID,
        current_user: CurrentUser,
        delete_linked_entries: bool = False,
    ) -> None:
        school_id = self._ensure_school(current_user)
        structure = await self.repo.get_structure_by_id(structure_id, school_id)
        if not structure:
            raise NotFoundException("Fee structure")

        ledger_count = await self.repo.count_ledgers_for_structure(structure_id, school_id)
        if ledger_count > 0:
            if not delete_linked_entries:
                raise ValidationException(
                    f"Fee structure is linked with {ledger_count} ledger entries. "
                    "Confirm delete_linked_entries=true to delete linked records as well."
                )
            # Cascade cleanup: deleting ledgers will cascade payments through FK.
            await self.repo.delete_ledgers_for_structure(structure_id, school_id)

        await self.repo.delete_structure(structure)

    # ------------------------------------------------------------------
    # Fee Structure List
    # ------------------------------------------------------------------

    async def list_structures(
        self,
        *,
        standard_id: uuid.UUID,
        academic_year_id: Optional[uuid.UUID],
        current_user: CurrentUser,
    ) -> FeeStructureListResponse:
        school_id = self._ensure_school(current_user)
        resolved_year_id = await self._resolve_academic_year(school_id, academic_year_id)
        structures = await self.repo.list_structures_for_standard(
            school_id=school_id,
            standard_id=standard_id,
            academic_year_id=resolved_year_id,
        )
        items = [self._serialize_structure(s) for s in structures]
        return FeeStructureListResponse(items=items, total=len(items))

    # ------------------------------------------------------------------
    # Ledger Generation (IDEMPOTENT) — class-wide
    # ------------------------------------------------------------------

    async def generate_ledger(
        self,
        body: LedgerGenerateRequest,
        current_user: CurrentUser,
    ) -> LedgerGenerateResponse:
        school_id = self._ensure_school(current_user)
        resolved_year_id = await self._resolve_academic_year(school_id, body.academic_year_id)

        # Step 1: Create any custom fee heads from the request
        created_structures = updated_structures = 0
        if body.custom_fee_heads:
            for cfh in body.custom_fee_heads:
                custom_head = self._normalize_custom_fee_head(cfh.name)
                installment_plan = None
                if cfh.installment_plan:
                    installment_plan = [
                        {
                            "name": ip.name,
                            "due_date": ip.due_date.isoformat(),
                            "amount": ip.amount,
                        }
                        for ip in cfh.installment_plan
                    ]

                existing = await self.repo.get_structure_duplicate(
                    school_id=school_id,
                    standard_id=body.standard_id,
                    academic_year_id=resolved_year_id,
                    fee_category=FeeCategory.MISCELLANEOUS,
                    custom_fee_head=custom_head,
                )
                if existing:
                    await self.repo.update_structure(
                        existing,
                        {
                            "amount": cfh.amount,
                            "due_date": cfh.due_date,
                            "description": cfh.description,
                            "installment_plan": installment_plan,
                        },
                    )
                    updated_structures += 1
                else:
                    await self.repo.create_structure(
                        {
                            "school_id": school_id,
                            "standard_id": body.standard_id,
                            "academic_year_id": resolved_year_id,
                            "fee_category": FeeCategory.MISCELLANEOUS,
                            "custom_fee_head": custom_head,
                            "amount": cfh.amount,
                            "due_date": cfh.due_date,
                            "description": cfh.description,
                            "installment_plan": installment_plan,
                        }
                    )
                    created_structures += 1

        # Step 2: Fetch all structures for this class+year
        structures = await self.repo.list_structures_for_standard(
            school_id=school_id,
            standard_id=body.standard_id,
            academic_year_id=resolved_year_id,
        )
        if not structures:
            return LedgerGenerateResponse(
                created=0,
                skipped=0,
                created_structures=created_structures,
                updated_structures=updated_structures,
            )

        # Step 3: Fetch all active students in this class
        students_result = await self.db.execute(
            select(Student.id).where(
                and_(
                    Student.school_id == school_id,
                    Student.standard_id == body.standard_id,
                )
            )
        )
        student_ids = [row[0] for row in students_result.all()]

        created = skipped = 0
        today = datetime.now(timezone.utc).date()

        for student_id in student_ids:
            for structure in structures:
                installment_plan = structure.installment_plan or []

                if installment_plan:
                    for installment in installment_plan:
                        inst_name = installment.get("name", "")
                        inst_due = (
                            date.fromisoformat(installment["due_date"])
                            if isinstance(installment.get("due_date"), str)
                            else installment.get("due_date")
                        )
                        inst_amount = float(installment.get("amount", structure.amount))

                        existing = await self.repo.get_ledger_duplicate(
                            student_id=student_id,
                            fee_structure_id=structure.id,
                            installment_name=inst_name,
                        )
                        if existing:
                            skipped += 1
                            continue

                        initial_status = self._compute_ledger_status(
                            0, inst_amount, inst_due, today
                        )
                        await self.repo.create_ledger(
                            {
                                "student_id": student_id,
                                "fee_structure_id": structure.id,
                                "installment_name": inst_name,
                                "due_date": inst_due,
                                "total_amount": inst_amount,
                                "paid_amount": 0,
                                "status": initial_status,
                                "school_id": school_id,
                            }
                        )
                        created += 1
                else:
                    existing = await self.repo.get_ledger_duplicate(
                        student_id=student_id,
                        fee_structure_id=structure.id,
                        installment_name="",
                    )
                    if existing:
                        skipped += 1
                        continue

                    initial_status = self._compute_ledger_status(
                        0, float(structure.amount), structure.due_date, today
                    )
                    await self.repo.create_ledger(
                        {
                            "student_id": student_id,
                            "fee_structure_id": structure.id,
                            "installment_name": "",
                            "due_date": structure.due_date,
                            "total_amount": structure.amount,
                            "paid_amount": 0,
                            "status": initial_status,
                            "school_id": school_id,
                        }
                    )
                    created += 1

        return LedgerGenerateResponse(
            created=created,
            skipped=skipped,
            created_structures=created_structures,
            updated_structures=updated_structures,
        )

    # ------------------------------------------------------------------
    # Ledger Generation — single student (mid-year or override)
    # ------------------------------------------------------------------

    async def generate_student_ledger(
        self,
        body: StudentLedgerGenerateRequest,
        current_user: CurrentUser,
    ) -> LedgerGenerateResponse:
        school_id = self._ensure_school(current_user)
        resolved_year_id = await self._resolve_academic_year(school_id, body.academic_year_id)

        student_result = await self.db.execute(
            select(Student).where(
                and_(
                    Student.id == body.student_id,
                    Student.school_id == school_id,
                )
            )
        )
        student = student_result.scalar_one_or_none()
        if not student:
            raise NotFoundException("Student")
        if student.standard_id != body.standard_id:
            raise ValidationException("Student does not belong to the selected class")
        if student.academic_year_id and student.academic_year_id != resolved_year_id:
            raise ValidationException("Student does not belong to the selected academic year")

        structures = await self.repo.list_structures_for_standard(
            school_id=school_id,
            standard_id=body.standard_id,
            academic_year_id=resolved_year_id,
        )

        created = skipped = 0
        today = datetime.now(timezone.utc).date()
        cycle = (body.payment_cycle or "").strip().upper()

        def _cycle_installments(total_amount: float, base_due: Optional[date]) -> list[dict]:
            if cycle not in {"MONTHLY", "QUARTERLY"}:
                return []
            count = 12 if cycle == "MONTHLY" else 4
            month_step = 1 if cycle == "MONTHLY" else 3
            prefix = "Month" if cycle == "MONTHLY" else "Quarter"
            due_base = base_due or today
            per_amount = round(total_amount / count, 2)
            running = 0.0
            rows: list[dict] = []
            for i in range(count):
                due = date(
                    due_base.year + ((due_base.month - 1 + (i * month_step)) // 12),
                    ((due_base.month - 1 + (i * month_step)) % 12) + 1,
                    due_base.day,
                )
                is_last = i == count - 1
                amount = round(total_amount - running, 2) if is_last else per_amount
                running += amount
                rows.append(
                    {
                        "name": f"{prefix} {i + 1}",
                        "due_date": due,
                        "amount": amount,
                    }
                )
            return rows

        for structure in structures:
            installment_plan = _cycle_installments(
                float(structure.amount), structure.due_date
            ) or (structure.installment_plan or [])

            if installment_plan:
                for installment in installment_plan:
                    inst_name = installment.get("name", "")
                    inst_due = (
                        date.fromisoformat(installment["due_date"])
                        if isinstance(installment.get("due_date"), str)
                        else installment.get("due_date")
                    )
                    inst_amount = float(installment.get("amount", structure.amount))

                    existing = await self.repo.get_ledger_duplicate(
                        student_id=body.student_id,
                        fee_structure_id=structure.id,
                        installment_name=inst_name,
                    )
                    if existing:
                        skipped += 1
                        continue

                    initial_status = self._compute_ledger_status(0, inst_amount, inst_due, today)
                    await self.repo.create_ledger(
                        {
                            "student_id": body.student_id,
                            "fee_structure_id": structure.id,
                            "installment_name": inst_name,
                            "due_date": inst_due,
                            "total_amount": inst_amount,
                            "paid_amount": 0,
                            "status": initial_status,
                            "school_id": school_id,
                        }
                    )
                    created += 1
            else:
                existing = await self.repo.get_ledger_duplicate(
                    student_id=body.student_id,
                    fee_structure_id=structure.id,
                    installment_name="",
                )
                if existing:
                    skipped += 1
                    continue

                initial_status = self._compute_ledger_status(
                    0, float(structure.amount), structure.due_date, today
                )
                await self.repo.create_ledger(
                    {
                        "student_id": body.student_id,
                        "fee_structure_id": structure.id,
                        "installment_name": "",
                        "due_date": structure.due_date,
                        "total_amount": structure.amount,
                        "paid_amount": 0,
                        "status": initial_status,
                        "school_id": school_id,
                    }
                )
                created += 1

        return LedgerGenerateResponse(created=created, skipped=skipped)

    # ------------------------------------------------------------------
    # Admin Ledger List
    # ------------------------------------------------------------------

    async def list_admin_ledgers(
        self,
        current_user: CurrentUser,
        standard_id: Optional[uuid.UUID],
        academic_year_id: Optional[uuid.UUID],
        student_id: Optional[uuid.UUID],
        status: Optional[str],
        page: int,
        page_size: int,
    ) -> AdminLedgerListResponse:
        school_id = self._ensure_school(current_user)
        resolved_year_id = None
        if academic_year_id:
            resolved_year_id = academic_year_id
        elif standard_id:
            resolved_year_id = await self._resolve_academic_year(school_id, None)
        else:
            # Keep statuses fresh for default admin listings as well.
            resolved_year_id = await self._resolve_academic_year(school_id, None)

        fee_status = None
        if status:
            try:
                fee_status = FeeStatus(status.upper())
            except ValueError:
                pass

        # Refresh overdue before listing
        if resolved_year_id:
            today = datetime.now(timezone.utc).date()
            await self.repo.mark_overdue_ledgers(
                school_id=school_id,
                academic_year_id=resolved_year_id,
                as_of_date=today,
            )

        ledgers, total = await self.repo.list_all_ledgers_paginated(
            school_id=school_id,
            academic_year_id=resolved_year_id,
            standard_id=standard_id,
            student_id=student_id,
            status=fee_status,
            page=page,
            page_size=page_size,
        )

        total_billed = total_paid = 0.0
        items = []
        for ledger in ledgers:
            b = float(ledger.total_amount)
            p = float(ledger.paid_amount)
            total_billed += b
            total_paid += p

            student_name = None
            admission_number = None
            standard_name = None

            if ledger.student:
                student_name = ledger.student.student_name
                admission_number = ledger.student.admission_number

            if ledger.fee_structure and ledger.fee_structure.standard:
                standard_name = ledger.fee_structure.standard.name

            fee_category = None
            custom_fee_head = None
            if ledger.fee_structure:
                fee_category = ledger.fee_structure.fee_category
                custom_fee_head = ledger.fee_structure.custom_fee_head or None

            items.append(
                AdminLedgerEntry(
                    id=ledger.id,
                    student_id=ledger.student_id,
                    fee_structure_id=ledger.fee_structure_id,
                    student_name=student_name,
                    admission_number=admission_number,
                    standard_name=standard_name,
                    installment_name=ledger.installment_name or "",
                    fee_category=fee_category,
                    custom_fee_head=custom_fee_head,
                    due_date=ledger.due_date,
                    total_amount=b,
                    paid_amount=p,
                    outstanding_amount=max(b - p, 0.0),
                    status=ledger.status,
                    last_payment_date=ledger.last_payment_date,
                    school_id=ledger.school_id,
                    created_at=ledger.created_at,
                    updated_at=ledger.updated_at,
                )
            )

        pages = max(1, math.ceil(total / page_size)) if page_size else 1
        return AdminLedgerListResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=pages,
            total_billed=round(total_billed, 2),
            total_paid=round(total_paid, 2),
            total_outstanding=round(max(total_billed - total_paid, 0.0), 2),
        )

    # ------------------------------------------------------------------
    # Payment Recording
    # ------------------------------------------------------------------

    async def record_payment(
        self,
        body: PaymentCreate,
        current_user: CurrentUser,
    ) -> PaymentResponse:
        school_id = self._ensure_school(current_user)
        payment_date = body.payment_date or datetime.now(timezone.utc).date()

        ledger = await self.repo.get_ledger_by_id(body.fee_ledger_id, school_id)
        if not ledger:
            raise NotFoundException("Fee ledger")
        if ledger.student_id != body.student_id:
            raise ValidationException("Student does not match ledger")

        structure = ledger.fee_structure
        if not structure:
            raise NotFoundException("Fee structure")

        # ── Overpayment guard ─────────────────────────────────────────────
        current_paid = float(ledger.paid_amount)
        total = float(ledger.total_amount)
        outstanding = total - current_paid

        if body.amount > outstanding + 0.01:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Payment of ₹{body.amount:.2f} exceeds outstanding balance "
                    f"₹{outstanding:.2f}. Overpayment is not allowed."
                ),
            )

        # ── Late fee flag ─────────────────────────────────────────────────
        is_late = bool(
            ledger.due_date and payment_date > ledger.due_date
        )
        original_due_date = ledger.due_date if is_late else None

        # ── Create payment record ─────────────────────────────────────────
        payment = await self.repo.create_payment(
            {
                "student_id": body.student_id,
                "fee_ledger_id": body.fee_ledger_id,
                "amount": body.amount,
                "payment_date": payment_date,
                "payment_mode": body.payment_mode,
                "reference_number": body.reference_number,
                "transaction_ref": body.transaction_ref,
                "recorded_by": current_user.id,
                "late_fee_applied": is_late,
                "original_due_date": original_due_date,
                "school_id": school_id,
            }
        )

        # ── Update ledger ─────────────────────────────────────────────────
        new_paid = current_paid + body.amount
        new_status = self._compute_ledger_status(
            new_paid, total, ledger.due_date, payment_date
        )

        await self.repo.update_ledger(
            ledger,
            {
                "paid_amount": new_paid,
                "status": new_status,
                "last_payment_date": payment_date,
            },
        )

        await self.db.refresh(payment)
        return PaymentResponse.model_validate(payment)

    async def allocate_student_payment(
        self,
        body: PaymentAllocateCreate,
        current_user: CurrentUser,
    ) -> PaymentAllocateResponse:
        school_id = self._ensure_school(current_user)
        payment_date = body.payment_date or datetime.now(timezone.utc).date()
        resolved_year_id = await self._resolve_academic_year(
            school_id, body.academic_year_id
        )

        student_result = await self.db.execute(
            select(Student).where(
                and_(
                    Student.id == body.student_id,
                    Student.school_id == school_id,
                )
            )
        )
        student = student_result.scalar_one_or_none()
        if not student:
            raise NotFoundException("Student")

        ledgers = await self.repo.list_ledger_for_student(school_id, body.student_id)
        eligible_ledgers: list[FeeLedger] = []
        for ledger in ledgers:
            if (
                ledger.fee_structure
                and ledger.fee_structure.academic_year_id == resolved_year_id
                and (float(ledger.total_amount) - float(ledger.paid_amount)) > 0.01
            ):
                eligible_ledgers.append(ledger)

        def _priority(ledger: FeeLedger) -> int:
            if ledger.status == FeeStatus.OVERDUE:
                return 0
            if ledger.status == FeeStatus.PARTIAL:
                return 1
            if ledger.status == FeeStatus.PENDING:
                return 2
            return 3

        eligible_ledgers.sort(
            key=lambda l: (_priority(l), l.due_date or date.max, l.created_at)
        )

        requested_cycle = (body.payment_cycle or "").strip().upper()
        if requested_cycle not in {"MONTHLY", "QUARTERLY", "YEARLY"}:
            requested_cycle = "UNASSIGNED"

        remaining = float(body.amount)
        total_applied = 0.0
        allocations: list[PaymentAllocationItem] = []

        for ledger in eligible_ledgers:
            if remaining <= 0.01:
                break
            current_paid = float(ledger.paid_amount)
            total = float(ledger.total_amount)
            outstanding = max(total - current_paid, 0.0)
            if outstanding <= 0.01:
                continue

            applied = min(remaining, outstanding)
            is_late = bool(ledger.due_date and payment_date > ledger.due_date)
            payment = await self.repo.create_payment(
                {
                    "student_id": body.student_id,
                    "fee_ledger_id": ledger.id,
                    "amount": applied,
                    "payment_date": payment_date,
                    "payment_mode": body.payment_mode,
                    "reference_number": body.reference_number,
                    "transaction_ref": body.transaction_ref,
                    "recorded_by": current_user.id,
                    "late_fee_applied": is_late,
                    "original_due_date": ledger.due_date if is_late else None,
                    "school_id": school_id,
                }
            )

            new_paid = current_paid + applied
            new_status = self._compute_ledger_status(
                new_paid, total, ledger.due_date, payment_date
            )
            await self.repo.update_ledger(
                ledger,
                {
                    "paid_amount": new_paid,
                    "status": new_status,
                    "last_payment_date": payment_date,
                },
            )

            remaining -= applied
            total_applied += applied
            allocations.append(
                PaymentAllocationItem(
                    payment_id=payment.id,
                    fee_ledger_id=ledger.id,
                    installment_name=ledger.installment_name or "",
                    applied_amount=round(applied, 2),
                    remaining_outstanding=round(max(total - new_paid, 0.0), 2),
                    status=new_status,
                )
            )

        return PaymentAllocateResponse(
            student_id=body.student_id,
            payment_cycle=requested_cycle,
            total_requested=round(float(body.amount), 2),
            total_applied=round(total_applied, 2),
            total_unapplied=round(max(float(body.amount) - total_applied, 0.0), 2),
            allocations=allocations,
        )

    # ------------------------------------------------------------------
    # Overdue refresh
    # ------------------------------------------------------------------

    async def refresh_overdue_statuses(
        self,
        current_user: CurrentUser,
        academic_year_id: Optional[uuid.UUID] = None,
    ) -> dict:
        school_id = self._ensure_school(current_user)
        resolved_year_id = await self._resolve_academic_year(school_id, academic_year_id)
        today = datetime.now(timezone.utc).date()
        count = await self.repo.mark_overdue_ledgers(
            school_id=school_id,
            academic_year_id=resolved_year_id,
            as_of_date=today,
        )
        return {"updated": count, "as_of_date": today.isoformat()}

    # ------------------------------------------------------------------
    # Fee Dashboard (student ledger view)
    # ------------------------------------------------------------------

    async def fee_dashboard(
        self,
        student_id: uuid.UUID,
        current_user: CurrentUser,
        academic_year_id: Optional[uuid.UUID] = None,
    ) -> FeeDashboardResponse:
        school_id = self._ensure_school(current_user)
        await self._assert_student_access(school_id, student_id, current_user)

        ledgers = await self.repo.list_ledger_for_student(school_id, student_id)

        resolved_year = academic_year_id
        if resolved_year is None and current_user.role in (RoleEnum.STUDENT, RoleEnum.PARENT):
            resolved_year = await self._resolve_academic_year(school_id, None)
        if resolved_year:
            ledgers = [
                ldr for ldr in ledgers
                if ldr.fee_structure and ldr.fee_structure.academic_year_id == resolved_year
            ]

        today = datetime.now(timezone.utc).date()
        items = []
        total_billed = 0.0
        total_paid = 0.0
        has_overdue = False

        for ledger in ledgers:
            outstanding = float(ledger.total_amount) - float(ledger.paid_amount)

            if (
                ledger.due_date
                and today > ledger.due_date
                and ledger.status not in (FeeStatus.PAID,)
            ):
                if ledger.status != FeeStatus.OVERDUE:
                    await self.repo.update_ledger(ledger, {"status": FeeStatus.OVERDUE})
                    ledger.status = FeeStatus.OVERDUE
                has_overdue = True
            if ledger.status == FeeStatus.OVERDUE:
                has_overdue = True

            data = FeeLedgerResponse.model_validate(ledger)
            data.outstanding_amount = max(outstanding, 0.0)
            if ledger.fee_structure:
                data.fee_category = ledger.fee_structure.fee_category
                data.custom_fee_head = ledger.fee_structure.custom_fee_head or None
                data.fee_description = ledger.fee_structure.description

            total_billed += float(ledger.total_amount)
            total_paid += float(ledger.paid_amount)
            items.append(data)

        if any(ldr.status == FeeStatus.OVERDUE for ldr in ledgers):
            has_overdue = True

        return FeeDashboardResponse(
            items=items,
            total=len(items),
            total_billed=round(total_billed, 2),
            total_paid=round(total_paid, 2),
            total_outstanding=round(max(total_billed - total_paid, 0.0), 2),
            has_overdue=has_overdue,
        )

    # ------------------------------------------------------------------
    # Payment List
    # ------------------------------------------------------------------

    async def list_payments(
        self,
        fee_ledger_id: uuid.UUID,
        current_user: CurrentUser,
    ) -> PaymentListResponse:
        school_id = self._ensure_school(current_user)

        ledger = await self.repo.get_ledger_by_id(fee_ledger_id, school_id)
        if not ledger:
            raise NotFoundException("Fee ledger")

        await self._assert_student_access(school_id, ledger.student_id, current_user)

        payments = await self.repo.list_payments_for_ledger(school_id, fee_ledger_id)
        items = [PaymentResponse.model_validate(p) for p in payments]
        return PaymentListResponse(items=items, total=len(items))

    # ------------------------------------------------------------------
    # Receipt URL
    # ------------------------------------------------------------------

    async def get_receipt_url(
        self,
        payment_id: uuid.UUID,
        current_user: CurrentUser,
    ) -> str:
        school_id = self._ensure_school(current_user)
        payment = await self.repo.get_payment_by_id(payment_id, school_id)
        if not payment:
            raise NotFoundException("Payment")

        if not payment.receipt_key:
            return f"/fees/payments/{payment_id}/receipt-fallback"

        try:
            from app.core.storage import StorageService
            storage = StorageService()
            url = await storage.get_presigned_url(payment.receipt_key, expires_in=3600)
            return url
        except Exception:
            return f"/fees/payments/{payment_id}/receipt-fallback"

    async def get_receipt_fallback_data(
        self,
        payment_id: uuid.UUID,
        current_user: CurrentUser,
    ) -> dict:
        school_id = self._ensure_school(current_user)
        payment = await self.repo.get_payment_by_id(payment_id, school_id)
        if not payment:
            raise NotFoundException("Payment")
        return {
            "payment_id": str(payment.id),
            "student_id": str(payment.student_id),
            "fee_ledger_id": str(payment.fee_ledger_id),
            "amount": float(payment.amount),
            "payment_date": payment.payment_date.isoformat() if payment.payment_date else "",
            "payment_mode": payment.payment_mode.value if payment.payment_mode else "",
            "reference_number": payment.reference_number or "",
            "transaction_ref": payment.transaction_ref or "",
            "recorded_by": str(payment.recorded_by) if payment.recorded_by else "",
        }

    # ------------------------------------------------------------------
    # Defaulters
    # ------------------------------------------------------------------

    async def get_defaulters(
        self,
        current_user: CurrentUser,
        academic_year_id: Optional[uuid.UUID],
        standard_id: Optional[uuid.UUID],
        section: Optional[str],
    ) -> DefaulterListResponse:
        school_id = self._ensure_school(current_user)
        resolved_year_id = await self._resolve_academic_year(school_id, academic_year_id)
        today = datetime.now(timezone.utc).date()

        await self.repo.mark_overdue_ledgers(
            school_id=school_id,
            academic_year_id=resolved_year_id,
            as_of_date=today,
        )

        where = [
            FeeLedger.school_id == school_id,
            FeeLedger.status == FeeStatus.OVERDUE,
            FeeStructure.academic_year_id == resolved_year_id,
        ]
        if standard_id:
            where.append(Student.standard_id == standard_id)
        if section:
            where.append(Student.section == section.strip())

        result = await self.db.execute(
            select(
                Student.id,
                Student.admission_number,
                Student.standard_id,
                Student.section,
                User.full_name.label("student_name"),
                func.count(FeeLedger.id).label("overdue_count"),
                func.sum(FeeLedger.total_amount - FeeLedger.paid_amount).label("overdue_amount"),
                func.min(FeeLedger.due_date).label("oldest_due"),
            )
            .outerjoin(User, User.id == Student.user_id)
            .join(FeeLedger, FeeLedger.student_id == Student.id)
            .join(FeeStructure, FeeStructure.id == FeeLedger.fee_structure_id)
            .where(and_(*where))
            .group_by(
                Student.id,
                Student.admission_number,
                Student.standard_id,
                Student.section,
                User.full_name,
            )
            .order_by(func.min(FeeLedger.due_date).asc())
        )
        rows = result.all()

        defaulters = []
        for row in rows:
            defaulters.append(
                DefaulterEntry(
                    student_id=row.id,
                    admission_number=row.admission_number or "",
                    student_name=row.student_name,
                    standard_id=row.standard_id,
                    section=row.section,
                    overdue_ledgers=int(row.overdue_count or 0),
                    total_overdue_amount=float(row.overdue_amount or 0),
                    oldest_due_date=row.oldest_due,
                )
            )

        return DefaulterListResponse(
            academic_year_id=resolved_year_id,
            report_date=today,
            total_defaulters=len(defaulters),
            defaulters=defaulters,
        )

    # ------------------------------------------------------------------
    # Analytics
    # ------------------------------------------------------------------

    async def fee_analytics(
        self,
        current_user: CurrentUser,
        academic_year_id: Optional[uuid.UUID],
        report_date: date,
        standard_id: Optional[uuid.UUID] = None,
        section: Optional[str] = None,
        student_id: Optional[uuid.UUID] = None,
    ) -> FeeAnalyticsResponse:
        school_id = self._ensure_school(current_user)
        resolved_year_id = await self._resolve_academic_year(school_id, academic_year_id)
        section_value = section.strip() if section else None

        await self.repo.mark_overdue_ledgers(
            school_id=school_id,
            academic_year_id=resolved_year_id,
            as_of_date=report_date,
        )
        await self.db.flush()

        ledger_where = [
            FeeLedger.school_id == school_id,
            Student.school_id == school_id,
            FeeStructure.academic_year_id == resolved_year_id,
        ]
        if standard_id is not None:
            ledger_where.append(Student.standard_id == standard_id)
        if section_value:
            ledger_where.append(Student.section == section_value)
        if student_id is not None:
            ledger_where.append(FeeLedger.student_id == student_id)

        summary_stmt = (
            select(
                func.coalesce(func.sum(FeeLedger.total_amount), 0).label("billed"),
                func.coalesce(func.sum(FeeLedger.paid_amount), 0).label("paid"),
                func.coalesce(func.count(FeeLedger.id), 0).label("ledgers"),
                func.coalesce(func.count(distinct(FeeLedger.student_id)), 0).label("students"),
                func.coalesce(
                    func.sum(case((FeeLedger.status == FeeStatus.PAID, 1), else_=0)), 0
                ).label("paid_ledgers"),
                func.coalesce(
                    func.sum(case((FeeLedger.status == FeeStatus.PARTIAL, 1), else_=0)), 0
                ).label("partial_ledgers"),
                func.coalesce(
                    func.sum(case((FeeLedger.status == FeeStatus.PENDING, 1), else_=0)), 0
                ).label("pending_ledgers"),
                func.coalesce(
                    func.sum(case((FeeLedger.status == FeeStatus.OVERDUE, 1), else_=0)), 0
                ).label("overdue_ledgers"),
            )
            .select_from(FeeLedger)
            .join(FeeStructure, FeeStructure.id == FeeLedger.fee_structure_id)
            .join(Student, Student.id == FeeLedger.student_id)
            .where(*ledger_where)
        )
        summary_row = (await self.db.execute(summary_stmt)).one()
        total_billed = float(summary_row.billed or 0)
        total_paid_amt = float(summary_row.paid or 0)
        total_outstanding = max(total_billed - total_paid_amt, 0.0)
        collection_pct = (
            round((total_paid_amt / total_billed) * 100, 2) if total_billed > 0 else 0.0
        )

        defaulters_subq = (
            select(distinct(FeeLedger.student_id))
            .join(FeeStructure, FeeStructure.id == FeeLedger.fee_structure_id)
            .join(Student, Student.id == FeeLedger.student_id)
            .where(
                *[w for w in ledger_where],
                FeeLedger.status == FeeStatus.OVERDUE,
            )
            .subquery()
        )
        defaulters_count_result = await self.db.execute(
            select(func.count()).select_from(defaulters_subq)
        )
        defaulters_count = int(defaulters_count_result.scalar_one() or 0)

        payment_where = [
            Payment.school_id == school_id,
            Student.school_id == school_id,
            FeeStructure.academic_year_id == resolved_year_id,
        ]
        if standard_id is not None:
            payment_where.append(Student.standard_id == standard_id)
        if section_value:
            payment_where.append(Student.section == section_value)
        if student_id is not None:
            payment_where.append(Payment.student_id == student_id)

        payments_stmt = (
            select(
                func.coalesce(func.count(Payment.id), 0).label("transactions"),
                func.coalesce(
                    func.sum(case((Payment.late_fee_applied.is_(True), 1), else_=0)), 0
                ).label("late_transactions"),
            )
            .select_from(Payment)
            .join(FeeLedger, FeeLedger.id == Payment.fee_ledger_id)
            .join(FeeStructure, FeeStructure.id == FeeLedger.fee_structure_id)
            .join(Student, Student.id == Payment.student_id)
            .where(*payment_where)
        )
        payments_row = (await self.db.execute(payments_stmt)).one()

        summary = FeeAnalyticsSummary(
            total_billed_amount=round(total_billed, 2),
            total_paid_amount=round(total_paid_amt, 2),
            total_outstanding_amount=round(total_outstanding, 2),
            collection_percentage=collection_pct,
            total_ledgers=int(summary_row.ledgers or 0),
            total_students=int(summary_row.students or 0),
            paid_ledgers=int(summary_row.paid_ledgers or 0),
            partial_ledgers=int(summary_row.partial_ledgers or 0),
            pending_ledgers=int(summary_row.pending_ledgers or 0),
            overdue_ledgers=int(summary_row.overdue_ledgers or 0),
            defaulters_count=defaulters_count,
            payments_count=int(payments_row.transactions or 0),
            late_payments_count=int(payments_row.late_transactions or 0),
        )

        # ── By category ────────────────────────────────────────────────────
        by_cat_result = await self.db.execute(
            select(
                FeeStructure.fee_category,
                func.coalesce(func.sum(FeeLedger.total_amount), 0).label("billed"),
                func.coalesce(func.sum(FeeLedger.paid_amount), 0).label("paid"),
                func.coalesce(func.count(FeeLedger.id), 0).label("ledgers"),
            )
            .select_from(FeeLedger)
            .join(FeeStructure, FeeStructure.id == FeeLedger.fee_structure_id)
            .join(Student, Student.id == FeeLedger.student_id)
            .where(*ledger_where)
            .group_by(FeeStructure.fee_category)
        )
        by_category = [
            FeeCategoryAnalyticsItem(
                fee_category=r.fee_category,
                billed_amount=float(r.billed),
                paid_amount=float(r.paid),
                outstanding_amount=max(float(r.billed) - float(r.paid), 0),
                ledgers=int(r.ledgers),
            )
            for r in by_cat_result.all()
        ]

        # ── By status ───────────────────────────────────────────────────────
        by_status_result = await self.db.execute(
            select(
                FeeLedger.status,
                func.coalesce(func.count(FeeLedger.id), 0).label("ledgers"),
                func.coalesce(func.sum(FeeLedger.total_amount), 0).label("billed"),
                func.coalesce(func.sum(FeeLedger.paid_amount), 0).label("paid"),
            )
            .select_from(FeeLedger)
            .join(FeeStructure, FeeStructure.id == FeeLedger.fee_structure_id)
            .join(Student, Student.id == FeeLedger.student_id)
            .where(*ledger_where)
            .group_by(FeeLedger.status)
        )
        by_status = [
            FeeStatusAnalyticsItem(
                status=r.status,
                ledgers=int(r.ledgers),
                billed_amount=float(r.billed),
                paid_amount=float(r.paid),
                outstanding_amount=max(float(r.billed) - float(r.paid), 0),
            )
            for r in by_status_result.all()
        ]

        # ── By payment mode ─────────────────────────────────────────────────
        by_mode_result = await self.db.execute(
            select(
                Payment.payment_mode,
                func.coalesce(func.sum(Payment.amount), 0).label("amount"),
                func.coalesce(func.count(Payment.id), 0).label("transactions"),
            )
            .select_from(Payment)
            .join(FeeLedger, FeeLedger.id == Payment.fee_ledger_id)
            .join(FeeStructure, FeeStructure.id == FeeLedger.fee_structure_id)
            .join(Student, Student.id == Payment.student_id)
            .where(*payment_where)
            .group_by(Payment.payment_mode)
        )
        by_payment_mode = [
            PaymentModeAnalyticsItem(
                payment_mode=r.payment_mode,
                amount=float(r.amount),
                transactions=int(r.transactions),
            )
            for r in by_mode_result.all()
        ]

        # ── By class ────────────────────────────────────────────────────────
        from app.models.masters import Standard
        by_class_result = await self.db.execute(
            select(
                FeeStructure.standard_id,
                Standard.name.label("standard_name"),
                Student.section,
                func.coalesce(func.count(distinct(FeeLedger.student_id)), 0).label("students"),
                func.coalesce(func.sum(FeeLedger.total_amount), 0).label("billed"),
                func.coalesce(func.sum(FeeLedger.paid_amount), 0).label("paid"),
                func.coalesce(
                    func.sum(case((FeeLedger.status == FeeStatus.OVERDUE, 1), else_=0)), 0
                ).label("defaulters"),
            )
            .select_from(FeeLedger)
            .join(FeeStructure, FeeStructure.id == FeeLedger.fee_structure_id)
            .join(Student, Student.id == FeeLedger.student_id)
            .join(Standard, Standard.id == FeeStructure.standard_id)
            .where(*ledger_where)
            .group_by(FeeStructure.standard_id, Standard.name, Student.section)
            .order_by(Standard.name.asc())
        )
        by_class = [
            FeeClassAnalyticsItem(
                standard_id=r.standard_id,
                standard_name=r.standard_name or "",
                section=r.section,
                total_students=int(r.students),
                total_billed=float(r.billed),
                total_paid=float(r.paid),
                total_outstanding=max(float(r.billed) - float(r.paid), 0),
                collection_percentage=round(
                    (float(r.paid) / float(r.billed) * 100) if float(r.billed) > 0 else 0, 2
                ),
                defaulters_count=int(r.defaulters),
            )
            for r in by_class_result.all()
        ]

        # ── By installment ──────────────────────────────────────────────────
        by_inst_result = await self.db.execute(
            select(
                FeeLedger.installment_name,
                func.coalesce(func.count(FeeLedger.id), 0).label("ledgers"),
                func.coalesce(
                    func.sum(case((FeeLedger.status == FeeStatus.PAID, 1), else_=0)), 0
                ).label("paid_l"),
                func.coalesce(
                    func.sum(case((FeeLedger.status == FeeStatus.PARTIAL, 1), else_=0)), 0
                ).label("partial_l"),
                func.coalesce(
                    func.sum(case((FeeLedger.status == FeeStatus.PENDING, 1), else_=0)), 0
                ).label("pending_l"),
                func.coalesce(
                    func.sum(case((FeeLedger.status == FeeStatus.OVERDUE, 1), else_=0)), 0
                ).label("overdue_l"),
                func.coalesce(func.sum(FeeLedger.total_amount), 0).label("billed"),
                func.coalesce(func.sum(FeeLedger.paid_amount), 0).label("paid"),
            )
            .select_from(FeeLedger)
            .join(FeeStructure, FeeStructure.id == FeeLedger.fee_structure_id)
            .join(Student, Student.id == FeeLedger.student_id)
            .where(*ledger_where)
            .group_by(FeeLedger.installment_name)
        )
        by_installment = [
            FeeInstallmentAnalyticsItem(
                installment_name=r.installment_name or "",
                total_ledgers=int(r.ledgers),
                paid_ledgers=int(r.paid_l),
                partial_ledgers=int(r.partial_l),
                pending_ledgers=int(r.pending_l),
                overdue_ledgers=int(r.overdue_l),
                total_billed=float(r.billed),
                total_paid=float(r.paid),
                total_outstanding=max(float(r.billed) - float(r.paid), 0),
                collection_percentage=round(
                    (float(r.paid) / float(r.billed) * 100) if float(r.billed) > 0 else 0, 2
                ),
            )
            for r in by_inst_result.all()
        ]

        # ── By student ──────────────────────────────────────────────────────
        latest_payment_subq = (
            select(
                Payment.student_id.label("student_id"),
                func.max(Payment.payment_date).label("latest_payment_date"),
            )
            .select_from(Payment)
            .join(FeeLedger, FeeLedger.id == Payment.fee_ledger_id)
            .join(FeeStructure, FeeStructure.id == FeeLedger.fee_structure_id)
            .join(Student, Student.id == Payment.student_id)
            .where(*payment_where)
            .group_by(Payment.student_id)
            .subquery()
        )

        by_student_result = await self.db.execute(
            select(
                Student.id.label("student_id"),
                Student.admission_number,
                Student.standard_id,
                Student.section,
                func.coalesce(func.sum(FeeLedger.total_amount), 0).label("billed"),
                func.coalesce(func.sum(FeeLedger.paid_amount), 0).label("paid"),
                func.coalesce(func.count(FeeLedger.id), 0).label("ledgers"),
                func.coalesce(
                    func.sum(case((FeeLedger.status == FeeStatus.PAID, 1), else_=0)), 0
                ).label("paid_ledgers"),
                func.coalesce(
                    func.sum(case((FeeLedger.status == FeeStatus.PARTIAL, 1), else_=0)), 0
                ).label("partial_ledgers"),
                func.coalesce(
                    func.sum(case((FeeLedger.status == FeeStatus.PENDING, 1), else_=0)), 0
                ).label("pending_ledgers"),
                func.coalesce(
                    func.sum(case((FeeLedger.status == FeeStatus.OVERDUE, 1), else_=0)), 0
                ).label("overdue_ledgers"),
                latest_payment_subq.c.latest_payment_date,
            )
            .select_from(FeeLedger)
            .join(FeeStructure, FeeStructure.id == FeeLedger.fee_structure_id)
            .join(Student, Student.id == FeeLedger.student_id)
            .outerjoin(
                latest_payment_subq, latest_payment_subq.c.student_id == Student.id
            )
            .where(*ledger_where)
            .group_by(
                Student.id,
                Student.admission_number,
                Student.standard_id,
                Student.section,
                latest_payment_subq.c.latest_payment_date,
            )
            .order_by(Student.admission_number.asc())
        )
        by_student = []
        for r in by_student_result.all():
            billed = float(r.billed or 0)
            paid = float(r.paid or 0)
            outstanding = max(billed - paid, 0.0)
            overdue_ledgers = int(r.overdue_ledgers or 0)
            by_student.append(
                FeeStudentAnalyticsItem(
                    student_id=r.student_id,
                    admission_number=r.admission_number or "",
                    standard_id=r.standard_id,
                    section=r.section,
                    billed_amount=billed,
                    paid_amount=paid,
                    outstanding_amount=outstanding,
                    ledgers=int(r.ledgers or 0),
                    paid_ledgers=int(r.paid_ledgers or 0),
                    partial_ledgers=int(r.partial_ledgers or 0),
                    pending_ledgers=int(r.pending_ledgers or 0),
                    overdue_ledgers=overdue_ledgers,
                    is_defaulter=overdue_ledgers > 0,
                    latest_payment_date=r.latest_payment_date,
                )
            )

        return FeeAnalyticsResponse(
            academic_year_id=resolved_year_id,
            report_date=report_date,
            filters={
                "standard_id": str(standard_id) if standard_id else None,
                "section": section_value,
                "student_id": str(student_id) if student_id else None,
            },
            summary=summary,
            by_category=by_category,
            by_status=by_status,
            by_payment_mode=by_payment_mode,
            by_student=by_student,
            by_class=by_class,
            by_installment=by_installment,
        )

    # ------------------------------------------------------------------
    # Class-wise student fee summary (admin console)
    # Returns one row per student with parent info + installment breakdown
    # ------------------------------------------------------------------

    async def list_class_fee_students(
        self,
        current_user: CurrentUser,
        standard_id: uuid.UUID,
        academic_year_id: Optional[uuid.UUID],
        section: Optional[str] = None,
        payment_cycle: Optional[str] = None,
        status_filter: Optional[str] = None,
    ) -> ClassFeeStudentListResponse:
        school_id = self._ensure_school(current_user)
        resolved_year_id = await self._resolve_academic_year(school_id, academic_year_id)
        today = datetime.now(timezone.utc).date()

        # Refresh overdue statuses first
        await self.repo.mark_overdue_ledgers(
            school_id=school_id,
            academic_year_id=resolved_year_id,
            as_of_date=today,
        )

        ledgers, _ = await self.repo.list_all_ledgers_paginated(
            school_id=school_id,
            academic_year_id=resolved_year_id,
            standard_id=standard_id,
            status=None,
            page=1,
            page_size=2000,
        )
        from app.models.parent import Parent

        student_result = await self.db.execute(
            # Parent/user details are required for class-wise fee verification rows.
            # Imported locally to avoid circular import side effects at module load.
            select(Student)
            .options(
                selectinload(Student.user),
                selectinload(Student.parent).selectinload(Parent.user),
                selectinload(Student.standard),
            )
            .where(
                and_(
                    Student.school_id == school_id,
                    Student.standard_id == standard_id,
                    *([Student.section == section.strip()] if section and section.strip() else []),
                    (Student.academic_year_id == resolved_year_id)
                    | (Student.academic_year_id.is_(None)),
                )
            )
            .order_by(Student.admission_number.asc())
        )
        students = list(student_result.scalars().all())

        from collections import defaultdict
        student_ledgers: dict[str, list] = defaultdict(list)
        for ledger in ledgers:
            student_ledgers[str(ledger.student_id)].append(ledger)

        def _resolve_cycle(installments: list[StudentInstallmentSummary]) -> str:
            if not installments:
                return "UNASSIGNED"
            names = [i.installment_name.lower() for i in installments if i.installment_name]
            if any("month" in n for n in names):
                return "MONTHLY"
            if any("quarter" in n for n in names):
                return "QUARTERLY"
            if any("year" in n for n in names):
                return "YEARLY"
            if len(installments) >= 10:
                return "MONTHLY"
            if len(installments) == 4:
                return "QUARTERLY"
            if len(installments) <= 2:
                return "YEARLY"
            return "CUSTOM"

        def _resolve_status(has_overdue: bool, total_paid: float, total_outstanding: float) -> str:
            if has_overdue:
                return FeeStatus.OVERDUE.value
            if total_outstanding <= 0.01 and (total_paid > 0):
                return FeeStatus.PAID.value
            if total_paid > 0 and total_outstanding > 0.01:
                return FeeStatus.PARTIAL.value
            return FeeStatus.PENDING.value

        items: list[StudentFeeRow] = []
        grand_billed = grand_paid = grand_outstanding = 0.0

        for student in students:
            student_id_str = str(student.id)
            student_ledger_list = student_ledgers.get(student_id_str, [])
            installments: list[StudentInstallmentSummary] = []
            total_billed = total_paid = 0.0
            has_overdue = False

            for ledger in sorted(
                student_ledger_list,
                key=lambda l: (l.due_date or date.max, l.created_at),
            ):
                b = float(ledger.total_amount)
                p = float(ledger.paid_amount)
                outstanding = max(b - p, 0.0)
                total_billed += b
                total_paid += p

                if ledger.status == FeeStatus.OVERDUE:
                    has_overdue = True

                fee_head = ""
                if ledger.fee_structure:
                    cfh = (ledger.fee_structure.custom_fee_head or "").strip()
                    fee_head = cfh if cfh else str(ledger.fee_structure.fee_category.value)

                installments.append(
                    StudentInstallmentSummary(
                        ledger_id=str(ledger.id),
                        fee_head=fee_head,
                        installment_name=ledger.installment_name or "",
                        due_date=ledger.due_date,
                        total_amount=b,
                        paid_amount=p,
                        outstanding_amount=outstanding,
                        status=ledger.status.value,
                        last_payment_date=ledger.last_payment_date,
                    )
                )

            total_outstanding = max(total_billed - total_paid, 0.0)
            student_status = _resolve_status(has_overdue, total_paid, total_outstanding)
            if status_filter and student_status != status_filter.upper():
                continue

            cycle = _resolve_cycle(installments)
            if payment_cycle and cycle != payment_cycle.strip().upper():
                continue
            grand_billed += total_billed
            grand_paid += total_paid
            grand_outstanding += total_outstanding

            items.append(
                StudentFeeRow(
                    student_id=student_id_str,
                    student_name=student.student_name,
                    admission_number=student.admission_number,
                    standard_name=student.standard.name if student.standard else None,
                    section=student.section,
                    parent_name=student.parent.user.full_name
                    if student.parent and student.parent.user
                    else None,
                    parent_phone=student.parent.user.phone
                    if student.parent and student.parent.user
                    else None,
                    parent_email=student.parent.user.email
                    if student.parent and student.parent.user
                    else None,
                    student_phone=student.user.phone if student.user else None,
                    payment_cycle=cycle,
                    status=student_status,
                    total_billed=round(total_billed, 2),
                    total_paid=round(total_paid, 2),
                    total_outstanding=round(total_outstanding, 2),
                    has_overdue=has_overdue,
                    installments=installments,
                )
            )

        items.sort(key=lambda r: r.admission_number or "")

        return ClassFeeStudentListResponse(
            items=items,
            total=len(items),
            total_billed=round(grand_billed, 2),
            total_paid=round(grand_paid, 2),
            total_outstanding=round(grand_outstanding, 2),
        )
