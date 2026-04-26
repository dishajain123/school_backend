import uuid
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.student import Student
from app.models.student_year_mapping import StudentYearMapping
from app.utils.enums import EnrollmentStatus


def _with_relations(stmt):
    return stmt.options(
        selectinload(StudentYearMapping.student).selectinload(Student.user),
        selectinload(StudentYearMapping.standard),
        selectinload(StudentYearMapping.section),
        selectinload(StudentYearMapping.academic_year),
    )


class EnrollmentRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, mapping_id: uuid.UUID) -> Optional[StudentYearMapping]:
        result = await self.db.execute(
            _with_relations(
                select(StudentYearMapping).where(StudentYearMapping.id == mapping_id)
            )
        )
        return result.scalar_one_or_none()

    async def get_by_student_year(
        self, student_id: uuid.UUID, academic_year_id: uuid.UUID
    ) -> Optional[StudentYearMapping]:
        result = await self.db.execute(
            _with_relations(
                select(StudentYearMapping).where(
                    StudentYearMapping.student_id == student_id,
                    StudentYearMapping.academic_year_id == academic_year_id,
                )
            )
        )
        return result.scalar_one_or_none()

    async def count_active_in_section(
        self, section_id: uuid.UUID, academic_year_id: uuid.UUID
    ) -> int:
        result = await self.db.execute(
            select(func.count(StudentYearMapping.id)).where(
                StudentYearMapping.section_id == section_id,
                StudentYearMapping.academic_year_id == academic_year_id,
                StudentYearMapping.status == EnrollmentStatus.ACTIVE,
            )
        )
        return int(result.scalar_one() or 0)

    async def list_for_roster(
        self,
        school_id: uuid.UUID,
        standard_id: uuid.UUID,
        section_id: Optional[uuid.UUID],
        academic_year_id: uuid.UUID,
        status_filter: Optional[EnrollmentStatus] = None,
    ) -> list[StudentYearMapping]:
        stmt = select(StudentYearMapping).where(
            StudentYearMapping.school_id == school_id,
            StudentYearMapping.standard_id == standard_id,
            StudentYearMapping.academic_year_id == academic_year_id,
        )
        if section_id is not None:
            stmt = stmt.where(StudentYearMapping.section_id == section_id)
        if status_filter is not None:
            stmt = stmt.where(StudentYearMapping.status == status_filter)

        stmt = stmt.order_by(
            StudentYearMapping.roll_number.asc().nullslast(),
            StudentYearMapping.created_at.asc(),
        )
        result = await self.db.execute(_with_relations(stmt))
        return list(result.scalars().all())
