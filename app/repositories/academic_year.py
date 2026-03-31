import uuid
from typing import Optional
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.academic_year import AcademicYear


class AcademicYearRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: dict) -> AcademicYear:
        year = AcademicYear(**data)
        self.db.add(year)
        await self.db.flush()
        await self.db.refresh(year)
        return year

    async def get_by_id(self, year_id: uuid.UUID, school_id: uuid.UUID) -> Optional[AcademicYear]:
        result = await self.db.execute(
            select(AcademicYear).where(
                AcademicYear.id == year_id,
                AcademicYear.school_id == school_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_name(self, name: str, school_id: uuid.UUID) -> Optional[AcademicYear]:
        result = await self.db.execute(
            select(AcademicYear).where(
                AcademicYear.name == name,
                AcademicYear.school_id == school_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_active(self, school_id: uuid.UUID) -> Optional[AcademicYear]:
        result = await self.db.execute(
            select(AcademicYear).where(
                AcademicYear.school_id == school_id,
                AcademicYear.is_active == True,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_school(self, school_id: uuid.UUID) -> tuple[list[AcademicYear], int]:
        query = (
            select(AcademicYear)
            .where(AcademicYear.school_id == school_id)
            .order_by(AcademicYear.start_date.desc())
        )
        count_query = select(func.count(AcademicYear.id)).where(
            AcademicYear.school_id == school_id
        )

        total_result = await self.db.execute(count_query)
        total = total_result.scalar_one()

        result = await self.db.execute(query)
        years = list(result.scalars().all())
        return years, total

    async def deactivate_all(self, school_id: uuid.UUID) -> None:
        await self.db.execute(
            update(AcademicYear)
            .where(
                AcademicYear.school_id == school_id,
                AcademicYear.is_active == True,
            )
            .values(is_active=False)
        )
        await self.db.flush()

    async def activate(self, year: AcademicYear) -> AcademicYear:
        year.is_active = True
        await self.db.flush()
        await self.db.refresh(year)
        return year

    async def update(self, year: AcademicYear, data: dict) -> AcademicYear:
        for key, value in data.items():
            if value is not None:
                setattr(year, key, value)
        await self.db.flush()
        await self.db.refresh(year)
        return year