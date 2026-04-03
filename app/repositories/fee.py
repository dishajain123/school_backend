import uuid
from typing import Optional

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.fee import FeeStructure, FeeLedger
from app.models.payment import Payment


def _structure_with_relations(stmt):
    return stmt.options(
        selectinload(FeeStructure.standard),
        selectinload(FeeStructure.academic_year),
    )


def _ledger_with_relations(stmt):
    return stmt.options(
        selectinload(FeeLedger.fee_structure),
        selectinload(FeeLedger.student),
    )


class FeeRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # Fee Structures
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
    ) -> Optional[FeeStructure]:
        result = await self.db.execute(
            select(FeeStructure).where(
                and_(
                    FeeStructure.school_id == school_id,
                    FeeStructure.standard_id == standard_id,
                    FeeStructure.academic_year_id == academic_year_id,
                    FeeStructure.fee_category == fee_category,
                )
            )
        )
        return result.scalar_one_or_none()

    async def list_structures_for_standard(
        self, school_id: uuid.UUID, standard_id: uuid.UUID, academic_year_id: uuid.UUID
    ) -> list[FeeStructure]:
        result = await self.db.execute(
            _structure_with_relations(
                select(FeeStructure).where(
                    and_(
                        FeeStructure.school_id == school_id,
                        FeeStructure.standard_id == standard_id,
                        FeeStructure.academic_year_id == academic_year_id,
                    )
                )
            )
        )
        return list(result.scalars().all())

    # Fee Ledger
    async def create_ledger(self, data: dict) -> FeeLedger:
        obj = FeeLedger(**data)
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

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

    async def get_ledger_existing(
        self, student_id: uuid.UUID, fee_structure_id: uuid.UUID
    ) -> Optional[FeeLedger]:
        result = await self.db.execute(
            select(FeeLedger).where(
                and_(
                    FeeLedger.student_id == student_id,
                    FeeLedger.fee_structure_id == fee_structure_id,
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
                )
            )
        )
        return list(result.scalars().all())

    async def update_ledger(self, ledger: FeeLedger, data: dict) -> FeeLedger:
        for key, value in data.items():
            setattr(ledger, key, value)
        await self.db.flush()
        await self.db.refresh(ledger)
        return ledger

    # Payments
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
        return result.scalar_one_or_none()\r\n\r\n    async def list_payments_for_ledger(
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
            .order_by(Payment.created_at.desc())
        )
        return list(result.scalars().all())


