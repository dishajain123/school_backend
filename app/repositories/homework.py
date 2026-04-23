import uuid
from datetime import date
from typing import Optional

from sqlalchemy import select, func, and_, exists
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.homework import Homework
from app.models.homework_submission import HomeworkSubmission


def _with_relations(stmt):
    return stmt.options(
        selectinload(Homework.teacher),
        selectinload(Homework.standard),
        selectinload(Homework.subject),
        selectinload(Homework.academic_year),
    )


class HomeworkRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: dict) -> Homework:
        obj = Homework(**data)
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def get_by_id(
        self, homework_id: uuid.UUID, school_id: uuid.UUID
    ) -> Optional[Homework]:
        result = await self.db.execute(
            _with_relations(
                select(Homework).where(
                    and_(
                        Homework.id == homework_id,
                        Homework.school_id == school_id,
                    )
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_duplicate(
        self,
        school_id: uuid.UUID,
        standard_id: uuid.UUID,
        subject_id: uuid.UUID,
        record_date: date,
        academic_year_id: uuid.UUID,
    ) -> Optional[Homework]:
        result = await self.db.execute(
            select(Homework).where(
                and_(
                    Homework.school_id == school_id,
                    Homework.standard_id == standard_id,
                    Homework.subject_id == subject_id,
                    Homework.date == record_date,
                    Homework.academic_year_id == academic_year_id,
                )
            )
        )
        return result.scalar_one_or_none()

    async def list_by_school(
        self,
        school_id: uuid.UUID,
        standard_id: Optional[uuid.UUID] = None,
        standard_ids: Optional[list[uuid.UUID]] = None,
        subject_id: Optional[uuid.UUID] = None,
        record_date: Optional[date] = None,
        academic_year_id: Optional[uuid.UUID] = None,
        teacher_id: Optional[uuid.UUID] = None,
        is_submitted: Optional[bool] = None,
        submission_student_ids: Optional[list[uuid.UUID]] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Homework], int]:
        base_where = [Homework.school_id == school_id]

        if standard_ids is not None:
            if not standard_ids:
                return [], 0
            base_where.append(Homework.standard_id.in_(standard_ids))
        elif standard_id:
            base_where.append(Homework.standard_id == standard_id)

        if subject_id:
            base_where.append(Homework.subject_id == subject_id)
        if record_date:
            base_where.append(Homework.date == record_date)
        if academic_year_id:
            base_where.append(Homework.academic_year_id == academic_year_id)
        if teacher_id:
            base_where.append(Homework.teacher_id == teacher_id)
        if is_submitted is not None:
            sub_where = [
                HomeworkSubmission.homework_id == Homework.id,
                HomeworkSubmission.school_id == school_id,
            ]
            if submission_student_ids is not None:
                if not submission_student_ids:
                    return ([], 0) if is_submitted else await self.list_by_school(
                        school_id=school_id,
                        standard_id=standard_id,
                        standard_ids=standard_ids,
                        subject_id=subject_id,
                        record_date=record_date,
                        academic_year_id=academic_year_id,
                        teacher_id=teacher_id,
                        is_submitted=None,
                        submission_student_ids=None,
                        page=page,
                        page_size=page_size,
                    )
                sub_where.append(
                    HomeworkSubmission.student_id.in_(submission_student_ids)
                )
            submission_exists = exists(
                select(HomeworkSubmission.id).where(and_(*sub_where))
            )
            base_where.append(submission_exists if is_submitted else ~submission_exists)

        stmt = select(Homework).where(and_(*base_where))
        count_q = select(func.count(Homework.id)).where(and_(*base_where))

        total = (await self.db.execute(count_q)).scalar_one()
        offset = (page - 1) * page_size
        rows = await self.db.execute(
            _with_relations(
                stmt.order_by(Homework.date.desc(), Homework.created_at.desc())
                .offset(offset)
                .limit(page_size)
            )
        )
        return list(rows.scalars().all()), total
