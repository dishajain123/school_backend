import uuid
from typing import Optional
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.teacher_class_subject import TeacherClassSubject


def _with_relations(stmt):
    return stmt.options(
        selectinload(TeacherClassSubject.teacher),
        selectinload(TeacherClassSubject.standard),
        selectinload(TeacherClassSubject.subject),
        selectinload(TeacherClassSubject.academic_year),
    )


class TeacherClassSubjectRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: dict) -> TeacherClassSubject:
        obj = TeacherClassSubject(**data)
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def get_by_id(
        self, assignment_id: uuid.UUID
    ) -> Optional[TeacherClassSubject]:
        result = await self.db.execute(
            _with_relations(
                select(TeacherClassSubject).where(
                    TeacherClassSubject.id == assignment_id
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_duplicate(
        self,
        teacher_id: uuid.UUID,
        standard_id: uuid.UUID,
        section: str,
        subject_id: uuid.UUID,
        academic_year_id: uuid.UUID,
    ) -> Optional[TeacherClassSubject]:
        result = await self.db.execute(
            select(TeacherClassSubject).where(
                and_(
                    TeacherClassSubject.teacher_id == teacher_id,
                    TeacherClassSubject.standard_id == standard_id,
                    TeacherClassSubject.section == section,
                    TeacherClassSubject.subject_id == subject_id,
                    TeacherClassSubject.academic_year_id == academic_year_id,
                )
            )
        )
        return result.scalar_one_or_none()

    async def list_by_teacher(
        self,
        teacher_id: uuid.UUID,
        academic_year_id: Optional[uuid.UUID] = None,
    ) -> tuple[list[TeacherClassSubject], int]:
        stmt = select(TeacherClassSubject).where(
            TeacherClassSubject.teacher_id == teacher_id
        )
        count_q = select(func.count(TeacherClassSubject.id)).where(
            TeacherClassSubject.teacher_id == teacher_id
        )

        if academic_year_id is not None:
            stmt = stmt.where(TeacherClassSubject.academic_year_id == academic_year_id)
            count_q = count_q.where(TeacherClassSubject.academic_year_id == academic_year_id)

        total = (await self.db.execute(count_q)).scalar_one()
        rows = await self.db.execute(
            _with_relations(stmt.order_by(TeacherClassSubject.created_at.desc()))
        )
        return list(rows.scalars().all()), total

    async def list_by_class(
        self,
        standard_id: uuid.UUID,
        section: str,
        academic_year_id: Optional[uuid.UUID] = None,
    ) -> tuple[list[TeacherClassSubject], int]:
        stmt = select(TeacherClassSubject).where(
            and_(
                TeacherClassSubject.standard_id == standard_id,
                TeacherClassSubject.section == section,
            )
        )
        count_q = select(func.count(TeacherClassSubject.id)).where(
            and_(
                TeacherClassSubject.standard_id == standard_id,
                TeacherClassSubject.section == section,
            )
        )

        if academic_year_id is not None:
            stmt = stmt.where(TeacherClassSubject.academic_year_id == academic_year_id)
            count_q = count_q.where(TeacherClassSubject.academic_year_id == academic_year_id)

        total = (await self.db.execute(count_q)).scalar_one()
        rows = await self.db.execute(
            _with_relations(stmt.order_by(TeacherClassSubject.created_at.desc()))
        )
        return list(rows.scalars().all()), total

    async def find_assignment(
        self,
        teacher_id: uuid.UUID,
        standard_id: uuid.UUID,
        subject_id: uuid.UUID,
        academic_year_id: uuid.UUID,
    ) -> Optional[TeacherClassSubject]:
        """Used by service helper assert_teacher_owns_class_subject."""
        result = await self.db.execute(
            select(TeacherClassSubject).where(
                and_(
                    TeacherClassSubject.teacher_id == teacher_id,
                    TeacherClassSubject.standard_id == standard_id,
                    TeacherClassSubject.subject_id == subject_id,
                    TeacherClassSubject.academic_year_id == academic_year_id,
                )
            )
        )
        return result.scalar_one_or_none()

    async def find_assignment_with_section(
        self,
        teacher_id: uuid.UUID,
        standard_id: uuid.UUID,
        section: str,
        subject_id: uuid.UUID,
        academic_year_id: uuid.UUID,
    ) -> Optional[TeacherClassSubject]:
        """Strict lookup including section — used where section matters."""
        result = await self.db.execute(
            select(TeacherClassSubject).where(
                and_(
                    TeacherClassSubject.teacher_id == teacher_id,
                    TeacherClassSubject.standard_id == standard_id,
                    TeacherClassSubject.section == section,
                    TeacherClassSubject.subject_id == subject_id,
                    TeacherClassSubject.academic_year_id == academic_year_id,
                )
            )
        )
        return result.scalar_one_or_none()

    async def delete(self, obj: TeacherClassSubject) -> None:
        await self.db.delete(obj)
        await self.db.flush()