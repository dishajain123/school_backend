import uuid
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.school import SchoolRepository
from app.schemas.school import SchoolCreate, SchoolUpdate
from app.models.school import School
from app.core.exceptions import NotFoundException, ConflictException


class SchoolService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = SchoolRepository(db)

    async def create_school(self, data: SchoolCreate) -> School:
        existing = await self.repo.get_by_email(data.contact_email)
        if existing:
            raise ConflictException(f"School with email '{data.contact_email}' already exists")

        school = await self.repo.create(data.model_dump())
        return school

    async def get_school(self, school_id: uuid.UUID) -> School:
        school = await self.repo.get_by_id(school_id)
        if not school:
            raise NotFoundException("School")
        return school

    async def list_schools(
        self,
        page: int = 1,
        page_size: int = 20,
        is_active: Optional[bool] = None,
    ) -> tuple[list[School], int]:
        return await self.repo.list_all(page=page, page_size=page_size, is_active=is_active)

    async def update_school(self, school_id: uuid.UUID, data: SchoolUpdate) -> School:
        school = await self.get_school(school_id)

        update_data = data.model_dump(exclude_none=True)
        if "contact_email" in update_data and update_data["contact_email"] != school.contact_email:
            existing = await self.repo.get_by_email(update_data["contact_email"])
            if existing:
                raise ConflictException(f"Email '{update_data['contact_email']}' is already in use")

        return await self.repo.update(school, update_data)

    async def deactivate_school(self, school_id: uuid.UUID) -> School:
        school = await self.get_school(school_id)
        if not school.is_active:
            raise ConflictException("School is already deactivated")
        return await self.repo.deactivate(school)