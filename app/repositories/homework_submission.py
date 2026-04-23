import uuid
from typing import Optional

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.homework_submission import HomeworkSubmission
from app.models.student import Student
from app.models.parent import Parent


def _with_relations(stmt):
    return stmt.options(
        selectinload(HomeworkSubmission.student).selectinload(Student.user),
        selectinload(HomeworkSubmission.performer),
        selectinload(HomeworkSubmission.reviewer),
    )


class HomeworkSubmissionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: dict) -> HomeworkSubmission:
        obj = HomeworkSubmission(**data)
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def get_by_id(
        self,
        submission_id: uuid.UUID,
        school_id: uuid.UUID,
    ) -> Optional[HomeworkSubmission]:
        result = await self.db.execute(
            _with_relations(
                select(HomeworkSubmission).where(
                    and_(
                        HomeworkSubmission.id == submission_id,
                        HomeworkSubmission.school_id == school_id,
                    )
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_existing(
        self,
        homework_id: uuid.UUID,
        student_id: uuid.UUID,
        school_id: uuid.UUID,
    ) -> Optional[HomeworkSubmission]:
        result = await self.db.execute(
            select(HomeworkSubmission).where(
                and_(
                    HomeworkSubmission.homework_id == homework_id,
                    HomeworkSubmission.student_id == student_id,
                    HomeworkSubmission.school_id == school_id,
                )
            )
        )
        return result.scalar_one_or_none()

    async def list_by_homework(
        self,
        homework_id: uuid.UUID,
        school_id: uuid.UUID,
        student_id: Optional[uuid.UUID] = None,
        parent_id: Optional[uuid.UUID] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[HomeworkSubmission], int]:
        base = [
            HomeworkSubmission.homework_id == homework_id,
            HomeworkSubmission.school_id == school_id,
        ]

        stmt = select(HomeworkSubmission).join(
            Student,
            Student.id == HomeworkSubmission.student_id,
        )
        count_q = select(func.count(HomeworkSubmission.id)).select_from(
            HomeworkSubmission
        ).join(Student, Student.id == HomeworkSubmission.student_id)

        if student_id is not None:
            base.append(HomeworkSubmission.student_id == student_id)
        if parent_id is not None:
            base.append(Student.parent_id == parent_id)

        stmt = stmt.where(and_(*base))
        count_q = count_q.where(and_(*base))

        total = (await self.db.execute(count_q)).scalar_one()
        offset = (page - 1) * page_size
        rows = await self.db.execute(
            _with_relations(
                stmt.order_by(
                    HomeworkSubmission.created_at.desc(),
                )
                .offset(offset)
                .limit(page_size)
            )
        )
        return list(rows.scalars().all()), total

    async def update(
        self,
        submission: HomeworkSubmission,
        data: dict,
    ) -> HomeworkSubmission:
        for key, value in data.items():
            setattr(submission, key, value)
        await self.db.flush()
        await self.db.refresh(submission)
        return submission
