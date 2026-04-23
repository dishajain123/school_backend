import uuid
from datetime import date
from typing import Optional
from sqlalchemy import select, func, and_, exists
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.assignment import Assignment
from app.models.submission import Submission
from app.utils.date_utils import today_in_app_timezone


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
        is_submitted: Optional[bool] = None,
        submission_student_ids: Optional[list[uuid.UUID]] = None,
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
        # When overdue segmentation is requested, default to active assignments
        # unless the caller explicitly asks otherwise.
        if is_overdue is not None and is_active is None:
            base_where.append(Assignment.is_active.is_(True))
        elif is_active is not None:
            base_where.append(Assignment.is_active == is_active)
        if is_overdue is not None:
            today = reference_date or today_in_app_timezone()
            if is_overdue:
                base_where.append(Assignment.due_date < today)
            else:
                base_where.append(Assignment.due_date >= today)
        if is_submitted is not None:
            sub_where = [
                Submission.assignment_id == Assignment.id,
                Submission.school_id == school_id,
            ]
            if submission_student_ids is not None:
                if not submission_student_ids:
                    # If no relevant students, there cannot be submitted assignments.
                    return ([], 0) if is_submitted else await self.list_by_school(
                        school_id=school_id,
                        standard_id=standard_id,
                        subject_id=subject_id,
                        academic_year_id=academic_year_id,
                        teacher_id=teacher_id,
                        is_active=is_active,
                        is_overdue=is_overdue,
                        is_submitted=None,
                        submission_student_ids=None,
                        reference_date=reference_date,
                        page=page,
                        page_size=page_size,
                    )
                sub_where.append(Submission.student_id.in_(submission_student_ids))
            submission_exists = exists(
                select(Submission.id).where(and_(*sub_where))
            )
            base_where.append(submission_exists if is_submitted else ~submission_exists)

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

    async def list_by_teacher_global(
        self,
        teacher_id: uuid.UUID,
        standard_id: Optional[uuid.UUID] = None,
        subject_id: Optional[uuid.UUID] = None,
        academic_year_id: Optional[uuid.UUID] = None,
        is_active: Optional[bool] = None,
        is_overdue: Optional[bool] = None,
        reference_date: Optional[date] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Assignment], int]:
        base_where = [Assignment.teacher_id == teacher_id]

        if standard_id:
            base_where.append(Assignment.standard_id == standard_id)
        if subject_id:
            base_where.append(Assignment.subject_id == subject_id)
        if academic_year_id:
            base_where.append(Assignment.academic_year_id == academic_year_id)

        if is_overdue is not None and is_active is None:
            base_where.append(Assignment.is_active.is_(True))
        elif is_active is not None:
            base_where.append(Assignment.is_active == is_active)

        if is_overdue is not None:
            today = reference_date or today_in_app_timezone()
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
