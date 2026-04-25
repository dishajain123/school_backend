import uuid
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select, and_, case, distinct, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import (
    ForbiddenException,
    ValidationException,
    NotFoundException,
)
from app.models.fee import FeeLedger, FeeStructure
from app.models.masters import Standard
from app.models.payment import Payment
from app.models.student import Student
from app.repositories.fee import FeeRepository
from app.schemas.fee import (
    FeeStructureResponse,
    FeeStructureListResponse,
    FeeStructureBatchCreate,
    FeeStructureBatchResponse,
    FeeStructureUpdate,
    FeeStructureUpdateResponse,
    LedgerGenerateRequest,
    LedgerGenerateResponse,
    PaymentCreate,
    PaymentResponse,
    FeeLedgerResponse,
    FeeDashboardResponse,
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
)
from app.services.academic_year import get_active_year
from app.integrations.minio_client import minio_client
from app.integrations import pdf_service
from app.utils.enums import RoleEnum, FeeStatus, FeeCategory

RECEIPTS_BUCKET = "receipts"


class FeeService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = FeeRepository(db)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_school(self, current_user: CurrentUser) -> uuid.UUID:
        if not current_user.school_id:
            raise ValidationException("school_id is required")
        return current_user.school_id

    async def _resolve_academic_year(
        self, school_id: uuid.UUID, academic_year_id: Optional[uuid.UUID]
    ) -> uuid.UUID:
        if academic_year_id:
            return academic_year_id
        return (await get_active_year(school_id, self.db)).id

    async def _assert_student_access(
        self,
        school_id: uuid.UUID,
        student_id: uuid.UUID,
        current_user: CurrentUser,
    ) -> None:
        """Raise ForbiddenException if current_user cannot access this student's data."""
        if current_user.role in (RoleEnum.PRINCIPAL, RoleEnum.TRUSTEE, RoleEnum.SUPERADMIN):
            return
        if current_user.role == RoleEnum.TEACHER:
            return
        if current_user.role == RoleEnum.STUDENT:
            result = await self.db.execute(
                select(Student.user_id).where(
                    and_(Student.id == student_id, Student.school_id == school_id)
                )
            )
            row = result.first()
            if row and row[0] == current_user.id:
                return
            raise ForbiddenException(detail="You can only view your own fee data")
        if current_user.role == RoleEnum.PARENT:
            if not current_user.parent_id:
                raise ForbiddenException(detail="Parent profile not found")
            result = await self.db.execute(
                select(Student.id).where(
                    and_(
                        Student.id == student_id,
                        Student.school_id == school_id,
                        Student.parent_id == current_user.parent_id,
                    )
                )
            )
            if result.first():
                return
            raise ForbiddenException(detail="You can only view your child's fee data")
        raise ForbiddenException(detail="Access denied")

    @staticmethod
    def _normalize_custom_fee_head(value: Optional[str]) -> str:
        if not value:
            return ""
        return " ".join(value.strip().split())

    def _compute_ledger_status(
        self,
        paid_amount: float,
        total_amount: float,
        due_date: Optional[date],
        payment_date: Optional[date] = None,
    ) -> FeeStatus:
        """
        Compute the correct status for a ledger entry.
        Rules:
          - paid_amount >= total_amount             → PAID
          - paid_amount > 0                         → PARTIAL
          - today > due_date AND status != PAID     → OVERDUE
          - else                                    → PENDING
        """
        today = payment_date or datetime.now(timezone.utc).date()
        if total_amount > 0 and paid_amount >= total_amount - 0.01:
            return FeeStatus.PAID
        if paid_amount > 0:
            # Still check if overdue
            if due_date and today > due_date:
                return FeeStatus.OVERDUE
            return FeeStatus.PARTIAL
        # Unpaid
        if due_date and today > due_date:
            return FeeStatus.OVERDUE
        return FeeStatus.PENDING

    async def _sync_ledgers_for_structure(
        self, school_id: uuid.UUID, structure: FeeStructure
    ) -> None:
        """After updating a structure, sync existing ledger total_amounts."""
        ledgers = await self.repo.list_ledgers_for_structure(school_id, structure.id)
        for ledger in ledgers:
            new_total = float(structure.amount)
            paid = float(ledger.paid_amount)
            new_status = self._compute_ledger_status(paid, new_total, ledger.due_date)
            await self.repo.update_ledger(
                ledger,
                {"total_amount": new_total, "status": new_status},
            )

    async def _upsert_structure(
        self,
        school_id: uuid.UUID,
        standard_id: uuid.UUID,
        academic_year_id: uuid.UUID,
        fee_category,
        custom_fee_head: str,
        amount: float,
        due_date: date,
        description: Optional[str],
        installment_plan: Optional[list] = None,
    ) -> tuple[FeeStructure, bool]:
        existing = await self.repo.get_structure_duplicate(
            school_id=school_id,
            standard_id=standard_id,
            academic_year_id=academic_year_id,
            fee_category=fee_category,
            custom_fee_head=custom_fee_head,
        )
        if existing:
            update_data = {
                "amount": amount,
                "due_date": due_date,
                "description": description,
            }
            if installment_plan is not None:
                update_data["installment_plan"] = installment_plan
            structure = await self.repo.update_structure(existing, update_data)
            await self._sync_ledgers_for_structure(school_id=school_id, structure=structure)
            return structure, False

        create_data = {
            "standard_id": standard_id,
            "academic_year_id": academic_year_id,
            "fee_category": fee_category,
            "custom_fee_head": custom_fee_head,
            "amount": amount,
            "due_date": due_date,
            "description": description,
            "school_id": school_id,
        }
        if installment_plan is not None:
            create_data["installment_plan"] = [
                {
                    "name": item.name,
                    "due_date": item.due_date.isoformat(),
                    "amount": item.amount,
                }
                for item in installment_plan
            ]
        structure = await self.repo.create_structure(create_data)
        return structure, True

    # ------------------------------------------------------------------
    # Fee Structure Batch Create
    # ------------------------------------------------------------------

    async def create_structures_batch(
        self,
        body: FeeStructureBatchCreate,
        current_user: CurrentUser,
    ) -> FeeStructureBatchResponse:
        school_id = self._ensure_school(current_user)
        academic_year_id = await self._resolve_academic_year(
            school_id, body.academic_year_id
        )

        if body.apply_to_all_classes:
            standards_result = await self.db.execute(
                select(Standard.id).where(
                    and_(
                        Standard.school_id == school_id,
                        Standard.academic_year_id == academic_year_id,
                    )
                )
            )
            target_standard_ids = [row[0] for row in standards_result.all()]
        elif body.standard_ids:
            target_standard_ids = body.standard_ids
        elif body.standard_id:
            target_standard_ids = [body.standard_id]
        else:
            raise ValidationException(
                "standard_id or standard_ids is required (or set apply_to_all_classes=true)"
            )

        if not target_standard_ids:
            raise ValidationException("No classes found to create fee structure")

        created = 0
        updated = 0
        structures: list[FeeStructure] = []
        seen_structure_ids: set[uuid.UUID] = set()

        installment_plan = body.installment_plan
        for standard_id in target_standard_ids:
            for fee_head in body.fee_heads:
                custom_fee_head = self._normalize_custom_fee_head(fee_head.name)
                structure, is_created = await self._upsert_structure(
                    school_id=school_id,
                    standard_id=standard_id,
                    academic_year_id=academic_year_id,
                    fee_category=FeeCategory.MISCELLANEOUS,
                    custom_fee_head=custom_fee_head,
                    amount=fee_head.amount,
                    due_date=body.due_date,
                    description=body.description,
                    installment_plan=installment_plan,
                )
                if structure.id not in seen_structure_ids:
                    structures.append(structure)
                    seen_structure_ids.add(structure.id)
                if is_created:
                    created += 1
                else:
                    updated += 1

        await self.db.commit()
        for structure in structures:
            await self.db.refresh(structure)

        return FeeStructureBatchResponse(
            items=[FeeStructureResponse.model_validate(item) for item in structures],
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
            updated = await self.repo.update_structure(structure, update_data)
            await self._sync_ledgers_for_structure(school_id=school_id, structure=updated)
            updated_structures.append(updated)

        await self.db.commit()
        for s in updated_structures:
            await self.db.refresh(s)

        return FeeStructureUpdateResponse(
            items=[FeeStructureResponse.model_validate(s) for s in updated_structures],
            total=len(updated_structures),
        )

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
        items = [FeeStructureResponse.model_validate(s) for s in structures]
        return FeeStructureListResponse(items=items, total=len(items))

    # ------------------------------------------------------------------
    # Ledger Generation (IDEMPOTENT)
    # ------------------------------------------------------------------

    async def generate_ledger(
        self,
        body: LedgerGenerateRequest,
        current_user: CurrentUser,
    ) -> LedgerGenerateResponse:
        school_id = self._ensure_school(current_user)
        academic_year_id = await self._resolve_academic_year(
            school_id, body.academic_year_id
        )
        created_structures = 0
        updated_structures = 0

        # Handle custom fee heads from the request
        for custom_head in body.custom_fee_heads:
            custom_name = self._normalize_custom_fee_head(custom_head.name)
            installment_plan = custom_head.installment_plan
            _, is_created = await self._upsert_structure(
                school_id=school_id,
                standard_id=body.standard_id,
                academic_year_id=academic_year_id,
                fee_category=FeeCategory.MISCELLANEOUS,
                custom_fee_head=custom_name,
                amount=custom_head.amount,
                due_date=custom_head.due_date or date.today(),
                description=custom_head.description,
                installment_plan=installment_plan,
            )
            if is_created:
                created_structures += 1
            else:
                updated_structures += 1

        # Get all students for this class/year
        students_result = await self.db.execute(
            select(Student.id).where(
                and_(
                    Student.school_id == school_id,
                    Student.standard_id == body.standard_id,
                    Student.academic_year_id == academic_year_id,
                )
            )
        )
        student_ids = [row[0] for row in students_result.all()]

        # Get all structures for this class/year
        structures = await self.repo.list_structures_for_standard(
            school_id=school_id,
            standard_id=body.standard_id,
            academic_year_id=academic_year_id,
        )
        if not structures:
            raise NotFoundException("Fee structure")

        today = datetime.now(timezone.utc).date()
        created = 0
        skipped = 0

        for student_id in student_ids:
            for structure in structures:
                installment_plan = structure.installment_plan

                if installment_plan and isinstance(installment_plan, list) and len(installment_plan) > 0:
                    # Generate ONE row per installment
                    for installment in installment_plan:
                        inst_name = installment.get("name", "")
                        inst_due_date_raw = installment.get("due_date")
                        inst_amount = float(installment.get("amount", structure.amount))

                        try:
                            inst_due = (
                                date.fromisoformat(inst_due_date_raw)
                                if inst_due_date_raw
                                else structure.due_date
                            )
                        except (ValueError, TypeError):
                            inst_due = structure.due_date

                        existing = await self.repo.get_ledger_existing(
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
                    # Single row per structure (no installment plan)
                    existing = await self.repo.get_ledger_existing(
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

        await self.db.commit()
        return LedgerGenerateResponse(
            created=created,
            skipped=skipped,
            created_structures=created_structures,
            updated_structures=updated_structures,
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
        if body.amount <= 0:
            raise ValidationException("Payment amount must be positive")

        new_paid = current_paid + body.amount

        # ── Determine new status ──────────────────────────────────────────
        new_status = self._compute_ledger_status(
            new_paid, total, ledger.due_date, payment_date
        )

        # ── Late fee flag ─────────────────────────────────────────────────
        effective_due = ledger.due_date or structure.due_date
        late_fee_applied = bool(effective_due and payment_date > effective_due)

        # ── Receipt generation ────────────────────────────────────────────
        fee_head = (
            ledger.installment_name
            or structure.custom_fee_head
            or structure.fee_category.value
        )
        receipt_html = _build_receipt_html(
            student_id=body.student_id,
            fee_head=fee_head,
            installment_name=ledger.installment_name,
            amount=body.amount,
            payment_date=payment_date,
            payment_mode=body.payment_mode,
            reference_number=body.reference_number or body.transaction_ref,
            total_amount=total,
            paid_so_far=new_paid,
            due_date=effective_due,
            late_fee_applied=late_fee_applied,
        )
        pdf_bytes = pdf_service.generate_pdf(receipt_html)
        receipt_key = f"{school_id}/{body.student_id}/{uuid.uuid4()}_fee_receipt.pdf"
        minio_client.upload_file(
            bucket=RECEIPTS_BUCKET,
            key=receipt_key,
            file_bytes=pdf_bytes,
            content_type="application/pdf",
        )

        # ── Persist payment ───────────────────────────────────────────────
        payment = await self.repo.create_payment(
            {
                "student_id": body.student_id,
                "fee_ledger_id": body.fee_ledger_id,
                "amount": body.amount,
                "payment_date": payment_date,
                "payment_mode": body.payment_mode,
                "reference_number": body.reference_number,
                "transaction_ref": body.transaction_ref,
                "receipt_key": receipt_key,
                "recorded_by": current_user.id,
                "late_fee_applied": late_fee_applied,
                "original_due_date": effective_due,
                "school_id": school_id,
            }
        )

        # ── Update ledger ─────────────────────────────────────────────────
        await self.repo.update_ledger(
            ledger,
            {
                "paid_amount": new_paid,
                "status": new_status,
                "last_payment_date": payment_date,
            },
        )

        await self.db.commit()
        await self.db.refresh(payment)
        return PaymentResponse.model_validate(payment)

    # ------------------------------------------------------------------
    # Overdue refresh (can be called from a scheduled job or endpoint)
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
        await self.db.commit()
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

        # Optional: filter by academic year
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

            # Lazily refresh overdue status
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
            # Per-installment due_date is stored on ledger directly
            # (populated during generate_ledger)

            total_billed += float(ledger.total_amount)
            total_paid += float(ledger.paid_amount)
            items.append(data)

        if any(ldr.status == FeeStatus.OVERDUE for ldr in ledgers):
            has_overdue = True

        # Commit any lazy overdue updates
        await self.db.commit()

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

        await self._assert_student_access(school_id, payment.student_id, current_user)

        if not payment.receipt_key:
            raise NotFoundException("Receipt")

        return minio_client.generate_presigned_url(RECEIPTS_BUCKET, payment.receipt_key)

    # ------------------------------------------------------------------
    # Defaulters
    # ------------------------------------------------------------------

    async def get_defaulters(
        self,
        current_user: CurrentUser,
        academic_year_id: Optional[uuid.UUID] = None,
        standard_id: Optional[uuid.UUID] = None,
        section: Optional[str] = None,
    ) -> DefaulterListResponse:
        school_id = self._ensure_school(current_user)
        resolved_year_id = await self._resolve_academic_year(school_id, academic_year_id)
        today = datetime.now(timezone.utc).date()

        # First refresh overdue statuses for accuracy
        await self.repo.mark_overdue_ledgers(
            school_id=school_id,
            academic_year_id=resolved_year_id,
            as_of_date=today,
        )
        await self.db.flush()

        rows = await self.repo.get_defaulters(
            school_id=school_id,
            academic_year_id=resolved_year_id,
            standard_id=standard_id,
            section=section.strip() if section else None,
        )

        defaulters = [
            DefaulterEntry(
                student_id=row["student_id"],
                admission_number=row["admission_number"],
                student_name=row.get("student_name") or None,
                standard_id=row.get("standard_id"),
                section=row.get("section"),
                overdue_ledgers=int(row["overdue_ledgers"] or 0),
                total_overdue_amount=round(float(row["total_overdue_amount"] or 0), 2),
                oldest_due_date=row.get("oldest_due_date"),
            )
            for row in rows
        ]

        await self.db.commit()
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

        # Refresh overdue statuses first for accurate analytics
        await self.repo.mark_overdue_ledgers(
            school_id=school_id,
            academic_year_id=resolved_year_id,
            as_of_date=report_date,
        )
        await self.db.flush()

        # Base WHERE clauses shared across ledger queries
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

        # ── Summary ────────────────────────────────────────────────────────
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

        # Defaulters count (students with at least one OVERDUE ledger)
        defaulters_subq = (
            select(distinct(FeeLedger.student_id))
            .join(FeeStructure, FeeStructure.id == FeeLedger.fee_structure_id)
            .join(Student, Student.id == FeeLedger.student_id)
            .where(
                *[
                    w for w in ledger_where
                    if not (hasattr(w, "left") and str(w.left) == str(FeeLedger.student_id))
                ],
                FeeLedger.status == FeeStatus.OVERDUE,
            )
            .subquery()
        )
        defaulters_count_result = await self.db.execute(
            select(func.count()).select_from(defaulters_subq)
        )
        defaulters_count = int(defaulters_count_result.scalar_one() or 0)

        # Payment-level WHERE clauses
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

        # ── By category ────────────────────────────────────────────────────
        by_category_stmt = (
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
            .order_by(FeeStructure.fee_category.asc())
        )
        by_category_rows = (await self.db.execute(by_category_stmt)).all()
        by_category = [
            FeeCategoryAnalyticsItem(
                fee_category=row.fee_category,
                billed_amount=round(float(row.billed or 0), 2),
                paid_amount=round(float(row.paid or 0), 2),
                outstanding_amount=round(
                    max(float(row.billed or 0) - float(row.paid or 0), 0.0), 2
                ),
                ledgers=int(row.ledgers or 0),
            )
            for row in by_category_rows
        ]

        # ── By status ──────────────────────────────────────────────────────
        by_status_stmt = (
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
            .order_by(FeeLedger.status.asc())
        )
        by_status_rows = (await self.db.execute(by_status_stmt)).all()
        by_status = [
            FeeStatusAnalyticsItem(
                status=row.status,
                ledgers=int(row.ledgers or 0),
                billed_amount=round(float(row.billed or 0), 2),
                paid_amount=round(float(row.paid or 0), 2),
                outstanding_amount=round(
                    max(float(row.billed or 0) - float(row.paid or 0), 0.0), 2
                ),
            )
            for row in by_status_rows
        ]

        # ── By payment mode ────────────────────────────────────────────────
        by_payment_mode_stmt = (
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
            .order_by(func.sum(Payment.amount).desc())
        )
        by_payment_mode_rows = (await self.db.execute(by_payment_mode_stmt)).all()
        by_payment_mode = [
            PaymentModeAnalyticsItem(
                payment_mode=row.payment_mode,
                amount=round(float(row.amount or 0), 2),
                transactions=int(row.transactions or 0),
            )
            for row in by_payment_mode_rows
        ]

        # ── By student ─────────────────────────────────────────────────────
        by_student_stmt = (
            select(
                FeeLedger.student_id,
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
                func.max(Payment.payment_date).label("latest_payment_date"),
            )
            .select_from(FeeLedger)
            .join(FeeStructure, FeeStructure.id == FeeLedger.fee_structure_id)
            .join(Student, Student.id == FeeLedger.student_id)
            .outerjoin(Payment, Payment.fee_ledger_id == FeeLedger.id)
            .where(*ledger_where)
            .group_by(
                FeeLedger.student_id,
                Student.admission_number,
                Student.standard_id,
                Student.section,
            )
            .order_by(func.sum(FeeLedger.paid_amount).desc(), Student.admission_number.asc())
        )
        by_student_rows = (await self.db.execute(by_student_stmt)).all()
        by_student = [
            FeeStudentAnalyticsItem(
                student_id=row.student_id,
                admission_number=row.admission_number,
                standard_id=row.standard_id,
                section=row.section,
                billed_amount=round(float(row.billed or 0), 2),
                paid_amount=round(float(row.paid or 0), 2),
                outstanding_amount=round(
                    max(float(row.billed or 0) - float(row.paid or 0), 0.0), 2
                ),
                ledgers=int(row.ledgers or 0),
                paid_ledgers=int(row.paid_ledgers or 0),
                partial_ledgers=int(row.partial_ledgers or 0),
                pending_ledgers=int(row.pending_ledgers or 0),
                overdue_ledgers=int(row.overdue_ledgers or 0),
                is_defaulter=int(row.overdue_ledgers or 0) > 0,
                latest_payment_date=row.latest_payment_date,
            )
            for row in by_student_rows
        ]

        # ── By class ───────────────────────────────────────────────────────
        class_rows = await self.repo.get_class_analytics(
            school_id=school_id,
            academic_year_id=resolved_year_id,
        )
        by_class = []
        for row in class_rows:
            tb = float(row["total_billed"] or 0)
            tp = float(row["total_paid"] or 0)
            coll_pct = round((tp / tb) * 100, 2) if tb > 0 else 0.0
            by_class.append(
                FeeClassAnalyticsItem(
                    standard_id=row["standard_id"],
                    standard_name=row["standard_name"],
                    section=row.get("section"),
                    total_students=int(row["total_students"] or 0),
                    total_billed=round(tb, 2),
                    total_paid=round(tp, 2),
                    total_outstanding=round(max(tb - tp, 0.0), 2),
                    collection_percentage=coll_pct,
                    defaulters_count=int(row.get("defaulters_count") or 0),
                )
            )

        # ── By installment ─────────────────────────────────────────────────
        inst_rows = await self.repo.get_installment_analytics(
            school_id=school_id,
            academic_year_id=resolved_year_id,
        )
        by_installment = []
        for row in inst_rows:
            tb = float(row["total_billed"] or 0)
            tp = float(row["total_paid"] or 0)
            coll_pct = round((tp / tb) * 100, 2) if tb > 0 else 0.0
            by_installment.append(
                FeeInstallmentAnalyticsItem(
                    installment_name=row["installment_name"],
                    total_ledgers=int(row["total_ledgers"] or 0),
                    paid_ledgers=int(row["paid_ledgers"] or 0),
                    partial_ledgers=int(row["partial_ledgers"] or 0),
                    pending_ledgers=int(row["pending_ledgers"] or 0),
                    overdue_ledgers=int(row["overdue_ledgers"] or 0),
                    total_billed=round(tb, 2),
                    total_paid=round(tp, 2),
                    total_outstanding=round(max(tb - tp, 0.0), 2),
                    collection_percentage=coll_pct,
                )
            )

        await self.db.commit()
        return FeeAnalyticsResponse(
            academic_year_id=resolved_year_id,
            report_date=report_date,
            filters={
                "standard_id": str(standard_id) if standard_id else None,
                "section": section_value,
                "student_id": str(student_id) if student_id else None,
            },
            summary=FeeAnalyticsSummary(
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
            ),
            by_category=by_category,
            by_status=by_status,
            by_payment_mode=by_payment_mode,
            by_student=by_student,
            by_class=by_class,
            by_installment=by_installment,
        )


# ---------------------------------------------------------------------------
# Receipt HTML builder
# ---------------------------------------------------------------------------

def _build_receipt_html(
    *,
    student_id: uuid.UUID,
    fee_head: str,
    installment_name: str,
    amount: float,
    payment_date: date,
    payment_mode,
    reference_number: Optional[str],
    total_amount: float,
    paid_so_far: float,
    due_date: Optional[date],
    late_fee_applied: bool,
) -> str:
    outstanding = max(total_amount - paid_so_far, 0.0)
    late_note = (
        "<p style='color:red;font-weight:bold;'>⚠ Late payment — paid after due date.</p>"
        if late_fee_applied
        else ""
    )
    installment_row = (
        f"<tr><td>Installment</td><td>{installment_name}</td></tr>"
        if installment_name
        else ""
    )
    due_row = (
        f"<tr><td>Due Date</td><td>{due_date}</td></tr>"
        if due_date
        else ""
    )
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8"/>
      <style>
        body {{ font-family: Arial, sans-serif; margin: 40px; color: #333; }}
        h2   {{ color: #2c3e50; border-bottom: 2px solid #2c3e50; padding-bottom: 8px; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 16px; }}
        td   {{ padding: 8px 12px; border: 1px solid #ddd; }}
        td:first-child {{ font-weight: bold; background: #f5f5f5; width: 40%; }}
        .footer {{ margin-top: 24px; font-size: 12px; color: #888; }}
        .paid {{ color: green; font-weight: bold; }}
        .outstanding {{ color: {'red' if outstanding > 0 else 'green'}; font-weight: bold; }}
      </style>
    </head>
    <body>
      <h2>Fee Payment Receipt</h2>
      {late_note}
      <table>
        <tr><td>Student ID</td><td>{student_id}</td></tr>
        <tr><td>Fee Head</td><td>{fee_head}</td></tr>
        {installment_row}
        <tr><td>Total Fee Amount</td><td>₹ {total_amount:.2f}</td></tr>
        <tr><td>Amount Paid (this payment)</td><td class="paid">₹ {amount:.2f}</td></tr>
        <tr><td>Total Paid So Far</td><td class="paid">₹ {paid_so_far:.2f}</td></tr>
        <tr><td>Outstanding Balance</td><td class="outstanding">₹ {outstanding:.2f}</td></tr>
        {due_row}
        <tr><td>Payment Date</td><td>{payment_date}</td></tr>
        <tr><td>Payment Mode</td><td>{payment_mode}</td></tr>
        <tr><td>Reference / Transaction Ref</td><td>{reference_number or '—'}</td></tr>
      </table>
      <div class="footer">
        This is a system-generated receipt. No signature required.
        Receipt generated on {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC.
      </div>
    </body>
    </html>
    """