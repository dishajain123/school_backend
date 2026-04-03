import uuid
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import ForbiddenException, ConflictException, ValidationException, NotFoundException
from app.repositories.fee import FeeRepository
from app.schemas.fee import (
    FeeStructureCreate,
    FeeStructureResponse,
    LedgerGenerateRequest,
    LedgerGenerateResponse,
    PaymentCreate,
    PaymentResponse,
    FeeLedgerResponse,
    FeeDashboardResponse,\n    PaymentListResponse,
)
from app.services.academic_year import get_active_year
from app.integrations.minio_client import minio_client
from app.integrations import pdf_service
from app.utils.enums import RoleEnum, FeeStatus

RECEIPTS_BUCKET = "receipts"


class FeeService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = FeeRepository(db)

    def _ensure_school(self, current_user: CurrentUser) -> uuid.UUID:
        if not current_user.school_id:
            raise ValidationException("school_id is required")
        return current_user.school_id

    async def create_structure(
        self,
        body: FeeStructureCreate,
        current_user: CurrentUser,
    ) -> FeeStructureResponse:
        school_id = self._ensure_school(current_user)
        academic_year_id = body.academic_year_id
        if not academic_year_id:
            academic_year_id = (await get_active_year(school_id, self.db)).id

        existing = await self.repo.get_structure_duplicate(
            school_id=school_id,
            standard_id=body.standard_id,
            academic_year_id=academic_year_id,
            fee_category=body.fee_category,
        )
        if existing:
            raise ConflictException("Fee structure already exists for this class and year")

        structure = await self.repo.create_structure(
            {
                "standard_id": body.standard_id,
                "academic_year_id": academic_year_id,
                "fee_category": body.fee_category,
                "amount": body.amount,
                "due_date": body.due_date,
                "description": body.description,
                "school_id": school_id,
            }
        )
        await self.db.commit()
        await self.db.refresh(structure)
        return FeeStructureResponse.model_validate(structure)

    async def generate_ledger(
        self,
        body: LedgerGenerateRequest,
        current_user: CurrentUser,
    ) -> LedgerGenerateResponse:
        school_id = self._ensure_school(current_user)
        academic_year_id = body.academic_year_id
        if not academic_year_id:
            academic_year_id = (await get_active_year(school_id, self.db)).id

        from app.models.student import Student

        students_result = await self.db.execute(
            select(Student.id).where(
                and_(
                    Student.school_id == school_id,
                    Student.standard_id == body.standard_id,
                )
            )
        )
        student_ids = [row[0] for row in students_result.all()]

        structures = await self.repo.list_structures_for_standard(
            school_id=school_id,
            standard_id=body.standard_id,
            academic_year_id=academic_year_id,
        )
        if not structures:
            raise NotFoundException("Fee structure")

        created = 0
        skipped = 0
        for student_id in student_ids:
            for structure in structures:
                existing = await self.repo.get_ledger_existing(
                    student_id=student_id,
                    fee_structure_id=structure.id,
                )
                if existing:
                    skipped += 1
                    continue
                await self.repo.create_ledger(
                    {
                        "student_id": student_id,
                        "fee_structure_id": structure.id,
                        "total_amount": structure.amount,
                        "paid_amount": 0,
                        "status": FeeStatus.PENDING,
                        "school_id": school_id,
                    }
                )
                created += 1

        await self.db.commit()
        return LedgerGenerateResponse(created=created, skipped=skipped)

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

        new_paid = float(ledger.paid_amount) + body.amount
        if new_paid < 0:
            raise ValidationException("Invalid payment amount")
        if new_paid > float(ledger.total_amount) + 0.01:
            raise HTTPException(status_code=422, detail="Payment exceeds total amount")

        if new_paid == 0:
            new_status = FeeStatus.PENDING
        elif new_paid < float(ledger.total_amount):
            new_status = FeeStatus.PARTIAL
        else:
            new_status = FeeStatus.PAID

        late_fee_applied = payment_date > structure.due_date

        # Generate receipt PDF
        receipt_html = f"""
        <html><body>
        <h2>Fee Receipt</h2>
        <p>Student ID: {body.student_id}</p>
        <p>Fee Category: {structure.fee_category}</p>
        <p>Amount Paid: {body.amount}</p>
        <p>Payment Date: {payment_date}</p>
        <p>Mode: {body.payment_mode}</p>
        <p>Reference: {body.reference_number or '-'}</p>
        </body></html>
        """
        pdf_bytes = pdf_service.generate_pdf(receipt_html)
        receipt_key = (
            f"{school_id}/{body.student_id}/{uuid.uuid4()}_fee_receipt.pdf"
        )
        minio_client.upload_file(
            bucket=RECEIPTS_BUCKET,
            key=receipt_key,
            file_bytes=pdf_bytes,
            content_type="application/pdf",
        )

        payment = await self.repo.create_payment(
            {
                "student_id": body.student_id,
                "fee_ledger_id": body.fee_ledger_id,
                "amount": body.amount,
                "payment_date": payment_date,
                "payment_mode": body.payment_mode,
                "reference_number": body.reference_number,
                "receipt_key": receipt_key,
                "recorded_by": current_user.id,
                "late_fee_applied": late_fee_applied,
                "original_due_date": structure.due_date,
                "school_id": school_id,
            }
        )

        await self.repo.update_ledger(
            ledger,
            {"paid_amount": new_paid, "status": new_status},
        )

        await self.db.commit()
        await self.db.refresh(payment)
        return PaymentResponse.model_validate(payment)

    async def fee_dashboard(
        self,
        student_id: uuid.UUID,
        current_user: CurrentUser,
    ) -> FeeDashboardResponse:
        school_id = self._ensure_school(current_user)

        from app.models.student import Student

        if current_user.role == RoleEnum.STUDENT:
            result = await self.db.execute(
                select(Student.id).where(
                    and_(
                        Student.user_id == current_user.id,
                        Student.school_id == school_id,
                    )
                )
            )
            own_student_id = result.scalar_one_or_none()
            if not own_student_id or own_student_id != student_id:
                raise ForbiddenException("You can only view your own fees")

        elif current_user.role == RoleEnum.PARENT:
            result = await self.db.execute(
                select(Student.id).where(
                    and_(
                        Student.id == student_id,
                        Student.parent_id == current_user.parent_id,
                        Student.school_id == school_id,
                    )
                )
            )
            if not result.scalar_one_or_none():
                raise ForbiddenException("Not your child")

        ledgers = await self.repo.list_ledger_for_student(school_id, student_id)
        items = []
        for ledger in ledgers:
            outstanding = float(ledger.total_amount) - float(ledger.paid_amount)
            data = FeeLedgerResponse.model_validate(ledger)
            data.outstanding_amount = max(outstanding, 0.0)
            items.append(data)

        return FeeDashboardResponse(items=items, total=len(items))

    
    async def list_payments(
        self,
        fee_ledger_id: uuid.UUID,
        current_user: CurrentUser,
    ) -> PaymentListResponse:
        school_id = self._ensure_school(current_user)

        ledger = await self.repo.get_ledger_by_id(fee_ledger_id, school_id)
        if not ledger:
            raise NotFoundException("Fee ledger")

        from app.models.student import Student

        if current_user.role == RoleEnum.STUDENT:
            result = await self.db.execute(
                select(Student.id).where(
                    and_(
                        Student.user_id == current_user.id,
                        Student.school_id == school_id,
                    )
                )
            )
            own_student_id = result.scalar_one_or_none()
            if not own_student_id or own_student_id != ledger.student_id:
                raise ForbiddenException("You can only view your own payments")

        elif current_user.role == RoleEnum.PARENT:
            result = await self.db.execute(
                select(Student.id).where(
                    and_(
                        Student.id == ledger.student_id,
                        Student.parent_id == current_user.parent_id,
                        Student.school_id == school_id,
                    )
                )
            )
            if not result.scalar_one_or_none():
                raise ForbiddenException("Not your child")

        payments = await self.repo.list_payments_for_ledger(
            school_id, fee_ledger_id
        )
        items = [PaymentResponse.model_validate(p) for p in payments]
        return PaymentListResponse(items=items, total=len(items))

    async def get_receipt_url(
        self,
        payment_id: uuid.UUID,
        current_user: CurrentUser,
    ) -> str:
        school_id = self._ensure_school(current_user)
        payment = await self.repo.get_payment_by_id(payment_id, school_id)
        if not payment:
            raise NotFoundException("Payment")

        from app.models.student import Student

        if current_user.role == RoleEnum.STUDENT:
            result = await self.db.execute(
                select(Student.id).where(
                    and_(
                        Student.user_id == current_user.id,
                        Student.school_id == school_id,
                    )
                )
            )
            own_student_id = result.scalar_one_or_none()
            if not own_student_id or own_student_id != payment.student_id:
                raise ForbiddenException("You can only view your own receipt")

        elif current_user.role == RoleEnum.PARENT:
            result = await self.db.execute(
                select(Student.id).where(
                    and_(
                        Student.id == payment.student_id,
                        Student.parent_id == current_user.parent_id,
                        Student.school_id == school_id,
                    )
                )
            )
            if not result.scalar_one_or_none():
                raise ForbiddenException("Not your child")

        if not payment.receipt_key:
            raise NotFoundException("Receipt")

        return minio_client.generate_presigned_url(
            RECEIPTS_BUCKET, payment.receipt_key
        )



