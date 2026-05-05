import uuid
from typing import Optional

from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.timetable import Timetable


def _with_relations(stmt):
    return stmt.options(
        selectinload(Timetable.standard),
        selectinload(Timetable.academic_year),
        selectinload(Timetable.uploader),
    )


class TimetableRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: dict) -> Timetable:
        obj = Timetable(**data)
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def get_by_standard(
        self,
        school_id: uuid.UUID,
        standard_id: uuid.UUID,
        academic_year_id: uuid.UUID,
        section: Optional[str] = None,
        exam_id: Optional[uuid.UUID] = None,
    ) -> Optional[Timetable]:
        conditions = [
            Timetable.school_id == school_id,
            Timetable.standard_id == standard_id,
            Timetable.academic_year_id == academic_year_id,
        ]
        if section is not None:
            conditions.append(Timetable.section == section)
        else:
            conditions.append(Timetable.section.is_(None))

        if exam_id is not None:
            conditions.append(Timetable.exam_id == exam_id)
        else:
            conditions.append(Timetable.exam_id.is_(None))

        result = await self.db.execute(
            _with_relations(
                select(Timetable).where(and_(*conditions))
            )
        )
        return result.scalar_one_or_none()

    async def get_by_standard_with_section_fallback(
        self,
        school_id: uuid.UUID,
        standard_id: uuid.UUID,
        academic_year_id: uuid.UUID,
        section: Optional[str],
        exam_id: Optional[uuid.UUID],
    ) -> Optional[Timetable]:
        """
        Prefer section-specific timetable rows; if missing, use class-wide rows
        (section NULL) so uploads that omit section match students/parents in any section.

        When [exam_id] is set (exam schedule context) but no exam-specific row exists,
        fall back to the class timetable row (exam_id NULL) — the usual upload path
        for "Upload Timetable" without exam mode.
        """
        row = await self.get_by_standard(
            school_id=school_id,
            standard_id=standard_id,
            academic_year_id=academic_year_id,
            section=section,
            exam_id=exam_id,
        )
        if row is not None:
            return row
        if section is not None:
            row = await self.get_by_standard(
                school_id=school_id,
                standard_id=standard_id,
                academic_year_id=academic_year_id,
                section=None,
                exam_id=exam_id,
            )
            if row is not None:
                return row

        if exam_id is not None:
            row = await self.get_by_standard(
                school_id=school_id,
                standard_id=standard_id,
                academic_year_id=academic_year_id,
                section=section,
                exam_id=None,
            )
            if row is not None:
                return row
            if section is not None:
                return await self.get_by_standard(
                    school_id=school_id,
                    standard_id=standard_id,
                    academic_year_id=academic_year_id,
                    section=None,
                    exam_id=None,
                )
        return None

    async def update(self, timetable: Timetable, data: dict) -> Timetable:
        for key, value in data.items():
            setattr(timetable, key, value)
        await self.db.flush()
        await self.db.refresh(timetable)
        return timetable

    async def delete(self, timetable: Timetable) -> None:
        await self.db.delete(timetable)
        await self.db.flush()

    async def list_sections_by_standard(
        self,
        school_id: uuid.UUID,
        standard_id: uuid.UUID,
        academic_year_id: uuid.UUID,
    ) -> list[str]:
        section_expr = func.trim(Timetable.section)
        result = await self.db.execute(
            select(section_expr.label("section"))
            .where(
                Timetable.school_id == school_id,
                Timetable.standard_id == standard_id,
                Timetable.academic_year_id == academic_year_id,
                Timetable.exam_id.is_(None),
                Timetable.section.is_not(None),
                section_expr != "",
            )
            .group_by(section_expr)
            .order_by(func.lower(section_expr))
        )
        return [row[0] for row in result.all() if row[0]]
