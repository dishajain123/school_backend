import uuid
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.academic_year import AcademicYearRepository
from app.repositories.masters import (
    GradeMasterRepository,
    SectionRepository,
    StandardRepository,
    SubjectRepository,
)
from app.schemas.masters import (
    GradeMasterCreate,
    GradeMasterUpdate,
    SectionCreate,
    SectionUpdate,
    StandardCreate,
    StandardUpdate,
    SubjectCreate,
    SubjectUpdate,
)
from app.models.masters import GradeMaster, Standard, Subject
from app.models.section import Section
from app.core.exceptions import (
    NotFoundException,
    ValidationException,
    ConflictException,
)
from app.services.academic_year import get_active_year


class MastersService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.std_repo = StandardRepository(db)
        self.sub_repo = SubjectRepository(db)
        self.grade_repo = GradeMasterRepository(db)
        self.section_repo = SectionRepository(db)
        self.year_repo = AcademicYearRepository(db)

    # ── Standards ─────────────────────────────────────────────────────────────

    async def create_standard(
        self,
        payload: StandardCreate,
        school_id: uuid.UUID,
    ) -> Standard:
        # Academic structure must be anchored to a concrete year.
        if payload.academic_year_id is None:
            payload = payload.model_copy(
                update={"academic_year_id": (await get_active_year(school_id, self.db)).id}
            )

        year = await self.year_repo.get_by_id(payload.academic_year_id, school_id)
        if not year:
            raise NotFoundException(detail="Academic year not found in this school")

        existing = await self.std_repo.get_by_level_and_year(
            school_id, payload.level, payload.academic_year_id
        )
        if existing:
            raise ConflictException(
                detail=f"A standard at level {payload.level} already exists for this academic year"
            )

        obj = await self.std_repo.create(
            {
                "school_id": school_id,
                "name": payload.name,
                "level": payload.level,
                "academic_year_id": payload.academic_year_id,
            }
        )
        await self.db.commit()
        await self.db.refresh(obj)
        return obj

    async def list_standards(
        self,
        school_id: uuid.UUID,
        academic_year_id: Optional[uuid.UUID],
    ) -> tuple[list[Standard], int]:
        return await self.std_repo.list_by_school(school_id, academic_year_id)

    async def update_standard(
        self,
        standard_id: uuid.UUID,
        payload: StandardUpdate,
        school_id: uuid.UUID,
    ) -> Standard:
        obj = await self.std_repo.get_by_id(standard_id, school_id)
        if not obj:
            raise NotFoundException(detail="Standard not found")

        update_data = payload.model_dump(exclude_unset=True)

        new_level = update_data.get("level", obj.level)
        new_year = update_data.get("academic_year_id", obj.academic_year_id)
        if new_level != obj.level or new_year != obj.academic_year_id:
            conflict = await self.std_repo.get_by_level_and_year(school_id, new_level, new_year)
            if conflict and conflict.id != standard_id:
                raise ConflictException(
                    detail=f"A standard at level {new_level} already exists for this academic year"
                )

        updated = await self.std_repo.update(obj, update_data)
        await self.db.commit()
        await self.db.refresh(updated)
        return updated

    async def delete_standard(self, standard_id: uuid.UUID, school_id: uuid.UUID) -> None:
        obj = await self.std_repo.get_by_id(standard_id, school_id)
        if not obj:
            raise NotFoundException(detail="Standard not found")
        await self.std_repo.delete(obj)
        await self.db.commit()

    # ── Subjects ──────────────────────────────────────────────────────────────

    async def create_subject(
        self,
        payload: SubjectCreate,
        school_id: uuid.UUID,
    ) -> Subject:
        # Optional class mapping: subject master can be global when standard_id is omitted.
        if payload.standard_id is not None:
            standard = await self.std_repo.get_by_id(payload.standard_id, school_id)
            if not standard:
                raise NotFoundException(detail="Standard not found")

        existing = await self.sub_repo.get_by_code(school_id, payload.code)
        if existing:
            raise ConflictException(detail=f"Subject code '{payload.code}' already exists in this school")

        obj = await self.sub_repo.create(
            {
                "school_id": school_id,
                "standard_id": payload.standard_id,
                "name": payload.name,
                "code": payload.code.upper().strip(),
            }
        )
        await self.db.commit()
        await self.db.refresh(obj)
        return obj

    async def list_subjects(
        self,
        school_id: uuid.UUID,
        standard_id: Optional[uuid.UUID],
    ) -> tuple[list[Subject], int]:
        return await self.sub_repo.list_by_standard(school_id, standard_id)

    async def update_subject(
        self,
        subject_id: uuid.UUID,
        payload: SubjectUpdate,
        school_id: uuid.UUID,
    ) -> Subject:
        obj = await self.sub_repo.get_by_id(subject_id, school_id)
        if not obj:
            raise NotFoundException(detail="Subject not found")

        update_data = payload.model_dump(exclude_unset=True)

        if "standard_id" in update_data and update_data["standard_id"] is not None:
            standard = await self.std_repo.get_by_id(update_data["standard_id"], school_id)
            if not standard:
                raise NotFoundException(detail="Standard not found")

        new_code = update_data.get("code")
        if new_code:
            update_data["code"] = new_code.upper().strip()
            if update_data["code"] != obj.code:
                conflict = await self.sub_repo.get_by_code(school_id, update_data["code"])
                if conflict and conflict.id != subject_id:
                    raise ConflictException(
                        detail=f"Subject code '{update_data['code']}' already exists in this school"
                    )

        updated = await self.sub_repo.update(obj, update_data)
        await self.db.commit()
        await self.db.refresh(updated)
        return updated

    async def delete_subject(self, subject_id: uuid.UUID, school_id: uuid.UUID) -> None:
        obj = await self.sub_repo.get_by_id(subject_id, school_id)
        if not obj:
            raise NotFoundException(detail="Subject not found")
        await self.sub_repo.delete(obj)
        await self.db.commit()

    # ── Sections ─────────────────────────────────────────────────────────────

    async def create_section(
        self,
        payload: SectionCreate,
        school_id: uuid.UUID,
    ) -> Section:
        standard = await self.std_repo.get_by_id(payload.standard_id, school_id)
        if not standard:
            raise NotFoundException(detail="Standard not found")

        year = await self.year_repo.get_by_id(payload.academic_year_id, school_id)
        if not year:
            raise NotFoundException(detail="Academic year not found")

        if standard.academic_year_id and standard.academic_year_id != payload.academic_year_id:
            raise ValidationException("Section year must match class academic year")

        section_name = payload.name.strip().upper()
        existing = await self.section_repo.get_by_key(
            school_id=school_id,
            standard_id=payload.standard_id,
            academic_year_id=payload.academic_year_id,
            name=section_name,
        )
        if existing:
            raise ConflictException(
                detail=f"Section '{section_name}' already exists for this class and academic year"
            )

        obj = await self.section_repo.create(
            {
                "school_id": school_id,
                "standard_id": payload.standard_id,
                "academic_year_id": payload.academic_year_id,
                "name": section_name,
                "capacity": payload.capacity,
                "is_active": True,
            }
        )
        await self.db.commit()
        await self.db.refresh(obj)
        return obj

    async def list_sections(
        self,
        school_id: uuid.UUID,
        standard_id: Optional[uuid.UUID],
        academic_year_id: Optional[uuid.UUID],
        include_inactive: bool = False,
    ) -> tuple[list[Section], int]:
        return await self.section_repo.list_by_scope(
            school_id=school_id,
            standard_id=standard_id,
            academic_year_id=academic_year_id,
            include_inactive=include_inactive,
        )

    async def update_section(
        self,
        section_id: uuid.UUID,
        payload: SectionUpdate,
        school_id: uuid.UUID,
    ) -> Section:
        obj = await self.section_repo.get_by_id(section_id, school_id)
        if not obj:
            raise NotFoundException(detail="Section not found")
        updated = await self.section_repo.update(obj, payload.model_dump(exclude_unset=True))
        await self.db.commit()
        await self.db.refresh(updated)
        return updated

    async def delete_section(self, section_id: uuid.UUID, school_id: uuid.UUID) -> None:
        obj = await self.section_repo.get_by_id(section_id, school_id)
        if not obj:
            raise NotFoundException(detail="Section not found")
        await self.section_repo.delete(obj)
        await self.db.commit()

    # ── Grade Master ──────────────────────────────────────────────────────────

    async def create_grade(
        self,
        payload: GradeMasterCreate,
        school_id: uuid.UUID,
    ) -> GradeMaster:
        if payload.min_percent >= payload.max_percent:
            raise ValidationException("min_percent must be less than max_percent")

        existing = await self.grade_repo.get_by_letter(school_id, payload.grade_letter)
        if existing:
            raise ConflictException(
                detail=f"Grade letter '{payload.grade_letter}' already exists for this school"
            )

        obj = await self.grade_repo.create(
            {
                "school_id": school_id,
                "min_percent": payload.min_percent,
                "max_percent": payload.max_percent,
                "grade_letter": payload.grade_letter.upper().strip(),
                "grade_point": payload.grade_point,
            }
        )
        await self.db.commit()
        await self.db.refresh(obj)
        return obj

    async def list_grades(self, school_id: uuid.UUID) -> tuple[list[GradeMaster], int]:
        return await self.grade_repo.list_by_school(school_id)

    async def update_grade(
        self,
        grade_id: uuid.UUID,
        payload: GradeMasterUpdate,
        school_id: uuid.UUID,
    ) -> GradeMaster:
        obj = await self.grade_repo.get_by_id(grade_id, school_id)
        if not obj:
            raise NotFoundException(detail="Grade not found")

        update_data = payload.model_dump(exclude_unset=True)

        new_min = update_data.get("min_percent", obj.min_percent)
        new_max = update_data.get("max_percent", obj.max_percent)
        if new_min >= new_max:
            raise ValidationException("min_percent must be less than max_percent")

        new_letter = update_data.get("grade_letter")
        if new_letter:
            update_data["grade_letter"] = new_letter.upper().strip()
            if update_data["grade_letter"] != obj.grade_letter:
                conflict = await self.grade_repo.get_by_letter(school_id, update_data["grade_letter"])
                if conflict and conflict.id != grade_id:
                    raise ConflictException(
                        detail=f"Grade letter '{update_data['grade_letter']}' already exists"
                    )

        updated = await self.grade_repo.update(obj, update_data)
        await self.db.commit()
        await self.db.refresh(updated)
        return updated

    async def delete_grade(self, grade_id: uuid.UUID, school_id: uuid.UUID) -> None:
        obj = await self.grade_repo.get_by_id(grade_id, school_id)
        if not obj:
            raise NotFoundException(detail="Grade not found")
        await self.grade_repo.delete(obj)
        await self.db.commit()

    async def lookup_grade_by_percent(
        self, school_id: uuid.UUID, percent: float
    ) -> GradeMaster:
        obj = await self.grade_repo.lookup_by_percent(school_id, percent)
        if not obj:
            raise NotFoundException(
                detail=f"No grade mapping found for {percent}%. Please configure grade master."
            )
        return obj
