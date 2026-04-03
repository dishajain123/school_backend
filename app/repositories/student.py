import uuid
import math
from typing import Optional
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.student import Student


class StudentRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: dict) -> Student:
        student = Student(**data)
        self.db.add(student)
        await self.db.flush()
        await self.db.refresh(student)
        return student

    async def get_by_id(self, student_id: uuid.UUID, school_id: uuid.UUID) -> Optional[Student]:
        result = await self.db.execute(
            select(Student).where(
                Student.id == student_id,
                Student.school_id == school_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_id_only(self, student_id: uuid.UUID) -> Optional[Student]:
        result = await self.db.execute(
            select(Student).where(Student.id == student_id)
        )
        return result.scalar_one_or_none()

    async def get_by_user_id(self, user_id: uuid.UUID) -> Optional[Student]:
        result = await self.db.execute(
            select(Student).where(Student.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_by_admission_number(
        self, admission_number: str, school_id: uuid.UUID
    ) -> Optional[Student]:
        result = await self.db.execute(
            select(Student).where(
                Student.admission_number == admission_number,
                Student.school_id == school_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_school(
        self,
        school_id: uuid.UUID,
        standard_id: Optional[uuid.UUID] = None,
        section: Optional[str] = None,
        academic_year_id: Optional[uuid.UUID] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Student], int]:
        query = select(Student).where(Student.school_id == school_id)
        count_query = select(func.count(Student.id)).where(Student.school_id == school_id)

        if standard_id is not None:
            query = query.where(Student.standard_id == standard_id)
            count_query = count_query.where(Student.standard_id == standard_id)

        if section is not None:
            query = query.where(Student.section == section)
            count_query = count_query.where(Student.section == section)

        if academic_year_id is not None:
            query = query.where(Student.academic_year_id == academic_year_id)
            count_query = count_query.where(Student.academic_year_id == academic_year_id)

        total_result = await self.db.execute(count_query)
        total = total_result.scalar_one()

        offset = (page - 1) * page_size
        query = query.order_by(Student.created_at.desc()).offset(offset).limit(page_size)
        result = await self.db.execute(query)
        return list(result.scalars().all()), total

    async def list_by_parent(self, parent_id: uuid.UUID, school_id: uuid.UUID) -> list[Student]:
        result = await self.db.execute(
            select(Student).where(
                Student.parent_id == parent_id,
                Student.school_id == school_id,
            ).order_by(Student.created_at.asc())
        )
        return list(result.scalars().all())

    async def list_by_standard(
        self,
        standard_id: uuid.UUID,
        school_id: uuid.UUID,
        section: Optional[str] = None,
    ) -> list[Student]:
        query = select(Student).where(
            Student.standard_id == standard_id,
            Student.school_id == school_id,
        )
        if section:
            query = query.where(Student.section == section)
        result = await self.db.execute(query.order_by(Student.roll_number.asc()))
        return list(result.scalars().all())

    async def list_sections_by_school(
        self,
        school_id: uuid.UUID,
        standard_id: Optional[uuid.UUID] = None,
        academic_year_id: Optional[uuid.UUID] = None,
    ) -> list[str]:
        query = select(Student.section).where(
            Student.school_id == school_id,
            Student.section.is_not(None),
            Student.section != "",
        )

        if standard_id is not None:
            query = query.where(Student.standard_id == standard_id)

        if academic_year_id is not None:
            query = query.where(Student.academic_year_id == academic_year_id)

        query = query.distinct().order_by(func.lower(Student.section))
        result = await self.db.execute(query)
        return [row[0].strip() for row in result.all() if row[0] and row[0].strip()]

    async def update(self, student: Student, data: dict) -> Student:
        for key, value in data.items():
            setattr(student, key, value)
        await self.db.flush()
        await self.db.refresh(student)
        return student

    async def update_promotion_status(
        self, student_id: uuid.UUID, is_promoted: bool
    ) -> None:
        await self.db.execute(
            update(Student)
            .where(Student.id == student_id)
            .values(is_promoted=is_promoted)
        )
        await self.db.flush()
