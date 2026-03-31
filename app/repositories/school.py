import uuid
from typing import Optional
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.school import School


class SchoolRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: dict) -> School:
        school = School(**data)
        self.db.add(school)
        await self.db.flush()
        await self.db.refresh(school)
        return school

    async def get_by_id(self, school_id: uuid.UUID) -> Optional[School]:
        result = await self.db.execute(
            select(School).where(School.id == school_id)
        )
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> Optional[School]:
        result = await self.db.execute(
            select(School).where(School.contact_email == email)
        )
        return result.scalar_one_or_none()

    async def list_all(
        self,
        page: int = 1,
        page_size: int = 20,
        is_active: Optional[bool] = None,
    ) -> tuple[list[School], int]:
        query = select(School)
        count_query = select(func.count(School.id))

        if is_active is not None:
            query = query.where(School.is_active == is_active)
            count_query = count_query.where(School.is_active == is_active)

        total_result = await self.db.execute(count_query)
        total = total_result.scalar_one()

        offset = (page - 1) * page_size
        query = query.order_by(School.created_at.desc()).offset(offset).limit(page_size)
        result = await self.db.execute(query)
        schools = list(result.scalars().all())

        return schools, total

    async def update(self, school: School, data: dict) -> School:
        for key, value in data.items():
            if value is not None:
                setattr(school, key, value)
        await self.db.flush()
        await self.db.refresh(school)
        return school

    async def deactivate(self, school: School) -> School:
        school.is_active = False
        await self.db.flush()
        await self.db.refresh(school)
        return school