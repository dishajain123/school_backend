import uuid
from typing import Optional
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.assignment import Assignment
from app.models.student import Student
from app.models.submission import Submission


def _with_relations(stmt):
    return stmt.options(
        selectinload(Submission.student),
        selectinload(Submission.student).selectinload(Student.user),
        selectinload(Submission.performer),
        selectinload(Submission.assignment).selectinload(Assignment.standard),
        selectinload(Submission.assignment).selectinload(Assignment.subject),
    )


class SubmissionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: dict) -> Submission:
        obj = Submission(**data)
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def get_by_id(
        self, submission_id: uuid.UUID, school_id: uuid.UUID
    ) -> Optional[Submission]:
        result = await self.db.execute(
            _with_relations(
                select(Submission).where(
                    and_(
                        Submission.id == submission_id,
                        Submission.school_id == school_id,
                    )
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_existing(
        self, assignment_id: uuid.UUID, student_id: uuid.UUID
    ) -> Optional[Submission]:
        result = await self.db.execute(
            select(Submission).where(
                and_(
                    Submission.assignment_id == assignment_id,
                    Submission.student_id == student_id,
                )
            )
        )
        return result.scalar_one_or_none()

    async def list_by_assignment(
        self,
        assignment_id: uuid.UUID,
        school_id: uuid.UUID,
        student_id: Optional[uuid.UUID] = None,
        standard_id: Optional[uuid.UUID] = None,
        subject_id: Optional[uuid.UUID] = None,
        section: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Submission], int]:
        base_where = [Submission.assignment_id == assignment_id, Submission.school_id == school_id]
        if student_id:
            base_where.append(Submission.student_id == student_id)
        if section:
            base_where.append(Student.section == section)
        if standard_id:
            base_where.append(Assignment.standard_id == standard_id)
        if subject_id:
            base_where.append(Assignment.subject_id == subject_id)

        stmt = (
            select(Submission)
            .join(Assignment, Assignment.id == Submission.assignment_id)
            .join(Student, Student.id == Submission.student_id)
            .where(and_(*base_where))
        )
        count_q = (
            select(func.count(Submission.id))
            .select_from(Submission)
            .join(Assignment, Assignment.id == Submission.assignment_id)
            .join(Student, Student.id == Submission.student_id)
            .where(and_(*base_where))
        )

        total = (await self.db.execute(count_q)).scalar_one()
        offset = (page - 1) * page_size
        rows = await self.db.execute(
            _with_relations(
                stmt.order_by(Submission.submitted_at.desc())
                .offset(offset)
                .limit(page_size)
            )
        )
        return list(rows.scalars().all()), total

    async def list_by_assignment_for_students(
        self,
        assignment_id: uuid.UUID,
        school_id: uuid.UUID,
        student_ids: list[uuid.UUID],
    ) -> list[Submission]:
        """Used for PARENT scope — fetch submissions for multiple children."""
        if not student_ids:
            return []
        stmt = select(Submission).where(
            and_(
                Submission.assignment_id == assignment_id,
                Submission.school_id == school_id,
                Submission.student_id.in_(student_ids),
            )
        )
        rows = await self.db.execute(
            _with_relations(stmt.order_by(Submission.submitted_at.desc()))
        )
        return list(rows.scalars().all())

    async def update(self, submission: Submission, data: dict) -> Submission:
        for key, value in data.items():
            setattr(submission, key, value)
        await self.db.flush()
        await self.db.refresh(submission)
        return submission
