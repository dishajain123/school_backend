import uuid
import json
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.teacher_class_subject import TeacherClassSubjectRepository
from app.repositories.teacher import TeacherRepository
from app.repositories.masters import StandardRepository, SubjectRepository
from app.repositories.masters import SectionRepository
from app.repositories.academic_year import AcademicYearRepository
from app.repositories.settings import SettingsRepository
from app.schemas.teacher_class_subject import (
    TeacherAssignmentCreate,
    TeacherAssignmentUpdate,
)
from app.models.teacher_class_subject import TeacherClassSubject
from app.core.exceptions import (
    NotFoundException,
    ConflictException,
    ForbiddenException,
    ValidationException,
)
from app.core.dependencies import CurrentUser
from app.utils.enums import RoleEnum, UserStatus


class TeacherClassSubjectService:
    SECTIONS_REGISTRY_KEY = "class_sections_registry"

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = TeacherClassSubjectRepository(db)
        self.teacher_repo = TeacherRepository(db)
        self.std_repo = StandardRepository(db)
        self.sub_repo = SubjectRepository(db)
        self.year_repo = AcademicYearRepository(db)
        self.settings_repo = SettingsRepository(db)
        self.section_repo = SectionRepository(db)

    @staticmethod
    def _normalize_optional_section(section: Optional[str]) -> Optional[str]:
        if section is None:
            return None
        value = section.strip().upper()
        return value if value else None

    @staticmethod
    def _ensure_teacher_is_approved(teacher) -> None:
        user = getattr(teacher, "user", None)
        if not user:
            raise ValidationException(detail="Teacher must be linked to a user account")
        if user.status != UserStatus.ACTIVE or not user.is_active:
            raise ValidationException(
                detail="Teacher assignment is allowed only for approved active teachers"
            )

    async def _resolve_teacher_in_school(
        self,
        teacher_identifier: uuid.UUID,
        school_id: uuid.UUID,
    ):
        """
        Backward-compatible resolver:
        - preferred: teacher_identifier is Teacher.id
        - fallback: teacher_identifier is User.id linked to Teacher
        """
        teacher = await self.teacher_repo.get_by_id(teacher_identifier, school_id)
        if teacher:
            return teacher

        teacher_by_user = await self.teacher_repo.get_by_user_id(
            teacher_identifier,
            school_id=school_id,
        )
        if teacher_by_user and teacher_by_user.school_id == school_id:
            return teacher_by_user
        return None

    async def _load_sections_registry(self, school_id: uuid.UUID) -> dict:
        setting = await self.settings_repo.get_by_key(
            school_id,
            self.SECTIONS_REGISTRY_KEY,
        )
        if not setting or not setting.setting_value:
            return {}
        try:
            parsed = json.loads(setting.setting_value)
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError):
            return {}

    async def _register_section_for_school(
        self,
        *,
        school_id: uuid.UUID,
        standard_id: Optional[uuid.UUID],
        academic_year_id: Optional[uuid.UUID],
        section: Optional[str],
    ) -> None:
        normalized = self._normalize_optional_section(section)
        if standard_id is None or normalized is None:
            return

        registry = await self._load_sections_registry(school_id)
        standards_map = registry.setdefault("standards", {})
        if not isinstance(standards_map, dict):
            standards_map = {}
            registry["standards"] = standards_map

        std_key = str(standard_id)
        std_map = standards_map.setdefault(std_key, {})
        if not isinstance(std_map, dict):
            std_map = {}
            standards_map[std_key] = std_map

        year_key = str(academic_year_id) if academic_year_id else "*"
        section_list = std_map.setdefault(year_key, [])
        if not isinstance(section_list, list):
            section_list = []
            std_map[year_key] = section_list

        existing = {str(s).strip().upper() for s in section_list if str(s).strip()}
        existing.add(normalized)
        std_map[year_key] = sorted(existing, key=lambda x: x.lower())

        await self.settings_repo.upsert_settings(
            school_id=school_id,
            items=[
                {
                    "key": self.SECTIONS_REGISTRY_KEY,
                    "value": json.dumps(registry, separators=(",", ":")),
                }
            ],
            updated_by=None,
        )

    async def create_assignment(
        self,
        payload: TeacherAssignmentCreate,
        school_id: uuid.UUID,
    ) -> TeacherClassSubject:
        normalized_section = self._normalize_optional_section(payload.section)
        if normalized_section is None:
            raise ValidationException(detail="Section is required")

        # Validate teacher belongs to school
        teacher = await self._resolve_teacher_in_school(payload.teacher_id, school_id)
        if not teacher:
            raise NotFoundException(detail="Teacher not found in this school")
        self._ensure_teacher_is_approved(teacher)

        # Validate standard belongs to school
        standard = await self.std_repo.get_by_id(payload.standard_id, school_id)
        if not standard:
            raise NotFoundException(detail="Standard not found in this school")

        # Validate subject belongs to school
        subject = await self.sub_repo.get_by_id(payload.subject_id, school_id)
        if not subject:
            raise NotFoundException(detail="Subject not found in this school")

        # Subject can be global (standard_id is NULL) or class-specific.
        if subject.standard_id is not None and subject.standard_id != payload.standard_id:
            raise ValidationException(
                detail="Subject does not belong to the specified standard"
            )

        # Validate academic year belongs to school
        year = await self.year_repo.get_by_id(payload.academic_year_id, school_id)
        if not year:
            raise NotFoundException(detail="Academic year not found in this school")

        # Enforce section must exist for selected class + year and be active.
        section_obj = await self.section_repo.get_by_key(
            school_id=school_id,
            standard_id=payload.standard_id,
            academic_year_id=payload.academic_year_id,
            name=normalized_section,
        )
        if not section_obj or not section_obj.is_active:
            raise ValidationException(
                detail="Section not found or inactive for the selected class and academic year"
            )

        # Guard: duplicate assignment
        duplicate = await self.repo.get_duplicate(
            teacher_id=teacher.id,
            standard_id=payload.standard_id,
            section=normalized_section,
            subject_id=payload.subject_id,
            academic_year_id=payload.academic_year_id,
        )
        if duplicate:
            raise ConflictException(
                detail="This teacher is already assigned to this class-subject for the academic year"
            )

        obj = await self.repo.create(
            {
                "teacher_id": teacher.id,
                "standard_id": payload.standard_id,
                "section": normalized_section,
                "subject_id": payload.subject_id,
                "academic_year_id": payload.academic_year_id,
            }
        )
        await self._register_section_for_school(
            school_id=school_id,
            standard_id=payload.standard_id,
            academic_year_id=payload.academic_year_id,
            section=normalized_section,
        )

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
        self._ensure_teacher_is_approved(teacher)

        await self.repo.delete(obj)

    async def update_assignment(
        self,
        assignment_id: uuid.UUID,
        payload: TeacherAssignmentUpdate,
        school_id: uuid.UUID,
    ) -> TeacherClassSubject:
        normalized_section = self._normalize_optional_section(payload.section)
        if normalized_section is None:
            raise ValidationException(detail="Section is required")

        obj = await self.repo.get_by_id(assignment_id)
        if not obj:
            raise NotFoundException(detail="Assignment not found")

        teacher = await self.teacher_repo.get_by_id(obj.teacher_id, school_id)
        if not teacher:
            raise NotFoundException(detail="Assignment not found in this school")
        self._ensure_teacher_is_approved(teacher)

        standard = await self.std_repo.get_by_id(payload.standard_id, school_id)
        if not standard:
            raise NotFoundException(detail="Standard not found in this school")

        subject = await self.sub_repo.get_by_id(payload.subject_id, school_id)
        if not subject:
            raise NotFoundException(detail="Subject not found in this school")

        if subject.standard_id is not None and subject.standard_id != payload.standard_id:
            raise ValidationException(
                detail="Subject does not belong to the specified standard"
            )

        year = await self.year_repo.get_by_id(payload.academic_year_id, school_id)
        if not year:
            raise NotFoundException(detail="Academic year not found in this school")

        section_obj = await self.section_repo.get_by_key(
            school_id=school_id,
            standard_id=payload.standard_id,
            academic_year_id=payload.academic_year_id,
            name=normalized_section,
        )
        if not section_obj or not section_obj.is_active:
            raise ValidationException(
                detail="Section not found or inactive for the selected class and academic year"
            )

        duplicate = await self.repo.get_duplicate_excluding(
            assignment_id=assignment_id,
            teacher_id=obj.teacher_id,
            standard_id=payload.standard_id,
            section=normalized_section,
            subject_id=payload.subject_id,
            academic_year_id=payload.academic_year_id,
        )
        if duplicate:
            raise ConflictException(
                detail="This teacher is already assigned to this class-subject for the academic year"
            )

        updated = await self.repo.update(
            obj,
            {
                "standard_id": payload.standard_id,
                "section": normalized_section,
                "subject_id": payload.subject_id,
                "academic_year_id": payload.academic_year_id,
            },
        )
        await self._register_section_for_school(
            school_id=school_id,
            standard_id=payload.standard_id,
            academic_year_id=payload.academic_year_id,
            section=normalized_section,
        )
        return await self.repo.get_by_id(updated.id)  # type: ignore[return-value]

    async def list_by_teacher(
        self,
        teacher_id: uuid.UUID,
        school_id: uuid.UUID,
        academic_year_id: Optional[uuid.UUID],
        current_user: CurrentUser,
    ) -> tuple[list[TeacherClassSubject], int]:
        # A TEACHER can only view their own assignments
        if current_user.role == RoleEnum.TEACHER:
            teacher = await self.teacher_repo.get_by_user_id(
                current_user.id,
                school_id=school_id,
            )
            if not teacher or (teacher.id != teacher_id and teacher.user_id != teacher_id):
                raise ForbiddenException(detail="Access denied")

        # Verify teacher belongs to school
        teacher = await self._resolve_teacher_in_school(teacher_id, school_id)
        if not teacher:
            raise NotFoundException(detail="Teacher not found in this school")

        return await self.repo.list_by_teacher(teacher.id, academic_year_id)

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

    async def list_by_standard(
        self,
        standard_id: uuid.UUID,
        school_id: uuid.UUID,
        academic_year_id: Optional[uuid.UUID],
    ) -> tuple[list[TeacherClassSubject], int]:
        standard = await self.std_repo.get_by_id(standard_id, school_id)
        if not standard:
            raise NotFoundException(detail="Standard not found in this school")
        return await self.repo.list_by_standard(standard_id, academic_year_id)

    async def list_mine(
        self,
        current_user: CurrentUser,
        school_id: uuid.UUID,
        academic_year_id: Optional[uuid.UUID],
    ) -> tuple[list[TeacherClassSubject], int]:
        if current_user.role != RoleEnum.TEACHER:
            raise ForbiddenException(detail="Only teachers can access own assignments")

        teacher = await self.teacher_repo.get_by_user_id(
            current_user.id,
            school_id=school_id,
        )
        if not teacher or teacher.school_id != school_id:
            raise NotFoundException(detail="Teacher profile not found in this school")

        return await self.repo.list_by_teacher(teacher.id, academic_year_id)

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
