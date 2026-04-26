import uuid
from typing import Optional
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.dependencies import CurrentUser
from app.repositories.academic_year import AcademicYearRepository
from app.schemas.academic_year import (
    AcademicYearCreate,
    AcademicYearUpdate,
    AcademicStructureValidation,
    AcademicStructureCopyRequest,
    AcademicStructureCopyResponse,
)
from app.schemas.masters import (
    AcademicStructureTreeResponse,
    StandardTreeNode,
    SectionResponse,
    SubjectResponse,
)
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

    async def validate_structure(
        self, year_id: uuid.UUID, school_id: uuid.UUID
    ) -> AcademicStructureValidation:
        from app.models.masters import Standard, Subject
        from app.models.section import Section

        stds_result = await self.db.execute(
            select(Standard).where(
                Standard.school_id == school_id,
                Standard.academic_year_id == year_id,
            ).order_by(Standard.level)
        )
        standards = stds_result.scalars().all()

        errors: list[str] = []
        warnings: list[str] = []
        without_subjects: list[str] = []
        without_sections: list[str] = []

        for std in standards:
            subj_result = await self.db.execute(
                select(func.count(Subject.id)).where(Subject.standard_id == std.id)
            )
            subj_count = subj_result.scalar_one()
            if subj_count == 0:
                errors.append(f"{std.name} has no subjects defined.")
                without_subjects.append(std.name)

            sec_result = await self.db.execute(
                select(func.count(Section.id)).where(
                    Section.standard_id == std.id,
                    Section.academic_year_id == year_id,
                    Section.is_active == True,
                )
            )
            sec_count = sec_result.scalar_one()
            if sec_count == 0:
                warnings.append(f"{std.name} has no sections defined.")
                without_sections.append(std.name)

        if len(standards) == 0:
            errors.append("No classes (standards) defined for this academic year.")

        total_sections_result = await self.db.execute(
            select(func.count(Section.id)).where(
                Section.academic_year_id == year_id,
                Section.school_id == school_id,
            )
        )

        return AcademicStructureValidation(
            is_valid=len(errors) == 0,
            total_standards=len(standards),
            standards_with_subjects=len(standards) - len(without_subjects),
            standards_without_subjects=without_subjects,
            total_sections=total_sections_result.scalar_one(),
            standards_without_sections=without_sections,
            warnings=warnings,
            errors=errors,
        )

    async def copy_structure(
        self,
        data: AcademicStructureCopyRequest,
        actor: CurrentUser,
    ) -> AcademicStructureCopyResponse:
        from app.models.masters import Standard, Subject
        from app.models.section import Section
        from app.models.academic_structure_copy import AcademicStructureCopy

        school_id = actor.school_id
        source_stds_result = await self.db.execute(
            select(Standard).where(
                Standard.school_id == school_id,
                Standard.academic_year_id == data.source_year_id,
            ).order_by(Standard.level)
        )
        source_stds = source_stds_result.scalars().all()

        stds_created = subjs_created = secs_created = skipped = 0
        warnings: list[str] = []

        for src_std in source_stds:
            existing_std_result = await self.db.execute(
                select(Standard).where(
                    Standard.school_id == school_id,
                    Standard.academic_year_id == data.target_year_id,
                    Standard.level == src_std.level,
                )
            )
            target_std = existing_std_result.scalar_one_or_none()

            if target_std is None and data.copy_standards:
                target_std = Standard(
                    school_id=school_id,
                    academic_year_id=data.target_year_id,
                    name=src_std.name,
                    level=src_std.level,
                )
                self.db.add(target_std)
                await self.db.flush()
                stds_created += 1
            elif target_std is not None:
                skipped += 1
                warnings.append(
                    f"{src_std.name} (level {src_std.level}) already exists - skipped."
                )

            if target_std is None:
                continue

            if data.copy_subjects:
                subjs_result = await self.db.execute(
                    select(Subject).where(Subject.standard_id == src_std.id)
                )
                for src_subj in subjs_result.scalars().all():
                    existing_subj = await self.db.execute(
                        select(Subject).where(
                            Subject.standard_id == target_std.id,
                            Subject.code == src_subj.code,
                        )
                    )
                    if existing_subj.scalar_one_or_none() is None:
                        new_subj = Subject(
                            school_id=school_id,
                            standard_id=target_std.id,
                            name=src_subj.name,
                            code=src_subj.code,
                        )
                        self.db.add(new_subj)
                        subjs_created += 1

            if data.copy_sections:
                secs_result = await self.db.execute(
                    select(Section).where(
                        Section.standard_id == src_std.id,
                        Section.academic_year_id == data.source_year_id,
                    )
                )
                for src_sec in secs_result.scalars().all():
                    existing_sec = await self.db.execute(
                        select(Section).where(
                            Section.standard_id == target_std.id,
                            Section.academic_year_id == data.target_year_id,
                            Section.name == src_sec.name,
                        )
                    )
                    if existing_sec.scalar_one_or_none() is None:
                        new_sec = Section(
                            school_id=school_id,
                            standard_id=target_std.id,
                            academic_year_id=data.target_year_id,
                            name=src_sec.name,
                            is_active=True,
                            capacity=src_sec.capacity,
                        )
                        self.db.add(new_sec)
                        secs_created += 1

        await self.db.flush()

        src_year = await self.repo.get_by_id(data.source_year_id, school_id)
        tgt_year = await self.repo.get_by_id(data.target_year_id, school_id)

        copy_record = AcademicStructureCopy(
            school_id=school_id,
            source_year_id=data.source_year_id,
            target_year_id=data.target_year_id,
            performed_by_id=actor.id,
            standards_copied=stds_created,
            subjects_copied=subjs_created,
            sections_copied=secs_created,
            summary={"skipped": skipped, "warnings": warnings},
        )
        self.db.add(copy_record)
        await self.db.commit()

        return AcademicStructureCopyResponse(
            source_year_name=src_year.name if src_year else "Unknown",
            target_year_name=tgt_year.name if tgt_year else "Unknown",
            standards_copied=stds_created,
            subjects_copied=subjs_created,
            sections_copied=secs_created,
            skipped_duplicates=skipped,
            warnings=warnings,
        )

    async def get_structure_tree(
        self, year_id: uuid.UUID, school_id: uuid.UUID
    ) -> AcademicStructureTreeResponse:
        from app.models.masters import Standard, Subject
        from app.models.section import Section

        year = await self.repo.get_by_id(year_id, school_id)
        if not year:
            raise NotFoundException("Academic year")

        stds_result = await self.db.execute(
            select(Standard).where(
                Standard.school_id == school_id,
                Standard.academic_year_id == year_id,
            ).order_by(Standard.level)
        )
        standards = stds_result.scalars().all()

        tree_nodes: list[StandardTreeNode] = []
        for std in standards:
            secs_result = await self.db.execute(
                select(Section).where(
                    Section.standard_id == std.id,
                    Section.academic_year_id == year_id,
                ).order_by(Section.name)
            )
            sections = secs_result.scalars().all()

            subjs_result = await self.db.execute(
                select(Subject).where(Subject.standard_id == std.id).order_by(Subject.name)
            )
            subjects = subjs_result.scalars().all()

            tree_nodes.append(
                StandardTreeNode(
                    id=std.id,
                    name=std.name,
                    level=std.level,
                    sections=[SectionResponse.model_validate(s) for s in sections],
                    subjects=[SubjectResponse.model_validate(s) for s in subjects],
                    section_count=len(sections),
                    subject_count=len(subjects),
                )
            )

        return AcademicStructureTreeResponse(
            academic_year_id=year.id,
            academic_year_name=year.name,
            is_active=year.is_active,
            standards=tree_nodes,
        )


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
