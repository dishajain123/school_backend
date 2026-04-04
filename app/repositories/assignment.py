import uuid
from datetime import date
from typing import Optional
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.assignment import Assignment


def _with_relations(stmt):
    return stmt.options(
        selectinload(Assignment.teacher),
        selectinload(Assignment.standard),
        selectinload(Assignment.subject),
        selectinload(Assignment.academic_year),
    )


class AssignmentRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: dict) -> Assignment:
        obj = Assignment(**data)
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def get_by_id(
        self, assignment_id: uuid.UUID, school_id: uuid.UUID
    ) -> Optional[Assignment]:
        result = await self.db.execute(
            _with_relations(
                select(Assignment).where(
                    and_(
                        Assignment.id == assignment_id,
                        Assignment.school_id == school_id,
                    )
                )
            )
        )
        return result.scalar_one_or_none()

    async def list_by_school(
        self,
        school_id: uuid.UUID,
        standard_id: Optional[uuid.UUID] = None,
        subject_id: Optional[uuid.UUID] = None,
        academic_year_id: Optional[uuid.UUID] = None,
        teacher_id: Optional[uuid.UUID] = None,
        is_active: Optional[bool] = None,
        is_overdue: Optional[bool] = None,
        reference_date: Optional[date] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Assignment], int]:
        base_where = [Assignment.school_id == school_id]

        if standard_id:
            base_where.append(Assignment.standard_id == standard_id)
        if subject_id:
            base_where.append(Assignment.subject_id == subject_id)
        if academic_year_id:
            base_where.append(Assignment.academic_year_id == academic_year_id)
        if teacher_id:
            base_where.append(Assignment.teacher_id == teacher_id)
        if is_active is not None:
            base_where.append(Assignment.is_active == is_active)
        if is_overdue is not None:
            today = reference_date or date.today()
            if is_overdue:
                base_where.append(Assignment.due_date < today)
            else:
                base_where.append(Assignment.due_date >= today)

        stmt = select(Assignment).where(and_(*base_where))
        count_q = select(func.count(Assignment.id)).where(and_(*base_where))

        total = (await self.db.execute(count_q)).scalar_one()
        offset = (page - 1) * page_size
        rows = await self.db.execute(
            _with_relations(
                stmt.order_by(Assignment.created_at.desc())
                .offset(offset)
                .limit(page_size)
            )
        )
        return list(rows.scalars().all()), total

    async def update(self, assignment: Assignment, data: dict) -> Assignment:
        for key, value in data.items():
            setattr(assignment, key, value)
        await self.db.flush()
        await self.db.refresh(assignment)
        return assignment
