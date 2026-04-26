import uuid
from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.masters import GradeMaster, Standard, Subject
from app.models.section import Section


class StandardRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: dict) -> Standard:
        obj = Standard(**data)
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def get_by_id(self, standard_id: uuid.UUID, school_id: uuid.UUID) -> Optional[Standard]:
        result = await self.db.execute(
            select(Standard).where(
                Standard.id == standard_id,
                Standard.school_id == school_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_level_and_year(
        self,
        school_id: uuid.UUID,
        level: int,
        academic_year_id: Optional[uuid.UUID],
    ) -> Optional[Standard]:
        result = await self.db.execute(
            select(Standard).where(
                Standard.school_id == school_id,
                Standard.level == level,
                Standard.academic_year_id == academic_year_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_school(
        self,
        school_id: uuid.UUID,
        academic_year_id: Optional[uuid.UUID] = None,
    ) -> tuple[list[Standard], int]:
        base = select(Standard).where(Standard.school_id == school_id)
        count_q = select(func.count(Standard.id)).where(Standard.school_id == school_id)

        if academic_year_id is not None:
            base = base.where(Standard.academic_year_id == academic_year_id)
            count_q = count_q.where(Standard.academic_year_id == academic_year_id)

        total = (await self.db.execute(count_q)).scalar_one()
        rows = await self.db.execute(base.order_by(Standard.level.asc(), Standard.name.asc()))
        return list(rows.scalars().all()), total

    async def update(self, obj: Standard, data: dict) -> Standard:
        for key, value in data.items():
            setattr(obj, key, value)
        await self.db.flush()
        return obj

    async def delete(self, obj: Standard) -> None:
        await self.db.delete(obj)


class SubjectRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: dict) -> Subject:
        obj = Subject(**data)
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def get_by_id(self, subject_id: uuid.UUID, school_id: uuid.UUID) -> Optional[Subject]:
        result = await self.db.execute(
            select(Subject).where(
                Subject.id == subject_id,
                Subject.school_id == school_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_code(self, school_id: uuid.UUID, code: str) -> Optional[Subject]:
        result = await self.db.execute(
            select(Subject).where(
                Subject.school_id == school_id,
                Subject.code == code,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_standard(
        self,
        school_id: uuid.UUID,
        standard_id: Optional[uuid.UUID] = None,
    ) -> tuple[list[Subject], int]:
        base = select(Subject).where(Subject.school_id == school_id)
        count_q = select(func.count(Subject.id)).where(Subject.school_id == school_id)

        if standard_id is not None:
            # Global subjects (standard_id=NULL) are available for all standards.
            base = base.where(or_(Subject.standard_id == standard_id, Subject.standard_id.is_(None)))
            count_q = count_q.where(or_(Subject.standard_id == standard_id, Subject.standard_id.is_(None)))

        total = (await self.db.execute(count_q)).scalar_one()
        rows = await self.db.execute(base.order_by(Subject.name.asc(), Subject.code.asc()))
        return list(rows.scalars().all()), total

    async def update(self, obj: Subject, data: dict) -> Subject:
        for key, value in data.items():
            setattr(obj, key, value)
        await self.db.flush()
        return obj

    async def delete(self, obj: Subject) -> None:
        await self.db.delete(obj)


class GradeMasterRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: dict) -> GradeMaster:
        obj = GradeMaster(**data)
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def get_by_id(self, grade_id: uuid.UUID, school_id: uuid.UUID) -> Optional[GradeMaster]:
        result = await self.db.execute(
            select(GradeMaster).where(
                GradeMaster.id == grade_id,
                GradeMaster.school_id == school_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_letter(self, school_id: uuid.UUID, grade_letter: str) -> Optional[GradeMaster]:
        result = await self.db.execute(
            select(GradeMaster).where(
                GradeMaster.school_id == school_id,
                GradeMaster.grade_letter == grade_letter,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_school(self, school_id: uuid.UUID) -> tuple[list[GradeMaster], int]:
        total = (
            await self.db.execute(
                select(func.count(GradeMaster.id)).where(GradeMaster.school_id == school_id)
            )
        ).scalar_one()
        rows = await self.db.execute(
            select(GradeMaster)
            .where(GradeMaster.school_id == school_id)
            .order_by(GradeMaster.max_percent.desc(), GradeMaster.grade_letter.asc())
        )
        return list(rows.scalars().all()), total

    async def lookup_by_percent(self, school_id: uuid.UUID, percent: float) -> Optional[GradeMaster]:
        result = await self.db.execute(
            select(GradeMaster).where(
                GradeMaster.school_id == school_id,
                GradeMaster.min_percent <= percent,
                GradeMaster.max_percent >= percent,
            )
        )
        return result.scalar_one_or_none()

    async def update(self, obj: GradeMaster, data: dict) -> GradeMaster:
        for key, value in data.items():
            setattr(obj, key, value)
        await self.db.flush()
        return obj

    async def delete(self, obj: GradeMaster) -> None:
        await self.db.delete(obj)


class SectionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: dict) -> Section:
        obj = Section(**data)
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def get_by_id(self, section_id: uuid.UUID, school_id: uuid.UUID) -> Optional[Section]:
        result = await self.db.execute(
            select(Section).where(
                Section.id == section_id,
                Section.school_id == school_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_key(
        self,
        school_id: uuid.UUID,
        standard_id: uuid.UUID,
        academic_year_id: uuid.UUID,
        name: str,
    ) -> Optional[Section]:
        result = await self.db.execute(
            select(Section).where(
                Section.school_id == school_id,
                Section.standard_id == standard_id,
                Section.academic_year_id == academic_year_id,
                Section.name == name,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_scope(
        self,
        school_id: uuid.UUID,
        standard_id: Optional[uuid.UUID] = None,
        academic_year_id: Optional[uuid.UUID] = None,
        include_inactive: bool = False,
    ) -> tuple[list[Section], int]:
        base = select(Section).where(Section.school_id == school_id)
        count_q = select(func.count(Section.id)).where(Section.school_id == school_id)

        if standard_id is not None:
            base = base.where(Section.standard_id == standard_id)
            count_q = count_q.where(Section.standard_id == standard_id)
        if academic_year_id is not None:
            base = base.where(Section.academic_year_id == academic_year_id)
            count_q = count_q.where(Section.academic_year_id == academic_year_id)
        if not include_inactive:
            base = base.where(Section.is_active.is_(True))
            count_q = count_q.where(Section.is_active.is_(True))

        total = (await self.db.execute(count_q)).scalar_one()
        rows = await self.db.execute(
            base.order_by(Section.academic_year_id.desc(), Section.standard_id.asc(), Section.name.asc())
        )
        return list(rows.scalars().all()), total

    async def update(self, obj: Section, data: dict) -> Section:
        for key, value in data.items():
            setattr(obj, key, value)
        await self.db.flush()
        return obj

    async def delete(self, obj: Section) -> None:
        await self.db.delete(obj)
