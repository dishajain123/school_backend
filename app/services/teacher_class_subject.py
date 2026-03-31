import uuid
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.teacher_class_subject import TeacherClassSubjectRepository
from app.repositories.teacher import TeacherRepository
from app.repositories.masters import StandardRepository, SubjectRepository
from app.repositories.academic_year import AcademicYearRepository
from app.schemas.teacher_class_subject import TeacherAssignmentCreate
from app.models.teacher_class_subject import TeacherClassSubject
from app.core.exceptions import (
    NotFoundException,
    ConflictException,
    ForbiddenException,
    ValidationException,
)
from app.core.dependencies import CurrentUser
from app.utils.enums import RoleEnum


class TeacherClassSubjectService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = TeacherClassSubjectRepository(db)
        self.teacher_repo = TeacherRepository(db)
        self.std_repo = StandardRepository(db)
        self.sub_repo = SubjectRepository(db)
        self.year_repo = AcademicYearRepository(db)

    async def create_assignment(
        self,
        payload: TeacherAssignmentCreate,
        school_id: uuid.UUID,
    ) -> TeacherClassSubject:
        # Validate teacher belongs to school
        teacher = await self.teacher_repo.get_by_id(payload.teacher_id, school_id)
        if not teacher:
            raise NotFoundException(detail="Teacher not found in this school")

        # Validate standard belongs to school
        standard = await self.std_repo.get_by_id(payload.standard_id, school_id)
        if not standard:
            raise NotFoundException(detail="Standard not found in this school")

        # Validate subject belongs to school
        subject = await self.sub_repo.get_by_id(payload.subject_id, school_id)
        if not subject:
            raise NotFoundException(detail="Subject not found in this school")

        # Validate subject belongs to the given standard
        if subject.standard_id != payload.standard_id:
            raise ValidationException(
                detail="Subject does not belong to the specified standard"
            )

        # Validate academic year belongs to school
        year = await self.year_repo.get_by_id(payload.academic_year_id, school_id)
        if not year:
            raise NotFoundException(detail="Academic year not found in this school")

        # Guard: duplicate assignment
        duplicate = await self.repo.get_duplicate(
            teacher_id=payload.teacher_id,
            standard_id=payload.standard_id,
            section=payload.section,
            subject_id=payload.subject_id,
            academic_year_id=payload.academic_year_id,
        )
        if duplicate:
            raise ConflictException(
                detail="This teacher is already assigned to this class-subject for the academic year"
            )

        obj = await self.repo.create(
            {
                "teacher_id": payload.teacher_id,
                "standard_id": payload.standard_id,
                "section": payload.section,
                "subject_id": payload.subject_id,
                "academic_year_id": payload.academic_year_id,
            }
        )
        await self.db.commit()

        return await self.repo.get_by_id(obj.id)  # type: ignore[return-value]

    async def delete_assignment(
        self,
        assignment_id: uuid.UUID,
        school_id: uuid.UUID,
    ) -> None:
        obj = await self.repo.get_by_id(assignment_id)
        if not obj:
            raise NotFoundException(detail="Assignment not found")

        # Verify the assignment belongs to this school via teacher
        teacher = await self.teacher_repo.get_by_id(obj.teacher_id, school_id)
        if not teacher:
            raise NotFoundException(detail="Assignment not found in this school")

        await self.repo.delete(obj)
        await self.db.commit()

    async def list_by_teacher(
        self,
        teacher_id: uuid.UUID,
        school_id: uuid.UUID,
        academic_year_id: Optional[uuid.UUID],
        current_user: CurrentUser,
    ) -> tuple[list[TeacherClassSubject], int]:
        # A TEACHER can only view their own assignments
        if current_user.role == RoleEnum.TEACHER:
            teacher = await self.teacher_repo.get_by_user_id(current_user.id)
            if not teacher or teacher.id != teacher_id:
                raise ForbiddenException(detail="Access denied")

        # Verify teacher belongs to school
        teacher = await self.teacher_repo.get_by_id(teacher_id, school_id)
        if not teacher:
            raise NotFoundException(detail="Teacher not found in this school")

        return await self.repo.list_by_teacher(teacher_id, academic_year_id)

    async def list_by_class(
        self,
        standard_id: uuid.UUID,
        section: str,
        school_id: uuid.UUID,
        academic_year_id: Optional[uuid.UUID],
    ) -> tuple[list[TeacherClassSubject], int]:
        # Verify standard belongs to school
        standard = await self.std_repo.get_by_id(standard_id, school_id)
        if not standard:
            raise NotFoundException(detail="Standard not found in this school")

        return await self.repo.list_by_class(standard_id, section, academic_year_id)

    # ── Reusable guard — imported by Attendance, Assignments, Homework, etc. ─

    async def assert_teacher_owns_class_subject(
        self,
        teacher_id: uuid.UUID,
        standard_id: uuid.UUID,
        subject_id: uuid.UUID,
        academic_year_id: uuid.UUID,
        section: Optional[str] = None,
    ) -> TeacherClassSubject:
        """
        Raises 403 if the teacher has no assignment for the given
        standard / subject / academic_year combination.
        Pass `section` for stricter section-level enforcement.
        """
        if section is not None:
            assignment = await self.repo.find_assignment_with_section(
                teacher_id=teacher_id,
                standard_id=standard_id,
                section=section,
                subject_id=subject_id,
                academic_year_id=academic_year_id,
            )
        else:
            assignment = await self.repo.find_assignment(
                teacher_id=teacher_id,
                standard_id=standard_id,
                subject_id=subject_id,
                academic_year_id=academic_year_id,
            )

        if not assignment:
            raise ForbiddenException(
                detail="Teacher is not assigned to this class-subject for the given academic year"
            )
        return assignment