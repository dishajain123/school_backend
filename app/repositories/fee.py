# app/repositories/fee.py
import math
import uuid
from datetime import date
from typing import Optional

from sqlalchemy import (
    String,
    and_,
    case,
    delete,
    func,
    literal,
    or_,
    select,
    update,
)
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

    # ------------------------------------------------------------------
    # Class fee student list (admin console) — DB-level pagination
    # ------------------------------------------------------------------

    def _class_fee_rollup_subquery(
        self,
        *,
        school_id: uuid.UUID,
        standard_id: uuid.UUID,
        academic_year_id: uuid.UUID,
    ):
        """
        One row per student_id with ledger aggregates for structures in
        this standard + academic year only (matches legacy list behavior).
        """
        _str = String(20)
        od_ct = func.coalesce(
            func.sum(
                case((FeeLedger.status == FeeStatus.OVERDUE, 1), else_=0)
            ),
            0,
        ).label("od_ct")
        mh = func.coalesce(
            func.sum(
                case((FeeLedger.installment_name.ilike("%month%"), 1), else_=0)
            ),
            0,
        ).label("mh")
        qh = func.coalesce(
            func.sum(
                case((FeeLedger.installment_name.ilike("%quarter%"), 1), else_=0)
            ),
            0,
        ).label("qh")
        yh = func.coalesce(
            func.sum(
                case((FeeLedger.installment_name.ilike("%year%"), 1), else_=0)
            ),
            0,
        ).label("yh")
        return (
            select(
                FeeLedger.student_id.label("student_id"),
                func.coalesce(func.sum(FeeLedger.total_amount), 0).label("tb"),
                func.coalesce(func.sum(FeeLedger.paid_amount), 0).label("tp"),
                func.count(FeeLedger.id).label("lcnt"),
                od_ct,
                mh,
                qh,
                yh,
            )
            .join(FeeStructure, FeeStructure.id == FeeLedger.fee_structure_id)
            .where(
                FeeLedger.school_id == school_id,
                FeeStructure.academic_year_id == academic_year_id,
                FeeStructure.standard_id == standard_id,
            )
            .group_by(FeeLedger.student_id)
        ).subquery()

    async def count_and_page_class_fee_student_ids(
        self,
        *,
        school_id: uuid.UUID,
        standard_id: uuid.UUID,
        academic_year_id: uuid.UUID,
        section: Optional[str],
        payment_cycle: Optional[str],
        status_filter: Optional[str],
        page: int,
        page_size: int,
    ) -> tuple[int, list[uuid.UUID], int, int]:
        """
        Applies the same derived status / payment-cycle rules as FeeService
        (mirrored in SQL), counts matching students, returns one page of IDs
        ordered by admission_number ascending.

        Returns ``(total_matches, student_ids, effective_page, effective_page_size)``.
        """
        R = self._class_fee_rollup_subquery(
            school_id=school_id,
            standard_id=standard_id,
            academic_year_id=academic_year_id,
        )

        tb_c = func.coalesce(R.c.tb, 0)
        tp_c = func.coalesce(R.c.tp, 0)
        lcnt_c = func.coalesce(R.c.lcnt, 0)
        mh_c = func.coalesce(R.c.mh, 0)
        qh_c = func.coalesce(R.c.qh, 0)
        yh_c = func.coalesce(R.c.yh, 0)

        outstanding = func.greatest(tb_c - tp_c, 0)
        has_overdue = func.coalesce(R.c.od_ct, 0) >= 1

        _pay = String(24)
        rollup_cycle = case(
            (lcnt_c == 0, literal("UNASSIGNED", type_=_pay)),
            (mh_c > 0, literal("MONTHLY", type_=_pay)),
            (qh_c > 0, literal("QUARTERLY", type_=_pay)),
            (yh_c > 0, literal("YEARLY", type_=_pay)),
            (lcnt_c >= 10, literal("MONTHLY", type_=_pay)),
            (lcnt_c == 4, literal("QUARTERLY", type_=_pay)),
            (lcnt_c <= 2, literal("YEARLY", type_=_pay)),
            else_=literal("CUSTOM", type_=_pay),
        )

        rollup_status = case(
            (has_overdue, literal("OVERDUE", type_=_pay)),
            (
                and_(outstanding <= 0.01, tp_c > 0),
                literal("PAID", type_=_pay),
            ),
            (
                and_(tp_c > 0, outstanding > 0.01),
                literal("PARTIAL", type_=_pay),
            ),
            else_=literal("PENDING", type_=_pay),
        )

        year_rel = or_(
            Student.academic_year_id == academic_year_id,
            Student.academic_year_id.is_(None),
        )
        stu_where = and_(
            Student.school_id == school_id,
            Student.standard_id == standard_id,
            year_rel,
        )
        if section is not None and section.strip():
            stu_where = and_(stu_where, Student.section == section.strip())

        filtered = (
            select(
                Student.id.label("student_id"),
                Student.admission_number.label("adm"),
            )
            .select_from(Student)
            .outerjoin(R, R.c.student_id == Student.id)
            .where(stu_where)
        )

        if status_filter and status_filter.strip():
            filtered = filtered.where(
                rollup_status == status_filter.strip().upper()
            )
        if payment_cycle and payment_cycle.strip():
            filtered = filtered.where(
                rollup_cycle == payment_cycle.strip().upper()
            )

        filtered_sq = filtered.subquery()

        count_stmt = select(func.count()).select_from(filtered_sq)
        total = int((await self.db.execute(count_stmt)).scalar_one() or 0)

        safe_size = max(1, min(page_size, 100))
        safe_page = max(1, page)
        total_pages = max(1, math.ceil(total / safe_size)) if total else 1
        if total and safe_page > total_pages:
            safe_page = total_pages
        offset = (safe_page - 1) * safe_size

        page_stmt = (
            select(filtered_sq.c.student_id)
            .select_from(filtered_sq)
            .order_by(filtered_sq.c.adm.asc())
            .offset(offset)
            .limit(safe_size)
        )
        rows = (await self.db.execute(page_stmt)).scalars().all()

        return total, list(rows), safe_page, safe_size

    async def list_ledgers_class_fee_for_students(
        self,
        *,
        school_id: uuid.UUID,
        standard_id: uuid.UUID,
        academic_year_id: uuid.UUID,
        student_ids: list[uuid.UUID],
    ) -> list[FeeLedger]:
        """Ledgers for given students, scoped to class structures only."""
        if not student_ids:
            return []
        stmt = (
            select(FeeLedger)
            .join(FeeStructure, FeeStructure.id == FeeLedger.fee_structure_id)
            .where(
                FeeLedger.school_id == school_id,
                FeeStructure.academic_year_id == academic_year_id,
                FeeStructure.standard_id == standard_id,
                FeeLedger.student_id.in_(student_ids),
            )
            .order_by(
                FeeLedger.student_id.asc(),
                FeeLedger.due_date.asc().nullsfirst(),
                FeeLedger.created_at.asc(),
            )
        )
        stmt = stmt.options(
            selectinload(FeeLedger.fee_structure).selectinload(
                FeeStructure.standard
            ),
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())