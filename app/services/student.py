import uuid
import math
import json
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.masters import Standard
from app.repositories.student import StudentRepository
from app.repositories.settings import SettingsRepository
from app.schemas.student import StudentCreate, StudentUpdate, StudentPromotionUpdate
from app.models.student import Student
from app.core.dependencies import CurrentUser
from app.core.exceptions import (
    NotFoundException,
    ConflictException,
    ForbiddenException,
    ValidationException,
)
from app.utils.enums import RoleEnum, PromotionStatus


async def assert_parent_owns_student(
    student: Student,
    current_user: CurrentUser,
) -> None:
    """
    Global scope enforcement helper.
    Reused by every module that a PARENT can call.
    Raises 403 if the parent does not own the student.
    """
    if current_user.role == RoleEnum.PARENT:
        if student.parent_id != current_user.parent_id:
            raise ForbiddenException("You do not have access to this student")


class StudentService:
    SECTIONS_REGISTRY_KEY = "class_sections_registry"

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = StudentRepository(db)
        self.settings_repo = SettingsRepository(db)

    @staticmethod
    def _normalize_section(section: str) -> str:
        value = (section or "").strip().upper()
        if not value:
            raise ValidationException("Section is required")
        if len(value) > 10:
            raise ValidationException("Section must be <= 10 characters")
        return value

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

    def _collect_registry_sections(
        self,
        registry: dict,
        standard_id: Optional[uuid.UUID],
        academic_year_id: Optional[uuid.UUID],
    ) -> set[str]:
        sections: set[str] = set()
        year_filter = str(academic_year_id) if academic_year_id else None
        standards_bucket = registry.get("standards")
        if not isinstance(standards_bucket, dict):
            return sections

        keys = [str(standard_id)] if standard_id else list(standards_bucket.keys())
        for std_key in keys:
            std_map = standards_bucket.get(std_key)
            if not isinstance(std_map, dict):
                continue

            year_keys = [year_filter, "*"] if year_filter else list(std_map.keys())
            for yk in year_keys:
                if not yk:
                    continue
                rows = std_map.get(yk)
                if not isinstance(rows, list):
                    continue
                for raw in rows:
                    if isinstance(raw, str) and raw.strip():
                        sections.add(raw.strip().upper())
        return sections

    async def _get_and_authorize(
        self,
        student_id: uuid.UUID,
        school_id: uuid.UUID,
        current_user: CurrentUser,
    ) -> Student:
        student = await self.repo.get_by_id(student_id, school_id)
        if not student:
            raise NotFoundException("Student")
        await assert_parent_owns_student(student, current_user)
        return student

    async def create_student(
        self,
        data: StudentCreate,
        school_id: uuid.UUID,
    ) -> Student:
        existing = await self.repo.get_by_admission_number(
            data.admission_number, school_id
        )
        if existing:
            raise ConflictException(
                f"Admission number '{data.admission_number}' already exists in this school"
            )

        if data.user_id:
            existing_user_student = await self.repo.get_by_user_id(data.user_id)
            if existing_user_student:
                raise ConflictException("This user is already linked to another student")

        student = await self.repo.create({
            "user_id": data.user_id,
            "school_id": school_id,
            "parent_id": data.parent_id,
            "standard_id": data.standard_id,
            "academic_year_id": data.academic_year_id,
            "section": data.section,
            "roll_number": data.roll_number,
            "admission_number": data.admission_number,
            "date_of_birth": data.date_of_birth,
            "admission_date": data.admission_date,
            "is_promoted": False,
        })
        return student

    async def get_student(
        self,
        student_id: uuid.UUID,
        school_id: uuid.UUID,
        current_user: CurrentUser,
    ) -> Student:
        return await self._get_and_authorize(student_id, school_id, current_user)

    async def get_my_student_profile(
        self,
        school_id: uuid.UUID,
        current_user: CurrentUser,
    ) -> Student:
        if current_user.role != RoleEnum.STUDENT:
            raise ForbiddenException("Only students can access this endpoint")

        own = await self.repo.get_by_user_id(current_user.id)
        if not own or own.school_id != school_id:
            raise NotFoundException("Student")
        return own

    async def list_students(
        self,
        school_id: uuid.UUID,
        current_user: CurrentUser,
        standard_id: Optional[uuid.UUID] = None,
        section: Optional[str] = None,
        academic_year_id: Optional[uuid.UUID] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Student], int, int]:
        if current_user.role == RoleEnum.PARENT:
            students = await self.repo.list_by_parent(
                current_user.parent_id, school_id
            )
            total = len(students)
            total_pages = 1
            return students, total, total_pages

        if current_user.role == RoleEnum.STUDENT:
            own = await self.repo.get_by_user_id(current_user.id)
            students = [own] if own else []
            return students, len(students), 1

        students, total = await self.repo.list_by_school(
            school_id=school_id,
            standard_id=standard_id,
            section=section,
            academic_year_id=academic_year_id,
            page=page,
            page_size=page_size,
        )
        total_pages = math.ceil(total / page_size) if total > 0 else 1
        return students, total, total_pages

    async def update_student(
        self,
        student_id: uuid.UUID,
        school_id: uuid.UUID,
        data: StudentUpdate,
        current_user: CurrentUser,
    ) -> Student:
        student = await self._get_and_authorize(student_id, school_id, current_user)
        update_data = data.model_dump(exclude_none=True)

        if "user_id" in update_data and update_data["user_id"] != student.user_id:
            existing = await self.repo.get_by_user_id(update_data["user_id"])
            if existing and existing.id != student_id:
                raise ConflictException("This user is already linked to another student")

        return await self.repo.update(student, update_data)

    async def list_sections(
        self,
        school_id: uuid.UUID,
        current_user: CurrentUser,
        standard_id: Optional[uuid.UUID] = None,
        academic_year_id: Optional[uuid.UUID] = None,
    ) -> list[str]:
        # Scope restrictions for parent/student.
        if current_user.role == RoleEnum.PARENT:
            students = await self.repo.list_by_parent(current_user.parent_id, school_id)
            sections = {
                (s.section or "").strip()
                for s in students
                if (not standard_id or s.standard_id == standard_id)
                and (not academic_year_id or s.academic_year_id == academic_year_id)
                and s.section
                and s.section.strip()
            }
            return sorted(sections, key=lambda x: x.lower())

        if current_user.role == RoleEnum.STUDENT:
            own = await self.repo.get_by_user_id(current_user.id)
            if not own or not own.section or not own.section.strip():
                return []
            if standard_id and own.standard_id != standard_id:
                return []
            if academic_year_id and own.academic_year_id != academic_year_id:
                return []
            return [own.section.strip()]

        db_sections = await self.repo.list_sections_by_school(
            school_id=school_id,
            standard_id=standard_id,
            academic_year_id=academic_year_id,
        )
        registry = await self._load_sections_registry(school_id)
        sections = {s.strip().upper() for s in db_sections if s and s.strip()}
        sections.update(
            self._collect_registry_sections(
                registry=registry,
                standard_id=standard_id,
                academic_year_id=academic_year_id,
            )
        )
        return sorted(sections, key=lambda x: x.lower())

    async def create_section(
        self,
        *,
        school_id: uuid.UUID,
        current_user: CurrentUser,
        standard_id: uuid.UUID,
        section: str,
        academic_year_id: Optional[uuid.UUID] = None,
    ) -> tuple[str, list[str], Optional[uuid.UUID]]:
        normalized = self._normalize_section(section)

        standard_result = await self.db.execute(
            select(Standard).where(
                Standard.id == standard_id,
                Standard.school_id == school_id,
            )
        )
        standard = standard_result.scalar_one_or_none()
        if not standard:
            raise NotFoundException("Standard")

        effective_year_id = academic_year_id or standard.academic_year_id
        if (
            standard.academic_year_id is not None
            and effective_year_id is not None
            and standard.academic_year_id != effective_year_id
        ):
            raise ValidationException(
                "Section academic_year_id must match the selected class academic year"
            )

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

        year_key = str(effective_year_id) if effective_year_id else "*"
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
            updated_by=current_user.id,
        )
        await self.db.commit()

        sections = await self.list_sections(
            school_id=school_id,
            current_user=current_user,
            standard_id=standard_id,
            academic_year_id=effective_year_id,
        )
        return normalized, sections, effective_year_id

    async def update_promotion_status(
        self,
        student_id: uuid.UUID,
        school_id: uuid.UUID,
        data: StudentPromotionUpdate,
        current_user: CurrentUser,
    ) -> Student:
        student = await self.repo.get_by_id(student_id, school_id)
        if not student:
            raise NotFoundException("Student")

        update_payload: dict = {
            "is_promoted": data.promotion_status == PromotionStatus.PROMOTED
        }

        # When promoted manually, move student to the next class immediately.
        if data.promotion_status == PromotionStatus.PROMOTED:
            if not student.standard_id:
                raise ValidationException("Student class is not set")
            if not student.academic_year_id:
                raise ValidationException("Student academic year is not set")

            current_standard_result = await self.db.execute(
                select(Standard).where(
                    and_(
                        Standard.id == student.standard_id,
                        Standard.school_id == school_id,
                    )
                )
            )
            current_standard = current_standard_result.scalar_one_or_none()
            if not current_standard:
                raise ValidationException("Current class not found for student")

            next_standard_result = await self.db.execute(
                select(Standard).where(
                    and_(
                        Standard.school_id == school_id,
                        Standard.level == current_standard.level + 1,
                        Standard.academic_year_id == student.academic_year_id,
                    )
                )
            )
            next_standard = next_standard_result.scalar_one_or_none()
            if not next_standard:
                raise ValidationException(
                    "Next class is not configured for this academic year"
                )

            update_payload["standard_id"] = next_standard.id

        student = await self.repo.update(student, update_payload)

        # Record/update yearly promotion history for both statuses.
        from app.repositories.promotion import PromotionRepository
        promo_repo = PromotionRepository(self.db)
        if student.standard_id and student.academic_year_id:
            latest = await promo_repo.get_latest_history(
                student.id, student.academic_year_id
            )
            promoted_to_standard_id = (
                student.standard_id
                if data.promotion_status == PromotionStatus.PROMOTED
                else None
            )
            if latest:
                latest.standard_id = student.standard_id
                latest.section = student.section
                latest.promoted_to_standard_id = promoted_to_standard_id
                latest.promotion_status = data.promotion_status
                latest.recorded_at = datetime.now(timezone.utc)
                latest.school_id = school_id
            else:
                await promo_repo.create_history(
                    {
                        "student_id": student.id,
                        "standard_id": student.standard_id,
                        "section": student.section,
                        "academic_year_id": student.academic_year_id,
                        "promoted_to_standard_id": promoted_to_standard_id,
                        "promotion_status": data.promotion_status,
                        "school_id": school_id,
                    }
                )
            await self.db.commit()

        updated = await self.repo.get_by_id(student_id, school_id)
        return updated

    async def bulk_update_promotion_status(
        self,
        student_ids: list[uuid.UUID],
        school_id: uuid.UUID,
        data: StudentPromotionUpdate,
        current_user: CurrentUser,
    ) -> list[Student]:
        # Keep order stable and avoid duplicate work.
        unique_ids: list[uuid.UUID] = []
        seen: set[uuid.UUID] = set()
        for sid in student_ids:
            if sid in seen:
                continue
            seen.add(sid)
            unique_ids.append(sid)

        updated_items: list[Student] = []
        for sid in unique_ids:
            updated = await self.update_promotion_status(
                student_id=sid,
                school_id=school_id,
                data=data,
                current_user=current_user,
            )
            if updated:
                updated_items.append(updated)
        return updated_items

    async def bulk_update_promotion_status_by_section(
        self,
        standard_id: uuid.UUID,
        section: str,
        school_id: uuid.UUID,
        data: StudentPromotionUpdate,
        current_user: CurrentUser,
        academic_year_id: Optional[uuid.UUID] = None,
        excluded_student_ids: Optional[list[uuid.UUID]] = None,
    ) -> list[Student]:
        normalized_section = self._normalize_section(section)
        excluded = set(excluded_student_ids or [])

        page = 1
        page_size = 100
        eligible_ids: list[uuid.UUID] = []

        while True:
            rows, total = await self.repo.list_by_school(
                school_id=school_id,
                standard_id=standard_id,
                section=normalized_section,
                academic_year_id=academic_year_id,
                page=page,
                page_size=page_size,
            )
            for student in rows:
                if student.id not in excluded:
                    eligible_ids.append(student.id)

            if not rows:
                break

            total_pages = math.ceil(total / page_size) if total > 0 else 1
            if page >= total_pages:
                break
            page += 1

        if not eligible_ids:
            return []

        return await self.bulk_update_promotion_status(
            student_ids=eligible_ids,
            school_id=school_id,
            data=data,
            current_user=current_user,
        )
