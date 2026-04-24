import uuid
from datetime import date
from typing import Optional

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.student_diary import StudentDiary
from app.models.teacher import Teacher


def _with_relations(stmt):
    return stmt.options(
        selectinload(StudentDiary.teacher),
        selectinload(StudentDiary.teacher).selectinload(Teacher.user),
        selectinload(StudentDiary.standard),
        selectinload(StudentDiary.subject),
        selectinload(StudentDiary.academic_year),
    )


class DiaryRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: dict) -> StudentDiary:
        obj = StudentDiary(**data)
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def get_by_id(
        self, diary_id: uuid.UUID, school_id: uuid.UUID
    ) -> Optional[StudentDiary]:
        result = await self.db.execute(
            _with_relations(
                select(StudentDiary).where(
                    and_(
                        StudentDiary.id == diary_id,
                        StudentDiary.school_id == school_id,
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
    ) -> Optional[StudentDiary]:
        result = await self.db.execute(
            select(StudentDiary).where(
                and_(
                    StudentDiary.school_id == school_id,
                    StudentDiary.standard_id == standard_id,
                    StudentDiary.subject_id == subject_id,
                    StudentDiary.date == record_date,
                    StudentDiary.academic_year_id == academic_year_id,
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
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[StudentDiary], int]:
        base_where = [StudentDiary.school_id == school_id]

        if standard_ids is not None:
            if not standard_ids:
                return [], 0
            base_where.append(StudentDiary.standard_id.in_(standard_ids))
        elif standard_id:
            base_where.append(StudentDiary.standard_id == standard_id)

        if subject_id:
            base_where.append(StudentDiary.subject_id == subject_id)
        if record_date:
            base_where.append(StudentDiary.date == record_date)
        if academic_year_id:
            base_where.append(StudentDiary.academic_year_id == academic_year_id)
        if teacher_id:
            base_where.append(StudentDiary.teacher_id == teacher_id)

        stmt = select(StudentDiary).where(and_(*base_where))
        count_q = select(func.count(StudentDiary.id)).where(and_(*base_where))

        total = (await self.db.execute(count_q)).scalar_one()
        offset = (page - 1) * page_size
        rows = await self.db.execute(
            _with_relations(
                stmt.order_by(StudentDiary.date.desc(), StudentDiary.created_at.desc())
                .offset(offset)
                .limit(page_size)
            )
        )
        return list(rows.scalars().all()), total
