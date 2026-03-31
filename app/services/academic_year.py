import uuid
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.academic_year import AcademicYearRepository
from app.schemas.academic_year import AcademicYearCreate, AcademicYearUpdate
from app.models.academic_year import AcademicYear
from app.core.exceptions import NotFoundException, ConflictException, ValidationException


class AcademicYearService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = AcademicYearRepository(db)

    async def create_academic_year(
        self, data: AcademicYearCreate, school_id: uuid.UUID
    ) -> AcademicYear:
        existing = await self.repo.get_by_name(data.name, school_id)
        if existing:
            raise ConflictException(
                f"Academic year '{data.name}' already exists for this school"
            )

        year = await self.repo.create(
            {
                "name": data.name,
                "start_date": data.start_date,
                "end_date": data.end_date,
                "is_active": False,
                "school_id": school_id,
            }
        )
        return year

    async def get_academic_year(
        self, year_id: uuid.UUID, school_id: uuid.UUID
    ) -> AcademicYear:
        year = await self.repo.get_by_id(year_id, school_id)
        if not year:
            raise NotFoundException("Academic year")
        return year

    async def list_academic_years(
        self, school_id: uuid.UUID
    ) -> tuple[list[AcademicYear], int]:
        return await self.repo.list_by_school(school_id)

    async def activate_academic_year(
        self, year_id: uuid.UUID, school_id: uuid.UUID
    ) -> AcademicYear:
        year = await self.repo.get_by_id(year_id, school_id)
        if not year:
            raise NotFoundException("Academic year")

        if year.is_active:
            raise ConflictException("Academic year is already active")

        # Atomically deactivate all others then activate this one
        await self.repo.deactivate_all(school_id)
        activated = await self.repo.activate(year)
        return activated

    async def update_academic_year(
        self, year_id: uuid.UUID, school_id: uuid.UUID, data: AcademicYearUpdate
    ) -> AcademicYear:
        year = await self.repo.get_by_id(year_id, school_id)
        if not year:
            raise NotFoundException("Academic year")

        update_data = data.model_dump(exclude_none=True)

        if "name" in update_data and update_data["name"] != year.name:
            existing = await self.repo.get_by_name(update_data["name"], school_id)
            if existing:
                raise ConflictException(
                    f"Academic year '{update_data['name']}' already exists for this school"
                )

        start = update_data.get("start_date", year.start_date)
        end = update_data.get("end_date", year.end_date)
        if end <= start:
            raise ValidationException("end_date must be after start_date")

        return await self.repo.update(year, update_data)


async def get_active_year(school_id: uuid.UUID, db: AsyncSession) -> AcademicYear:
    """
    Reusable dependency helper — fetches the currently active academic year
    for a school. Raises 404 if none is active.
    Used by Attendance, Assignments, Homework, Results, and other modules.
    """
    repo = AcademicYearRepository(db)
    year = await repo.get_active(school_id)
    if not year:
        raise NotFoundException(
            "No active academic year found for this school. "
            "Please activate an academic year before proceeding."
        )
    return year