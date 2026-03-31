import uuid
from typing import Optional
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.teacher import Teacher


class TeacherRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: dict) -> Teacher:
        teacher = Teacher(**data)
        self.db.add(teacher)
        await self.db.flush()
        await self.db.refresh(teacher)
        return teacher

    async def get_by_id(
        self,
        teacher_id: uuid.UUID,
        school_id: uuid.UUID,
    ) -> Optional[Teacher]:
        result = await self.db.execute(
            select(Teacher)
            .options(selectinload(Teacher.user))
            .where(
                Teacher.id == teacher_id,
                Teacher.school_id == school_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_user_id(self, user_id: uuid.UUID) -> Optional[Teacher]:
        result = await self.db.execute(
            select(Teacher)
            .options(selectinload(Teacher.user))
            .where(Teacher.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_by_employee_code(self, employee_code: str) -> Optional[Teacher]:
        result = await self.db.execute(
            select(Teacher).where(Teacher.employee_code == employee_code)
        )
        return result.scalar_one_or_none()

    async def list_by_school(
        self,
        school_id: uuid.UUID,
        academic_year_id: Optional[uuid.UUID] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Teacher], int]:
        base = select(Teacher).where(Teacher.school_id == school_id)
        count_q = select(func.count(Teacher.id)).where(Teacher.school_id == school_id)

        if academic_year_id is not None:
            base = base.where(Teacher.academic_year_id == academic_year_id)
            count_q = count_q.where(Teacher.academic_year_id == academic_year_id)

        total = (await self.db.execute(count_q)).scalar_one()

        offset = (page - 1) * page_size
        rows = await self.db.execute(
            base.options(selectinload(Teacher.user))
            .order_by(Teacher.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        return list(rows.scalars().all()), total

    async def update(self, teacher: Teacher, data: dict) -> Teacher:
        for key, value in data.items():
            setattr(teacher, key, value)
        await self.db.flush()
        await self.db.refresh(teacher)
        return teacher