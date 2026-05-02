# app/repositories/fee.py
import math
import uuid
from datetime import date
from typing import Optional

from sqlalchemy import select, and_, update, func, distinct, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.fee import FeeStructure, FeeLedger
from app.models.payment import Payment
from app.models.student import Student
from app.utils.enums import FeeStatus


def _structure_with_relations(stmt):
    return stmt.options(
        selectinload(FeeStructure.standard),
        selectinload(FeeStructure.academic_year),
    )


def _ledger_with_relations(stmt):
    return stmt.options(
        selectinload(FeeLedger.fee_structure).selectinload(FeeStructure.standard),
        selectinload(FeeLedger.student).selectinload(Student.user),
    )


class FeeRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------
    # Fee Structures
    # ------------------------------------------------------------------

    async def create_structure(self, data: dict) -> FeeStructure:
        obj = FeeStructure(**data)
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def get_structure_by_id(
        self, structure_id: uuid.UUID, school_id: uuid.UUID
    ) -> Optional[FeeStructure]:
        result = await self.db.execute(
            _structure_with_relations(
                select(FeeStructure).where(
                    and_(
                        FeeStructure.id == structure_id,
                        FeeStructure.school_id == school_id,
                    )
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_structure_duplicate(
        self,
        school_id: uuid.UUID,
        standard_id: uuid.UUID,
        academic_year_id: uuid.UUID,
        fee_category,
        custom_fee_head: str = "",
    ) -> Optional[FeeStructure]:
        result = await self.db.execute(
            select(FeeStructure).where(
                and_(
                    FeeStructure.school_id == school_id,
                    FeeStructure.standard_id == standard_id,
                    FeeStructure.academic_year_id == academic_year_id,
                    FeeStructure.fee_category == fee_category,
                    FeeStructure.custom_fee_head == custom_fee_head,
                )
            )
        )
        return result.scalar_one_or_none()

    async def list_structures_for_standard(
        self,
        school_id: uuid.UUID,
        standard_id: uuid.UUID,
        academic_year_id: uuid.UUID,
    ) -> list[FeeStructure]:
        result = await self.db.execute(
            _structure_with_relations(
                select(FeeStructure).where(
                    and_(
                        FeeStructure.school_id == school_id,
                        FeeStructure.standard_id == standard_id,
                        FeeStructure.academic_year_id == academic_year_id,
                    )
                ).order_by(FeeStructure.fee_category.asc(), FeeStructure.custom_fee_head.asc())
            )
        )
        return list(result.scalars().all())

    async def update_structure(self, structure: FeeStructure, data: dict) -> FeeStructure:
        for key, value in data.items():
            setattr(structure, key, value)
        await self.db.flush()
        await self.db.refresh(structure)
        return structure

    async def delete_structure(self, structure: FeeStructure) -> None:
        await self.db.delete(structure)
        await self.db.flush()

    async def count_ledgers_for_structure(
        self, structure_id: uuid.UUID, school_id: uuid.UUID
    ) -> int:
        result = await self.db.execute(
            select(func.count(FeeLedger.id)).where(
                and_(
                    FeeLedger.fee_structure_id == structure_id,
                    FeeLedger.school_id == school_id,
                )
            )
        )
        return int(result.scalar_one() or 0)

    async def count_payments_for_structure(
        self, structure_id: uuid.UUID, school_id: uuid.UUID
    ) -> int:
        result = await self.db.execute(
            select(func.count(Payment.id))
            .select_from(Payment)
            .join(FeeLedger, FeeLedger.id == Payment.fee_ledger_id)
            .where(
                and_(
                    FeeLedger.fee_structure_id == structure_id,
                    Payment.school_id == school_id,
                )
            )
        )
        return int(result.scalar_one() or 0)

    async def delete_ledgers_for_structure(
        self, structure_id: uuid.UUID, school_id: uuid.UUID
    ) -> int:
        result = await self.db.execute(
            delete(FeeLedger).where(
                and_(
                    FeeLedger.fee_structure_id == structure_id,
                    FeeLedger.school_id == school_id,
                )
            )
        )
        return result.rowcount or 0

    # ------------------------------------------------------------------
    # Fee Ledger
    # ------------------------------------------------------------------

    async def create_ledger(self, data: dict) -> FeeLedger:
        obj = FeeLedger(**data)
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def get_ledger_duplicate(
        self,
        student_id: uuid.UUID,
        fee_structure_id: uuid.UUID,
        installment_name: str,
    ) -> Optional[FeeLedger]:
        result = await self.db.execute(
            select(FeeLedger).where(
                and_(
                    FeeLedger.student_id == student_id,
                    FeeLedger.fee_structure_id == fee_structure_id,
                    FeeLedger.installment_name == installment_name,
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_ledger_by_id(
        self, ledger_id: uuid.UUID, school_id: uuid.UUID
    ) -> Optional[FeeLedger]:
        result = await self.db.execute(
            _ledger_with_relations(
                select(FeeLedger).where(
                    and_(
                        FeeLedger.id == ledger_id,
                        FeeLedger.school_id == school_id,
                    )
                )
            )
        )
        return result.scalar_one_or_none()

    async def list_ledger_for_student(
        self, school_id: uuid.UUID, student_id: uuid.UUID
    ) -> list[FeeLedger]:
        result = await self.db.execute(
            _ledger_with_relations(
                select(FeeLedger).where(
                    and_(
                        FeeLedger.school_id == school_id,
                        FeeLedger.student_id == student_id,
                    )
                ).order_by(FeeLedger.due_date.asc().nullsfirst(), FeeLedger.created_at.asc())
            )
        )
        return list(result.scalars().all())

    async def list_all_ledgers_paginated(
        self,
        school_id: uuid.UUID,
        academic_year_id: Optional[uuid.UUID] = None,
        standard_id: Optional[uuid.UUID] = None,
        student_id: Optional[uuid.UUID] = None,
        status: Optional[FeeStatus] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[FeeLedger], int]:
        """Return paginated ledger entries for admin view."""
        stmt = (
            select(FeeLedger)
            .join(FeeStructure, FeeStructure.id == FeeLedger.fee_structure_id)
            .where(FeeLedger.school_id == school_id)
        )

        if academic_year_id is not None:
            stmt = stmt.where(FeeStructure.academic_year_id == academic_year_id)
        if standard_id is not None:
            stmt = stmt.where(FeeStructure.standard_id == standard_id)
        if student_id is not None:
            stmt = stmt.where(FeeLedger.student_id == student_id)
        if status is not None:
            stmt = stmt.where(FeeLedger.status == status)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_result = await self.db.execute(count_stmt)
        total = int(total_result.scalar_one() or 0)

        stmt = stmt.order_by(
            FeeLedger.status.asc(),
            FeeLedger.due_date.asc().nullsfirst(),
            FeeLedger.created_at.asc(),
        ).offset((page - 1) * page_size).limit(page_size)

        result = await self.db.execute(
            stmt.options(
                selectinload(FeeLedger.fee_structure).selectinload(FeeStructure.standard),
                selectinload(FeeLedger.student).selectinload(Student.user),
            )
        )
        return list(result.scalars().all()), total

    async def update_ledger(self, ledger: FeeLedger, data: dict) -> FeeLedger:
        for key, value in data.items():
            setattr(ledger, key, value)
        await self.db.flush()
        return ledger

    async def mark_overdue_ledgers(
        self,
        school_id: uuid.UUID,
        academic_year_id: uuid.UUID,
        as_of_date: date,
    ) -> int:
        result = await self.db.execute(
            update(FeeLedger)
            .where(
                and_(
                    FeeLedger.school_id == school_id,
                    FeeLedger.status.in_([FeeStatus.PENDING, FeeStatus.PARTIAL]),
                    FeeLedger.due_date < as_of_date,
                    FeeLedger.due_date.is_not(None),
                    FeeLedger.fee_structure_id.in_(
                        select(FeeStructure.id).where(
                            FeeStructure.academic_year_id == academic_year_id
                        )
                    ),
                )
            )
            .values(status=FeeStatus.OVERDUE)
        )
        return result.rowcount

    # ------------------------------------------------------------------
    # Payments
    # ------------------------------------------------------------------

    async def create_payment(self, data: dict) -> Payment:
        obj = Payment(**data)
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def get_payment_by_id(
        self, payment_id: uuid.UUID, school_id: uuid.UUID
    ) -> Optional[Payment]:
        result = await self.db.execute(
            select(Payment).where(
                and_(
                    Payment.id == payment_id,
                    Payment.school_id == school_id,
                )
            )
        )
        return result.scalar_one_or_none()

    async def list_payments_for_ledger(
        self, school_id: uuid.UUID, fee_ledger_id: uuid.UUID
    ) -> list[Payment]:
        result = await self.db.execute(
            select(Payment)
            .where(
                and_(
                    Payment.school_id == school_id,
                    Payment.fee_ledger_id == fee_ledger_id,
                )
            )
            .order_by(Payment.payment_date.desc(), Payment.created_at.desc())
        )
        return list(result.scalars().all())