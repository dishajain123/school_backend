import uuid
import math
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.masters import Standard
from app.repositories.student import StudentRepository
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
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = StudentRepository(db)

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

        return await self.repo.list_sections_by_school(
            school_id=school_id,
            standard_id=standard_id,
            academic_year_id=academic_year_id,
        )

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
